from __future__ import annotations

from pathlib import Path

import typer

from evalyn.targets.loader import AllowlistError, PackError, load_pack

app = typer.Typer(help="Evalyn — evaluation agent for LLM-powered products.", no_args_is_help=True)


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
        art = run_mod.run_gate(pack, judge_model=judge_model,
                               rubric_judge_model=rubric_judge_model,
                               rubric_scores_untrusted=rubric_untrusted,
                               out_dir=out_dir)
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
        art = asyncio.run(cmp_mod.run_compare(
            pack, arts["A"], arts["B"], rubric_model,
            cache_dir=Path(target) / ".cache",
            rubric_scores_untrusted=rubric_untrusted, seed=seed,
            out_dir=out_dir, label_a=label_a, label_b=label_b,
            source_a=a, source_b=b))
    except BudgetExceeded as e:
        if debug:
            raise
        typer.echo(f"compare: budget exceeded: {e} — the compare artifact is "
                   f"on disk under {out_dir}/ for inspection", err=True)
        raise typer.Exit(2)
    except ValueError as e:  # locked preconditions (pack hash, transcripts)
        if debug:
            raise
        typer.echo(f"compare: setup error: {e}", err=True)
        raise typer.Exit(2)
    except Exception as e:  # judge connection / infra
        if debug:
            raise
        typer.echo(f"compare: run error: {e}", err=True)
        raise typer.Exit(2)

    # Guarded write/render: an OSError here (unwritable/full --out-dir) must
    # stay inside compare's exit-0/2 contract, never escape as exit 1.
    try:
        path = cmp_mod.write_compare_artifact(art, out_dir=out_dir)
        report_md = cmp_mod.render_compare_report(art)
    except Exception as e:
        if debug:
            raise
        typer.echo(f"compare: run error: {e}", err=True)
        raise typer.Exit(2)
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
