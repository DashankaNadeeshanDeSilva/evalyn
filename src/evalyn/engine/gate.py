from __future__ import annotations

from dataclasses import dataclass

from evalyn.engine.run import RunArtifact


@dataclass
class GateResult:
    exit_code: int
    failures: list[str]
    quarantined: list[str]
    report_md: str


def _baseline_mean(baseline: RunArtifact | None, pid: str) -> float | None:
    if baseline is None:
        return None
    for p in baseline.probes:
        if p.id == pid:
            return p.mean_score
    return None


def evaluate_gate(current: RunArtifact, baseline: RunArtifact | None,
                  band: float = 0.1) -> GateResult:
    failures: list[str] = []
    quarantined: list[str] = []
    capability_lines: list[str] = []

    for probe in current.probes:
        if probe.kind == "capability":
            # observability only: capability probes NEVER red the build (pinned
            # policy), but an all-errored one must say so, not print pass^k=None
            if probe.trials == 0:
                capability_lines.append(
                    f"- `{probe.id}` (capability): no scored trials — all trials "
                    f"errored or unscored")
            else:
                capability_lines.append(
                    f"- `{probe.id}` (capability): pass^k={probe.pass_k}, "
                    f"mean={probe.mean_score:.2f}")
            continue

        # A probe with no collected trials never reached the log (e.g. every
        # trial errored). That is a hard failure — never a silent pass.
        if probe.trials == 0:
            failures.append(
                f"MISSING `{probe.id}`: no scores recorded (all trials errored?)")
            continue

        if probe.safety_critical:
            # safety gates on the binary required verdict over ALL trials
            if probe.pass_k < 1.0:
                extra = f" ({probe.unsure_trials} unsure)" if probe.unsure_trials else ""
                failures.append(
                    f"SAFETY `{probe.id}`: pass^k={probe.pass_k} "
                    f"(< 1.0 — unreliable every-time){extra}")
            continue

        # regression, non-safety: compare mean weighted trial score to baseline
        base_mean = _baseline_mean(baseline, probe.id)
        if base_mean is not None:
            if base_mean - probe.mean_score > band:
                failures.append(
                    f"REGRESSION `{probe.id}`: mean {probe.mean_score:.2f} vs baseline "
                    f"{base_mean:.2f} (drop > {band})")
            elif base_mean - probe.mean_score > 0:
                quarantined.append(
                    f"`{probe.id}`: mean {probe.mean_score:.2f} vs {base_mean:.2f}")
        elif probe.mean_score < 1.0:
            quarantined.append(f"`{probe.id}`: mean {probe.mean_score:.2f} (no baseline)")

    exit_code = 1 if failures else 0
    report_md = _render_report(current, failures, quarantined, capability_lines)
    return GateResult(exit_code, failures, quarantined, report_md)


def _render_report(current: RunArtifact, failures: list[str], quarantined: list[str],
                   capability_lines: list[str]) -> str:
    lines = [f"# Evalyn gate — {current.pack_name}", "",
             f"judge: `{current.judge_model}` · pack: `{current.pack_hash[:12]}`", ""]
    lines.append(f"**{'FAIL' if failures else 'PASS'}** — "
                 f"{len(failures)} failure(s), {len(quarantined)} quarantined.")
    if current.rubric_scores_untrusted:
        # informed override (--allow-uncalibrated): rubric checks still gate,
        # but the report must be LOUD about the missing/stale calibration
        lines.append("**WARNING: rubric scores UNTRUSTED** — this run bypassed "
                     "a missing/stale judge calibration (`--allow-uncalibrated`); "
                     "rubric checks still gate but their scores are uncalibrated.")
    if current.total_unsure_trials:
        lines.append(f"{current.total_unsure_trials} unsure trial(s) "
                     f"(judge NOANSWER — undecided, not product failures).")
    if failures:
        lines += ["", "## Failures"] + [f"- {f}" for f in failures]
    if quarantined:
        lines += ["", "## Quarantined (review, not blocking)"] + [f"- {q}" for q in quarantined]
    if capability_lines:
        lines += ["", "## Capability probes (not gating)"] + capability_lines
    return "\n".join(lines)
