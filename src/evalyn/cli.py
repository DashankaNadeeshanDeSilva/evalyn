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
    dry_run: bool = typer.Option(False, "--dry-run"),
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
                               rubric_scores_untrusted=rubric_untrusted)
    except BudgetExceeded as e:
        typer.echo(f"gate: budget exceeded: {e} — partial run artifact is on "
                   f"disk under runs/ for inspection", err=True)
        raise typer.Exit(2)
    except Exception as e:  # connection / infra
        typer.echo(f"gate: run error: {e}", err=True)
        raise typer.Exit(2)

    if update_baseline:
        save_baseline(art, baseline)
        typer.echo(f"gate: baseline updated at {baseline}")
        raise typer.Exit(0)

    baseline_art = load_baseline(baseline)
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
def calibrate(
    target: str = typer.Option(..., "--target", help="Path to a target pack directory."),
    rubric_judge_model: str = typer.Option(
        None, "--rubric-judge-model",
        help="Tier-3 rubric judge model (default: the pack's judge.rubric_model)."),
):
    """Score anchor transcripts with the rubric judge and record agreement vs
    human labels (committed to <pack>/calibration.json)."""
    import asyncio

    from evalyn.engine import calibrate as cal

    try:
        pack = load_pack(target)
    except PackError as e:
        typer.echo(f"calibrate: setup error: {e}", err=True)
        raise typer.Exit(2)
    if not cal.load_anchors(pack):
        typer.echo(f"calibrate: setup error: no anchor transcripts found under "
                   f"{target}/anchors/ — add human-labeled anchors first", err=True)
        raise typer.Exit(2)
    model = rubric_judge_model or pack.spec.judge.rubric_model
    result = asyncio.run(cal.run_calibration(pack, model, cache_dir=Path(target) / ".cache"))
    for aid in result.skipped:
        typer.echo(f"warning: anchor {aid!r} skipped — missing/invalid human scores "
                   f"(need integer 1-5 per criterion)", err=True)
    for aid in result.unsure:
        typer.echo(f"warning: anchor {aid!r}: judge UNSURE — counted as disagreement",
                   err=True)
    for aid, crits in result.unmatched.items():
        typer.echo(f"warning: anchor {aid!r}: human label(s) "
                   f"{', '.join(repr(c) for c in crits)} match no rubric criterion — "
                   f"excluded from agreement (check for typos vs the rubric headings)",
                   err=True)
    if result.anchors == 0:
        typer.echo("calibrate: setup error: no anchors with usable human scores", err=True)
        raise typer.Exit(2)
    for crit, val in result.per_criterion.items():
        typer.echo(f"  {crit}: {val:.0%}")
    typer.echo(f"overall agreement: {result.overall:.0%} over {result.anchors} anchor(s), "
               f"judge {model} (threshold {cal.AGREEMENT_THRESHOLD:.0%})")
    cal.write_record(pack, result.overall, result.per_criterion, model)
    if result.overall >= cal.AGREEMENT_THRESHOLD:
        typer.echo("calibrate: PASS — rubric judge is calibrated for this pack")
        raise typer.Exit(0)
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
