from __future__ import annotations

import os
from pathlib import Path

import typer

from evalyn.targets.loader import AllowlistError, PackError, load_pack

app = typer.Typer(help="Evalyn — evaluation agent for LLM-powered products.", no_args_is_help=True)

#: The cockpit tells a launched run its identity through the child's env; this
#: is the ONLY place that env var is read. Everything below the CLI takes the id
#: as a parameter, so no engine function's behaviour depends on ambient state.
RUN_ID_ENV = "EVALYN_RUN_ID"


def _run_id_from_env() -> str | None:
    """The launcher-assigned run id, or `None` to mint one as usual.

    Read at command entry so the server knows the artifact path
    (`runs/<run_id><suffix>.json`) *before* the run starts — no newest-file
    heuristic, and no race between two runs finishing in the same second.

    **A bad value is ignored, never fatal.** A stale export in an operator's
    shell, or a launcher bug, must not be able to abort a run: the fallback —
    mint as always — is always correct. It is loud on stderr, never silent.
    """
    raw = os.environ.get(RUN_ID_ENV)
    if not raw:
        return None
    # the ONE grammar (R4-7): the frozen contract's own predicate, imported
    # lazily so `evalyn --help` stays free of the ui layer
    from evalyn.ui.models import is_run_id
    if not is_run_id(raw):
        typer.echo(f"warning: ignoring invalid {RUN_ID_ENV} {raw!r} — the run "
                   f"artifact will be named as usual", err=True)
        return None
    return raw


#: `--events` help text, shared by the three modes so it cannot drift.
EVENTS_HELP = ("Write a live JSONL event stream next to the run artifact "
               "(`runs/<run_id>....events.jsonl`), for `evalyn ui`. Off by "
               "default, and off means nothing is written and no sink is even "
               "constructed.")

#: Artifact filename suffix per mode — the same suffixes the writers use.
_MODE_SUFFIX = {"gate": "", "compare": "-compare", "discover": "-discover"}


def _open_sink(events: bool, *, mode: str, pack_name: str, out_dir: str,
               run_id: str | None):
    """`(sink, run_id)`. Without `--events` this is `(NULL_SINK, run_id)`.

    **Nothing is imported, constructed or created when `events` is false** —
    that is what `tests/engine/test_events_noop.py`'s constructor-interdiction
    proof checks, and it is why `JsonlSink` is reached through the module
    (`events_mod.JsonlSink`) rather than bound at import time: a test can then
    replace it with a sentinel and watch nobody call it.

    With `--events` the run id is minted HERE if the launcher did not supply
    one, because the stream's path is derived from the artifact's — and the
    artifact does not exist yet. That derivation is `ui.paths.events_path`,
    never a hand-built `.events.jsonl` string (Task 2 owns the layout).
    """
    from evalyn.engine import events as events_mod

    if not events:
        return events_mod.NULL_SINK, run_id
    from evalyn.engine.run import new_run_id
    from evalyn.ui.paths import events_path

    if run_id is None:
        run_id = new_run_id(pack_name)
    artifact = Path(out_dir) / f"{run_id}{_MODE_SUFFIX[mode]}.json"
    return (events_mod.JsonlSink(events_path(artifact), run_id=run_id, mode=mode),
            run_id)


@app.command()
def gate(
    target: str = typer.Option(..., "--target", help="Path to a target pack directory."),
    judge_model: str = typer.Option("mockllm/model", "--judge-model"),
    rubric_judge_model: str = typer.Option(
        None, "--rubric-judge-model",
        help="Tier-3 rubric judge model (default: the pack's judge.rubric_model)."),
    allow_uncalibrated: bool = typer.Option(
        False, "--allow-uncalibrated",
        help="Run rubric checks despite a missing/stale calibration record "
             "(loud warning; rubric scores marked untrusted in the artifact)."),
    baseline: str = typer.Option("runs/baseline.json", "--baseline"),
    update_baseline: bool = typer.Option(False, "--update-baseline"),
    force_baseline: bool = typer.Option(
        False, "--force-baseline",
        help="With --update-baseline: bless the run even when its artifact is "
             "untrusted (uncalibrated rubric scores) or incomplete (probes "
             "with zero scored trials). Loud warning; use deliberately."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    out_dir: str = typer.Option(
        "runs", "--out-dir", help="Directory the run artifact is written to."),
    events: bool = typer.Option(False, "--events", help=EVENTS_HELP),
    debug: bool = typer.Option(
        False, "--debug",
        help="Re-raise errors with full tracebacks instead of clean exit-2 messages."),
):
    """Run the deterministic probe suite against a target and diff vs baseline."""
    from evalyn.engine import run as run_mod
    from evalyn.engine.baseline import load_baseline, save_baseline
    from evalyn.engine.budget import BudgetExceeded
    from evalyn.engine.gate import evaluate_gate
    from evalyn.engine.validate import validate_pack
    from evalyn.targets.loader import resolve_base_url

    run_id = _run_id_from_env()  # at command entry: a bad value warns here, early
    try:
        pack = load_pack(target)
        base_url = resolve_base_url(pack)  # enforces allowlist
    except (PackError, AllowlistError) as e:
        if debug:
            raise
        typer.echo(f"gate: setup error: {e}", err=True)
        raise typer.Exit(2)

    # Fail closed on a broken pack before any evaluation (including --dry-run):
    # malformed checks silently no-op or crash at scoring time.
    report = validate_pack(pack)
    for w in report.warnings:
        typer.echo(f"warning: {w}")
    for err in report.errors:
        typer.echo(f"error: {err}", err=True)
    if not report.ok:
        typer.echo("gate: setup error: pack failed validation "
                   "(see errors above; `evalyn validate-pack` reproduces them)", err=True)
        raise typer.Exit(2)

    has_classifier = any(c.type == "classifier" for p in pack.probes for c in p.checks)
    if judge_model.startswith("mockllm") and has_classifier:
        typer.echo("warning: judge model is mockllm — classifier checks fail closed "
                   "(scored UNSURE); pass a real --judge-model for classifier scoring",
                   err=True)

    # Fail-closed judge calibration: rubric checks are refused (setup error)
    # until `evalyn calibrate` has recorded >= threshold agreement for the
    # current rubrics + judge model, unless --allow-uncalibrated.
    has_rubric = any(c.type == "rubric" for p in pack.probes for c in p.checks)
    rubric_untrusted = False
    if has_rubric and not dry_run:
        from evalyn.engine.calibrate import is_stale

        rubric_model = rubric_judge_model or pack.spec.judge.rubric_model
        stale, why = is_stale(pack, rubric_model)
        if stale and not allow_uncalibrated:
            typer.echo(f"gate: setup error: rubric checks require calibration ({why}); "
                       f"run `evalyn calibrate --target {target}` or pass "
                       f"--allow-uncalibrated", err=True)
            raise typer.Exit(2)
        if stale:
            typer.echo(f"warning: running UNCALIBRATED rubric checks ({why}) — "
                       f"rubric scores are untrusted", err=True)
            rubric_untrusted = True

    if dry_run:
        typer.echo(f"gate (dry-run): pack '{pack.spec.name}', {len(pack.probes)} probes, "
                   f"target {base_url}, judge {judge_model}. No calls made.")
        raise typer.Exit(0)

    try:
        sink, run_id = _open_sink(events, mode="gate", pack_name=pack.spec.name,
                                  out_dir=out_dir, run_id=run_id)
    except Exception as e:  # unwritable --out-dir, a stream another pid owns
        if debug:
            raise
        typer.echo(f"gate: setup error: --events stream unavailable: {e}", err=True)
        raise typer.Exit(2)

    try:
        art = run_mod.run_gate(pack, judge_model=judge_model,
                               rubric_judge_model=rubric_judge_model,
                               rubric_scores_untrusted=rubric_untrusted,
                               out_dir=out_dir, run_id=run_id, sink=sink)
    except BudgetExceeded as e:
        if debug:
            raise
        typer.echo(f"gate: budget exceeded: {e} — partial run artifact is on "
                   f"disk under {out_dir}/ for inspection", err=True)
        raise typer.Exit(2)
    except Exception as e:  # connection / infra
        if debug:
            raise
        typer.echo(f"gate: run error: {e}", err=True)
        raise typer.Exit(2)
    finally:
        # Every gate event is emitted inside run_gate; what follows is baseline
        # diffing and rendering, which emits nothing. `close` is idempotent and
        # never raises.
        sink.close()

    if update_baseline:
        # Round-2 N4: refuse to bless artifacts every future gate diff would
        # silently trust — untrusted rubric scores or probes with zero scored
        # trials. --force-baseline is the loud, deliberate escape hatch.
        problems = []
        if art.rubric_scores_untrusted:
            problems.append("its rubric scores are UNTRUSTED "
                            "(--allow-uncalibrated run)")
        zero_trials = sorted(p.id for p in art.probes if p.trials == 0)
        if zero_trials:
            problems.append("probe(s) with zero scored trials: "
                            + ", ".join(zero_trials))
        incomplete = sorted(p.id for p in art.probes
                            if p.expected_trials
                            and 0 < p.trials < p.expected_trials)
        if incomplete:
            problems.append("probe(s) INCOMPLETE (fewer scored trials than "
                            "expected): " + ", ".join(incomplete))
        if problems and not force_baseline:
            typer.echo("gate: refusing --update-baseline: "
                       + "; ".join(problems)
                       + " — a blessed baseline must come from a trusted, "
                         "fully-scored run (pass --force-baseline to bless "
                         "anyway)", err=True)
            raise typer.Exit(2)
        if problems:
            typer.echo("warning: FORCING baseline update despite: "
                       + "; ".join(problems), err=True)
        # Echo the verdict being blessed — an explicit bless never blocks, but
        # blessing a FAIL should be a visible, deliberate act.
        verdict = evaluate_gate(art, None)
        typer.echo(f"gate: blessing {'FAIL' if verdict.exit_code else 'PASS'} verdict "
                   f"({len(verdict.failures)} failure(s), "
                   f"{len(verdict.quarantined)} quarantined)")
        save_baseline(art, baseline)
        typer.echo(f"gate: baseline updated at {baseline}")
        raise typer.Exit(0)

    try:
        baseline_art = load_baseline(baseline)
    except RuntimeError as e:  # corrupt JSON or pre-Plan-#2a schema
        if debug:
            raise
        typer.echo(f"gate: baseline error: {e}", err=True)
        raise typer.Exit(2)
    if baseline_art is not None:
        if baseline_art.pack_hash != art.pack_hash:
            typer.echo(f"warning: baseline pack hash `{baseline_art.pack_hash[:12]}` differs "
                       f"from current `{art.pack_hash[:12]}` — baseline may be stale")
        missing = sorted({p.id for p in baseline_art.probes} - {p.id for p in art.probes})
        if missing:
            typer.echo(f"warning: probe(s) in baseline but absent from current run "
                       f"(invisible to the gate): {', '.join(missing)}")

    result = evaluate_gate(art, baseline_art)
    typer.echo(result.report_md)
    raise typer.Exit(result.exit_code)


@app.command()
def compare(
    target: str = typer.Option(..., "--target", help="Path to a target pack directory."),
    a: str = typer.Option(..., "--a", help="Path to gate run artifact A."),
    b: str = typer.Option(..., "--b", help="Path to gate run artifact B."),
    label_a: str = typer.Option("A", "--label-a", help="Display label for side A."),
    label_b: str = typer.Option("B", "--label-b", help="Display label for side B."),
    rubric_judge_model: str = typer.Option(
        None, "--rubric-judge-model",
        help="Pairwise rubric judge model (default: the pack's judge.rubric_model)."),
    allow_uncalibrated: bool = typer.Option(
        False, "--allow-uncalibrated",
        help="Judge rubric pairs despite a missing/stale calibration record "
             "(loud warning; verdicts marked untrusted in the artifact)."),
    out_dir: str = typer.Option(
        "runs", "--out-dir", help="Directory the compare artifact is written to."),
    events: bool = typer.Option(False, "--events", help=EVENTS_HELP),
    seed: int = typer.Option(
        None, "--seed", help="Seed for the judge's order-controlled draw-2 orders."),
    debug: bool = typer.Option(
        False, "--debug",
        help="Re-raise errors with full tracebacks instead of clean exit-2 messages."),
):
    """Blind pairwise A/B judging over two gate artifacts (advisory — no
    target HTTP calls, no combined winner; exit 0 or 2 only)."""
    import asyncio
    import json

    from evalyn.engine import compare as cmp_mod
    from evalyn.engine.budget import BudgetExceeded
    from evalyn.engine.run import RunArtifact
    from evalyn.engine.task_builder import _model_family
    from evalyn.engine.validate import validate_pack

    run_id = _run_id_from_env()  # at command entry: a bad value warns here, early

    # Compare never touches the target: no resolve_base_url, no HTTP.
    try:
        pack = load_pack(target)
    except PackError as e:
        if debug:
            raise
        typer.echo(f"compare: setup error: {e}", err=True)
        raise typer.Exit(2)

    report = validate_pack(pack)
    for w in report.warnings:
        typer.echo(f"warning: {w}")
    for err in report.errors:
        typer.echo(f"error: {err}", err=True)
    if not report.ok:
        typer.echo("compare: setup error: pack failed validation "
                   "(see errors above; `evalyn validate-pack` reproduces them)", err=True)
        raise typer.Exit(2)

    # Judge != generator family (spec §2.1): compare never calls build_task,
    # so its self-preference warning is mirrored here for the resolved judge.
    rubric_model = rubric_judge_model or pack.spec.judge.rubric_model
    generator_family = pack.spec.judge.generator_family
    if generator_family and _model_family(rubric_model) == generator_family.lower():
        typer.echo(f"warning: rubric judge model {rubric_model!r} is the same "
                   f"model family as the target's generator "
                   f"({generator_family!r}) — self-preference bias risk; "
                   f"prefer a different judge family", err=True)

    # Fail-closed judge calibration, BEFORE artifacts are even loaded
    # (mirrors gate): pairwise verdicts are refused until `evalyn calibrate`
    # has blessed the current rubrics + judge model.
    has_rubric = any(c.type == "rubric" for p in pack.probes for c in p.checks)
    rubric_untrusted = False
    if has_rubric:
        from evalyn.engine.calibrate import is_stale

        stale, why = is_stale(pack, rubric_model)
        if stale and not allow_uncalibrated:
            typer.echo(f"compare: setup error: rubric checks require calibration ({why}); "
                       f"run `evalyn calibrate --target {target}` or pass "
                       f"--allow-uncalibrated", err=True)
            raise typer.Exit(2)
        if stale:
            typer.echo(f"warning: judging with UNCALIBRATED rubrics ({why}) — "
                       f"pairwise verdicts are untrusted", err=True)
            rubric_untrusted = True

    arts = {}
    for side, path in (("A", a), ("B", b)):
        try:
            arts[side] = RunArtifact.from_dict(json.loads(Path(path).read_text()))
        except (OSError, ValueError) as e:  # missing/corrupt JSON or old schema
            if debug:
                raise
            typer.echo(f"compare: artifact {side} error ({path}): {e}", err=True)
            raise typer.Exit(2)

    try:
        sink, run_id = _open_sink(events, mode="compare", pack_name=pack.spec.name,
                                  out_dir=out_dir, run_id=run_id)
    except Exception as e:
        if debug:
            raise
        typer.echo(f"compare: setup error: --events stream unavailable: {e}", err=True)
        raise typer.Exit(2)

    try:
        art = asyncio.run(cmp_mod.run_compare(
            pack, arts["A"], arts["B"], rubric_model,
            cache_dir=Path(target) / ".cache",
            rubric_scores_untrusted=rubric_untrusted, seed=seed,
            out_dir=out_dir, label_a=label_a, label_b=label_b,
            source_a=a, source_b=b, run_id=run_id, sink=sink))
    # Unlike `gate`, this block cannot take a `finally`: the sink has to stay
    # open through `write_compare_artifact` below, the one place that can
    # honestly emit `artifact.written`. So each failing exit closes it here
    # instead, first thing, before --debug re-raises. `close` is idempotent.
    except BudgetExceeded as e:
        sink.close()
        if debug:
            raise
        typer.echo(f"compare: budget exceeded: {e} — the compare artifact is "
                   f"on disk under {out_dir}/ for inspection", err=True)
        raise typer.Exit(2)
    except ValueError as e:  # locked preconditions (pack hash, transcripts)
        sink.close()
        if debug:
            raise
        typer.echo(f"compare: setup error: {e}", err=True)
        raise typer.Exit(2)
    except Exception as e:  # judge connection / infra
        sink.close()
        if debug:
            raise
        typer.echo(f"compare: run error: {e}", err=True)
        raise typer.Exit(2)

    # Guarded write/render: an OSError here (unwritable/full --out-dir) must
    # stay inside compare's exit-0/2 contract, never escape as exit 1.
    try:
        path = cmp_mod.write_compare_artifact(art, out_dir=out_dir, run_id=run_id,
                                              sink=sink)
        report_md = cmp_mod.render_compare_report(art)
    except Exception as e:
        if debug:
            raise
        typer.echo(f"compare: run error: {e}", err=True)
        raise typer.Exit(2)
    finally:
        # Held open across the write so `artifact.written` — which only the
        # writer can honestly emit — makes it into the stream.
        sink.close()
    typer.echo(report_md)
    typer.echo(f"compare: artifact written to {path}")
    raise typer.Exit(0)


@app.command()
def calibrate(
    target: str = typer.Option(..., "--target", help="Path to a target pack directory."),
    rubric_judge_model: str = typer.Option(
        None, "--rubric-judge-model",
        help="Tier-3 rubric judge model (default: the pack's judge.rubric_model)."),
    debug: bool = typer.Option(
        False, "--debug",
        help="Re-raise errors with full tracebacks instead of clean exit-2 messages."),
):
    """Score anchor transcripts with the rubric judge and record agreement vs
    human labels (committed to <pack>/calibration.json)."""
    import asyncio

    from evalyn.engine import calibrate as cal
    from evalyn.engine.calibrate import per_rubric_agreement

    try:
        pack = load_pack(target)
        anchors = cal.load_anchors(pack)
    except PackError as e:  # unloadable pack OR malformed anchor
        if debug:
            raise
        typer.echo(f"calibrate: setup error: {e}", err=True)
        raise typer.Exit(2)
    if not anchors:
        typer.echo(f"calibrate: setup error: no anchor transcripts found under "
                   f"{target}/anchors/ — add human-labeled anchors first", err=True)
        raise typer.Exit(2)
    model = rubric_judge_model or pack.spec.judge.rubric_model
    try:
        result = asyncio.run(
            cal.run_calibration(pack, model, cache_dir=Path(target) / ".cache"))
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        # missing rubric file; unparseable steps generation (fail-loud,
        # 2026-07-31); or a malformed committed rubrics/<rid>.steps.json
        # (calibrate runs no validate_pack, so the loader's error surfaces here)
        if debug:
            raise
        typer.echo(f"calibrate: setup error: {e}", err=True)
        raise typer.Exit(2)
    for aid in result.skipped:
        typer.echo(f"warning: anchor {aid!r} skipped — missing/invalid human scores "
                   f"(need integer 1-5 per criterion)", err=True)
    for aid in result.unsure:
        typer.echo(f"warning: anchor {aid!r}: judge UNSURE — undecided criteria "
                   f"counted as misses", err=True)
    for aid, crits in result.unmatched.items():
        typer.echo(f"warning: anchor {aid!r}: human label(s) "
                   f"{', '.join(repr(c) for c in crits)} match no rubric criterion — "
                   f"excluded from agreement (check for typos vs the rubric headings)",
                   err=True)
    if result.anchors == 0:
        typer.echo("calibrate: setup error: no anchors with usable human scores", err=True)
        raise typer.Exit(2)
    # Per-anchor diagnosis, always printed (2026-07-30 failure: aggregates
    # alone could not say WHICH anchors disagreed, or distinguish an
    # unparseable judge from genuine +/-1 disagreement).
    if result.per_anchor:
        typer.echo("per-anchor agreement:")
        for aid, info in result.per_anchor.items():
            pairs = ", ".join(
                f"{crit} judge={'-' if d['judge'] is None else d['judge']}"
                + (f" ({d['unsure_reason']})" if d.get("unsure_reason") else "")
                + f" human={d['human']} {'ok' if d['within'] else 'MISS'}"
                for crit, d in info["criteria"].items())
            prefix = (f"UNSURE ({info['unsure_reason']}) — "
                      if info.get("unsure_reason") else "")
            typer.echo(f"  {aid} ({info['rubric']}): {prefix}{pairs}")
    for crit, val in result.per_criterion.items():
        typer.echo(f"  {crit}: {val:.0%}")
    typer.echo(f"overall agreement: {result.overall:.0%} over {result.anchors} anchor(s), "
               f"judge {model} (threshold {cal.AGREEMENT_THRESHOLD:.0%})")
    # Record-written-on-failure is by design (pinned): is_stale rejects any
    # record the verdict below would fail, so the gate can never trust it.
    cal.write_record(pack, result.overall, result.per_criterion, model,
                     per_criterion_counts=result.per_criterion_counts)
    # Verdict mirrors is_stale exactly (PR #4 fix #4 follow-up): overall AND
    # every rubric's own agreement must clear the threshold — calibrate must
    # never print PASS on a record the gate would refuse for a weak rubric.
    # Round-2 N8: pool from raw pair counts when available (exact under
    # divergent counts); mean-of-fractions only as the legacy fallback.
    by_rubric = (cal.pooled_rubric_agreement(result.per_criterion_counts)
                 if result.per_criterion_counts
                 else per_rubric_agreement(result.per_criterion))
    weak = {rid: val for rid, val in by_rubric.items()
            if val < cal.AGREEMENT_THRESHOLD}
    if result.overall >= cal.AGREEMENT_THRESHOLD and not weak:
        typer.echo("calibrate: PASS — rubric judge is calibrated for this pack")
        raise typer.Exit(0)
    if weak:
        typer.echo(f"calibrate: FAIL — per-rubric agreement below "
                   f"{cal.AGREEMENT_THRESHOLD:.0%} for "
                   + ", ".join(f"{rid!r} at {val:.0%}" for rid, val in weak.items())
                   + "; the gate will refuse rubric checks until calibration passes",
                   err=True)
    if result.overall < cal.AGREEMENT_THRESHOLD:
        typer.echo("calibrate: FAIL — agreement below threshold; the gate will refuse "
                   "rubric checks until calibration passes", err=True)
    raise typer.Exit(1)


@app.command()
def discover(
    target: str = typer.Option(..., "--target", help="Path to a target pack directory."),
    objective: list[str] = typer.Option(
        None, "--objective",
        help="Objective id to hunt (repeatable; default: all four)."),
    persona: str = typer.Option(
        None, "--persona", help="Persona id (default: all the pack ships)."),
    playbook: str = typer.Option(
        None, "--playbook", help="Playbook id (default: the pack's, by id)."),
    agent_model: str = typer.Option(
        "openai/gpt-5-mini", "--agent-model", help="The discovery agent model."),
    judge_model: str = typer.Option("mockllm/model", "--judge-model"),
    rubric_judge_model: str = typer.Option(
        None, "--rubric-judge-model",
        help="Tier-3 rubric judge model (required to confirm rubric objectives)."),
    max_steps: int = typer.Option(8, "--max-steps"),
    max_sessions: int = typer.Option(4, "--max-sessions"),
    max_usd: float = typer.Option(
        None, "--max-usd",
        help="Per-run USD ceiling (default/upper-bound = the pack's cap)."),
    allow_uncalibrated: bool = typer.Option(False, "--allow-uncalibrated"),
    allow_family_collision: bool = typer.Option(False, "--allow-family-collision"),
    no_replay: bool = typer.Option(False, "--no-replay"),
    staging_dir: str = typer.Option(
        None, "--staging-dir", help="Where confirmed probes stage (default: <pack>/discoveries/)."),
    out_dir: str = typer.Option("runs", "--out-dir"),
    events: bool = typer.Option(False, "--events", help=EVENTS_HELP),
    seed: int = typer.Option(None, "--seed"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    debug: bool = typer.Option(False, "--debug"),
):
    """Adaptively hunt a target for weaknesses; confirm with the real scorers."""
    import asyncio

    from evalyn.discovery import run as discovery_run
    from evalyn.discovery.config import CliLimits, DiscoveryConfig, resolve_limits
    from evalyn.discovery.objectives import OBJECTIVES
    from evalyn.discovery.personas import load_personas, load_playbooks
    from evalyn.discovery.task_builder import plan_hunts
    from evalyn.engine.validate import validate_pack
    from evalyn.targets.loader import resolve_base_url

    run_id = _run_id_from_env()  # at command entry: a bad value warns here, early
    try:
        pack = load_pack(target)
        base_url = resolve_base_url(pack)  # enforces allowlist
    except (PackError, AllowlistError) as e:
        if debug:
            raise
        typer.echo(f"discover: setup error: {e}", err=True)
        raise typer.Exit(2)

    report = validate_pack(pack)
    for w in report.warnings:
        typer.echo(f"warning: {w}")
    for err in report.errors:
        typer.echo(f"error: {err}", err=True)
    if not report.ok:
        typer.echo("discover: setup error: pack failed validation "
                   "(see errors above; `evalyn validate-pack` reproduces them)", err=True)
        raise typer.Exit(2)

    # R10-4: a CLI `--max-usd 0` resolves to a literal 0 ceiling ("spend
    # nothing"), while a pack's `max_usd_per_run: 0` means "no ceiling" — the
    # same value, opposite meanings. Reject 0 on the flag rather than ship that
    # footgun, and point the operator at the pack field for an uncapped run.
    if max_usd is not None and max_usd == 0:
        typer.echo("discover: setup error: --max-usd 0 would refuse all spend "
                   "and every hunt before it starts. The CLI flag and the pack "
                   "field disagree at 0: to run UNCAPPED, set the pack's "
                   "budget.max_usd_per_run: 0 instead (not this flag).", err=True)
        raise typer.Exit(2)

    try:
        limits = resolve_limits(pack, CliLimits(
            max_steps=max_steps, max_sessions=max_sessions, max_usd=max_usd))
        cfg = DiscoveryConfig(
            limits=limits,
            objectives=tuple(objective) if objective else tuple(OBJECTIVES),
            persona=persona, playbook=playbook, agent_model=agent_model,
            judge_model=judge_model, rubric_judge_model=rubric_judge_model,
            staging_dir=Path(staging_dir) if staging_dir else None,
            out_dir=Path(out_dir), seed=seed, replay=not no_replay)
    except ValueError as e:
        if debug:
            raise
        typer.echo(f"discover: setup error: {e}", err=True)
        raise typer.Exit(2)

    # R10-1: consume Task 9's single family check (never a second one). The
    # discovery<->rubric-judge collision is refuse-class; match REFUSE_PREFIX,
    # never the prose. --allow-family-collision downgrades it to a warning.
    from evalyn.engine.task_builder import REFUSE_PREFIX, family_warnings

    # Match the run: the discovery Confirmer judges ONLY with
    # cfg.rubric_judge_model, so the discovery<->judge family refusal must be
    # measured against THAT model, never the pack's default rubric model (which a
    # discover run never invokes) — else we'd over-refuse against a judge that
    # will not run. `None` -> "" so the rubric-based entries simply don't fire.
    fam = family_warnings(pack, judge_model=cfg.judge_model,
                          rubric_model=cfg.rubric_judge_model or "",
                          discovery_model=cfg.agent_model)
    refusals = [m for m in fam if m.startswith(REFUSE_PREFIX)]
    for m in fam:
        if not m.startswith(REFUSE_PREFIX):
            typer.echo(f"warning: {m}", err=True)
    if refusals and not allow_family_collision:
        for m in refusals:
            typer.echo(f"discover: setup error: {m[len(REFUSE_PREFIX):]} "
                       f"(pass --allow-family-collision to override)", err=True)
        raise typer.Exit(2)
    for m in refusals:
        typer.echo(f"warning: family collision ALLOWED — {m[len(REFUSE_PREFIX):]}",
                   err=True)

    # Shared predicates for R10-2 (rubric objective, no judge) and R10-5 (tier-3
    # staleness). Computed once so the real refusal and the --dry-run "would
    # refuse" note can NEVER drift: R10-2 by the objective's own confirm_checks
    # factory (not declared tier); R10-5 by `is_stale` + `tier >= 3`, mirroring
    # `gate` (which also resolves the rubric model as the override-or-pack-default
    # and skips the check under --dry-run).
    from evalyn.discovery.objectives import get_objective
    from evalyn.discovery.task_builder import _needs_rubric_judge

    blind = ([o for o in cfg.objectives if _needs_rubric_judge(get_objective(o))]
             if cfg.rubric_judge_model is None else [])

    tier3 = [o for o in cfg.objectives if get_objective(o).tier >= 3]
    tier3_stale = False
    stale_why = ""
    if tier3:
        from evalyn.engine.calibrate import is_stale

        stale_rubric_model = cfg.rubric_judge_model or pack.spec.judge.rubric_model
        tier3_stale, stale_why = is_stale(pack, stale_rubric_model)

    if not dry_run:
        # R10-2 — an operator must not start a hunt structurally incapable of
        # confirming anything. No auto-override; fix by judge or deselection.
        if blind:
            typer.echo(f"discover: setup error: no rubric judge configured "
                       f"(--rubric-judge-model), so rubric objective(s) "
                       f"{', '.join(blind)} can never be confirmed — every rubric "
                       f"candidate returns unsure, which is never a finding; set a "
                       f"rubric judge model or deselect those objectives", err=True)
            raise typer.Exit(2)
        # R10-5 — tier-3 calibration-staleness gate.
        if tier3_stale and not allow_uncalibrated:
            typer.echo(f"discover: setup error: tier-3 objective(s) "
                       f"{', '.join(tier3)} require calibration ({stale_why}); run "
                       f"`evalyn calibrate --target {target}` or pass "
                       f"--allow-uncalibrated", err=True)
            raise typer.Exit(2)
        if tier3_stale:
            typer.echo(f"warning: running UNCALIBRATED tier-3 hunt(s) ({stale_why}) "
                       f"— rubric confirmations are untrusted", err=True)

    # Resolve persona/playbook axes (validates the ids) and plan the hunts.
    try:
        personas = load_personas(pack)
        playbooks = load_playbooks(pack)
    except OSError as e:
        if debug:
            raise
        typer.echo(f"discover: setup error: {e}", err=True)
        raise typer.Exit(2)
    # Validate the requested persona/playbook ids up front (a typo would
    # otherwise surface as an opaque error inside the run build).
    if cfg.persona is not None and cfg.persona not in personas:
        typer.echo(f"discover: setup error: unknown persona {cfg.persona!r} — "
                   f"this pack offers: {', '.join(sorted(personas))}", err=True)
        raise typer.Exit(2)
    if cfg.playbook is not None and cfg.playbook not in playbooks:
        typer.echo(f"discover: setup error: unknown playbook {cfg.playbook!r} — "
                   f"this pack offers: {', '.join(sorted(playbooks))}", err=True)
        raise typer.Exit(2)
    persona_ids = sorted(personas) if cfg.persona is None else [cfg.persona]
    pairs = plan_hunts(list(cfg.objectives), persona_ids, cfg.limits.max_sessions)

    # R10-3: the session cap drops whole objectives SILENTLY (round-robin keeps
    # the distribution fair but says nothing). Name the dropped ones so a capped
    # run never reads as "found nothing" when it never looked.
    scheduled = {o for o, _ in pairs}
    dropped = [o for o in cfg.objectives if o not in scheduled]
    if dropped:
        typer.echo(f"warning: session cap {cfg.limits.max_sessions} dropped "
                   f"objective(s): {', '.join(dropped)} — not hunted this run "
                   f"(raise --max-sessions or narrow --objective)", err=True)

    if dry_run:
        # Surface the refusals --dry-run itself suppresses (R10-2/R10-5): the
        # preview must never green-light a config the real run refuses. These use
        # the SAME predicates as the refusals above, gated on the SAME override
        # flags, so a note appears iff a real run would actually exit 2.
        if blind:
            typer.echo(f"NOTE: a real run would REFUSE (exit 2): objective(s) "
                       f"{', '.join(blind)} need a rubric judge but none is "
                       f"configured — set --rubric-judge-model or deselect them.",
                       err=True)
        if tier3_stale and not allow_uncalibrated:
            typer.echo(f"NOTE: a real run would REFUSE (exit 2): tier-3 "
                       f"calibration is stale/absent ({stale_why}) — pass "
                       f"--allow-uncalibrated to proceed, or run `evalyn calibrate "
                       f"--target {target}`.", err=True)
        staging = cfg.staging_dir or (pack.root / "discoveries")
        typer.echo(
            f"discover (dry-run): pack '{pack.spec.name}', target {base_url}\n"
            f"  objectives: {', '.join(cfg.objectives)}\n"
            f"  personas: {', '.join(persona_ids)}\n"
            f"  hunts: {', '.join(f'{o}::{p}' for o, p in pairs)}\n"
            f"  caps: steps {cfg.limits.max_steps}, sessions {cfg.limits.max_sessions}, "
            f"turns {cfg.limits.max_turns}, max_usd ${cfg.limits.max_usd:.2f}\n"
            f"  staging dir: {staging}\n"
            f"  No calls made.")
        raise typer.Exit(0)

    try:
        sink, run_id = _open_sink(events, mode="discover", pack_name=pack.spec.name,
                                  out_dir=str(cfg.out_dir), run_id=run_id)
    except Exception as e:
        if debug:
            raise
        # Exit 2, not 3: this is preflight — nothing has been billed yet.
        typer.echo(f"discover: setup error: --events stream unavailable: {e}",
                   err=True)
        raise typer.Exit(2)

    try:
        art = asyncio.run(discovery_run.run_discovery(pack, cfg, run_id=run_id,
                                                      sink=sink))
    except Exception as e:
        if debug:
            raise
        # Exit 3, not 2. Everything above this point is preflight and exits 2
        # ("setup refusal — nothing was billed"); by HERE the eval has run and
        # the money is spent, and R8-5 has already written a partial artifact.
        # Reporting that as a setup refusal tells a CI consumer to fix its
        # config and retry, when the truth is the opposite: the run is invalid
        # and it was charged for. Name the record so the operator can find what
        # their spend bought.
        typer.echo(f"discover: run error: {e}\n"
                   f"  the run is INVALID (exit 3) — it may have SPENT before "
                   f"failing. A partial run record (spend + any findings made "
                   f"before the failure) was written under {cfg.out_dir}/ as "
                   f"the newest `*-discover.json`.", err=True)
        raise typer.Exit(3)
    finally:
        # `run_discovery` owns every discover event, including the ones on its
        # partial-write path; what follows is rendering and exit-code policy.
        sink.close()

    typer.echo(discovery_run.render_discovery_report(art))
    # Run-invalid (3), in the two shapes it takes. The eval-status case is the
    # sneakier one: a failed/cancelled eval yields NO samples, so `sessions_total`
    # and `error_count` are both 0 and the all-errored guard below is false —
    # the run would otherwise report `0 finding(s) from 0 hunt(s)` and exit 0.
    if not art.eval_ok:
        raise typer.Exit(3)
    if art.sessions_total > 0 and art.error_count >= art.sessions_total:
        raise typer.Exit(3)
    raise typer.Exit(0)


@app.command()
def ui(
    port: int = typer.Option(8765, "--port", help="Loopback port to serve on."),
    runs_dir: str = typer.Option("runs", "--runs-dir",
                                 help="Directory of run artifacts to serve."),
    target: list[str] = typer.Option(
        None, "--target",
        help="Pack the cockpit may launch runs against. Repeatable."),
    allow_discover: bool = typer.Option(
        False, "--allow-discover",
        help="Permit `discover` launches, which spend real money."),
    no_open: bool = typer.Option(False, "--no-open",
                                 help="Do not open a browser on start."),
):
    """Serve the local cockpit over `runs/` on 127.0.0.1.

    The import is inside the body on purpose. `evalyn.ui.server` is the only
    module that touches FastAPI, and keeping it out of this file's import graph
    is what lets `evalyn gate` run on a machine that never installed the `[ui]`
    extra — and what makes the missing-extra case a sentence a human reads
    rather than an `ImportError` raised three modules away at start-up.
    """
    try:
        from evalyn.ui.server import serve
    except ImportError:
        typer.echo("evalyn ui: setup error: the UI extra is not installed. "
                   "Install it with: pip install 'evalyn[ui]'", err=True)
        raise typer.Exit(2)

    try:
        serve(runs_dir=Path(runs_dir), packs=[Path(t) for t in target or []],
              port=port, allow_discover=allow_discover, open_browser=not no_open)
    except (PackError, AllowlistError) as e:
        # Fail closed: a pack that does not load is a pack whose `not_contains`
        # secrets never reached the redactor. Refusing to start beats serving
        # with a hole in the one control that is supposed to be structural.
        typer.echo(f"evalyn ui: setup error: {e}", err=True)
        raise typer.Exit(2)


@app.command("validate-pack")
def validate_pack_cmd(pack: str = typer.Argument(..., help="Path to a target pack directory.")):
    """Task-health check: schema, solvability, category balance."""
    from evalyn.engine.validate import validate_pack

    try:
        loaded = load_pack(pack)
    except PackError as e:
        typer.echo(f"validate-pack: {e}", err=True)
        raise typer.Exit(1)

    report = validate_pack(loaded)
    for w in report.warnings:
        typer.echo(f"warning: {w}")
    for e in report.errors:
        typer.echo(f"error: {e}", err=True)
    if report.ok:
        typer.echo(f"validate-pack: OK ({len(loaded.probes)} probes passed)")
        raise typer.Exit(0)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
