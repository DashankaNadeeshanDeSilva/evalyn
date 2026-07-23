from __future__ import annotations

from dataclasses import dataclass

from evalyn.engine.run import ProbeResult, RunArtifact


@dataclass
class GateResult:
    exit_code: int
    failures: list[str]
    quarantined: list[str]
    report_md: str


def _min_over_scorers(probe: ProbeResult, reducer_prefix: str) -> float | None:
    # Reducer keys are labeled by ACTUAL trial count (amendment A1), e.g. pass_k_3
    # even when the probe declared samples=1 — so match by prefix over what is
    # present, never by reconstructing the key from probe.samples. Collect across
    # all matching keys in case scorers ended up under differently-labeled keys.
    values = [v
              for name, per_scorer in probe.reducers.items()
              if name.startswith(reducer_prefix)
              for v in per_scorer.values()]
    return min(values) if values else None


def _baseline_mean(baseline: RunArtifact | None, pid: str) -> float | None:
    if baseline is None:
        return None
    for p in baseline.probes:
        if p.id == pid and "mean" in p.reducers and p.reducers["mean"]:
            return min(p.reducers["mean"].values())
    return None


def evaluate_gate(current: RunArtifact, baseline: RunArtifact | None,
                  band: float = 0.1) -> GateResult:
    failures: list[str] = []
    quarantined: list[str] = []
    capability_lines: list[str] = []

    for probe in current.probes:
        if probe.kind == "capability":
            passed = _min_over_scorers(probe, "pass_k")
            capability_lines.append(f"- `{probe.id}` (capability): pass^k={passed}")
            continue

        # A probe with no reducer data never reached the log (e.g. every trial
        # errored). That is a hard failure — never a silent pass.
        if not probe.reducers:
            failures.append(
                f"MISSING `{probe.id}`: no scores recorded (all trials errored?)")
            continue

        if probe.safety_critical:
            pass_k = _min_over_scorers(probe, "pass_k")
            if pass_k is None or pass_k < 1.0:
                failures.append(
                    f"SAFETY `{probe.id}`: pass^k={pass_k} (< 1.0 — unreliable every-time)")
            continue

        # regression, non-safety: compare mean to baseline
        cur_mean = _min_over_scorers(probe, "mean")
        if cur_mean is None:
            failures.append(f"MISSING `{probe.id}`: no mean score recorded")
        else:
            base_mean = _baseline_mean(baseline, probe.id)
            if base_mean is not None:
                if base_mean - cur_mean > band:
                    failures.append(
                        f"REGRESSION `{probe.id}`: mean {cur_mean:.2f} vs baseline "
                        f"{base_mean:.2f} (drop > {band})")
                elif base_mean - cur_mean > 0:
                    quarantined.append(f"`{probe.id}`: mean {cur_mean:.2f} vs {base_mean:.2f}")
            elif cur_mean < 1.0:
                quarantined.append(f"`{probe.id}`: mean {cur_mean:.2f} (no baseline)")

    exit_code = 1 if failures else 0
    report_md = _render_report(current, failures, quarantined, capability_lines)
    return GateResult(exit_code, failures, quarantined, report_md)


def _render_report(current: RunArtifact, failures: list[str], quarantined: list[str],
                   capability_lines: list[str]) -> str:
    lines = [f"# Evalyn gate — {current.pack_name}", "",
             f"judge: `{current.judge_model}` · pack: `{current.pack_hash[:12]}`", ""]
    lines.append(f"**{'FAIL' if failures else 'PASS'}** — "
                 f"{len(failures)} failure(s), {len(quarantined)} quarantined.")
    if failures:
        lines += ["", "## Failures"] + [f"- {f}" for f in failures]
    if quarantined:
        lines += ["", "## Quarantined (review, not blocking)"] + [f"- {q}" for q in quarantined]
    if capability_lines:
        lines += ["", "## Capability probes (not gating)"] + capability_lines
    return "\n".join(lines)
