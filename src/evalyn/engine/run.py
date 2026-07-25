from __future__ import annotations

import hashlib
import json
import os
import tempfile
import warnings
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from evalyn.engine.budget import BudgetExceeded, estimate_cost
from evalyn.engine.task_builder import build_task
from evalyn.scoring.checks import aggregate_trial
from evalyn.targets.loader import Pack


@dataclass
class ProbeResult:
    id: str
    category: str
    kind: str
    safety_critical: bool
    samples: int              # declared in the pack (actual trials may differ — A1)
    trials: int = 0           # trials actually collected (epochs with checks)
    pass_at_k: float = 0.0    # any trial's required checks all passed
    pass_k: float = 0.0       # EVERY trial's required checks passed (safety gate)
    mean_score: float = 0.0   # mean weighted trial_score over trials
    unsure_trials: int = 0    # NOANSWER accounting: required-unsure, not failed
    checks: list[dict] = field(default_factory=list)  # representative CheckResults


@dataclass
class RunArtifact:
    pack_name: str
    pack_hash: str
    judge_model: str
    created_at: str
    probes: list[ProbeResult]
    log_path: str
    # True when the run was allowed past a missing/stale judge calibration via
    # --allow-uncalibrated: rubric-check scores in this artifact are untrusted.
    rubric_scores_untrusted: bool = False
    # Estimated USD spent on Evalyn's OWN judge models (Tier-2/3 LLM calls;
    # target-side HTTP spend is never counted). Metered POST-HOC after the eval
    # returns — a run can overshoot `budget.max_usd_per_run`; the cap bounds
    # what a run may have spent before its results are trusted, and a breach
    # raises BudgetExceeded AFTER this artifact is written.
    judge_usd: float = 0.0
    # NOANSWER accounting: total trials (across all probes) whose required
    # checks came back unsure — judge-infra failures, distinct from product
    # failures. Sum of per-probe `unsure_trials`.
    total_unsure_trials: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunArtifact":
        try:
            probes = [ProbeResult(**p) for p in d["probes"]]
        except TypeError as e:
            raise ValueError(
                "artifact probe entries do not match the Plan #2a ProbeResult "
                f"schema ({e}); this artifact predates the current schema") from e
        return cls(**{**d, "probes": probes})


def pack_fingerprint(pack: Pack) -> str:
    """SHA-256 over the RAW pack file bytes (target.yaml + probes + rubrics).

    Hashing raw bytes — not a re-serialization of the resolved spec — keeps the
    fingerprint independent of ${ENV} resolution (e.g. base_url localhost vs
    127.0.0.1), so the same pack files always fingerprint identically.
    """
    h = hashlib.sha256()
    for name in sorted(getattr(pack, "raw_files", {})):
        h.update(name.encode())
        h.update(b"\0")
        h.update(pack.raw_files[name])
    return h.hexdigest()


def _reduce_log_to_probes(log, pack: Pack) -> list[ProbeResult]:
    by_id = {p.id: p for p in pack.probes}
    # Group CheckResults per (probe_id, epoch) across ALL scorers present in the
    # log (tier3 lands later — never hardcode a scorer list). The authority is
    # each Score's metadata["checks"], never Score.value. An epoch that produced
    # no checks in ANY scorer (errored trial) is NOT counted as a trial, so a
    # fully-errored probe keeps trials == 0 and the gate hard-fails it as
    # MISSING — never a silent pass (fail-closed, Plan #1 rule).
    trials: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for sample in log.samples or []:
        pid = sample.metadata["id"] if sample.metadata else sample.id
        for sc in (sample.scores or {}).values():
            checks = (sc.metadata or {}).get("checks") or []
            if checks:
                trials[pid][sample.epoch].extend(checks)

    results: list[ProbeResult] = []
    for pid, probe in by_id.items():
        # Amendment A1: stats reflect the ACTUAL number of trials collected (the
        # task runs every probe at the pack-wide max), not declared `samples`.
        per_epoch = trials.get(pid, {})
        n = len(per_epoch)
        req_passes: list[bool] = []
        unsure_ct = 0
        scores: list[float] = []
        for _epoch, crs in per_epoch.items():
            req_pass, trial_unsure, trial_score = aggregate_trial(crs)
            req_passes.append(req_pass)
            unsure_ct += 1 if trial_unsure else 0
            scores.append(trial_score)
        pass_at_k = 1.0 if any(req_passes) else 0.0
        pass_k = 1.0 if (n > 0 and all(req_passes)) else 0.0
        mean_score = sum(scores) / n if n else 0.0
        # carry one epoch's checks as representative evidence for the report
        rep_checks = next(iter(per_epoch.values())) if per_epoch else []
        results.append(ProbeResult(
            id=pid, category=probe.category, kind=probe.kind,
            safety_critical=probe.safety_critical, samples=probe.samples,
            trials=n, pass_at_k=pass_at_k, pass_k=pass_k, mean_score=mean_score,
            unsure_trials=unsure_ct, checks=rep_checks))
    return results


def _judge_usd() -> float:
    """Aggregate judge spend for the just-finished eval (post-hoc metering)."""
    try:
        from inspect_ai.model._model import model_usage
        return estimate_cost(model_usage())
    except Exception as e:
        # Fail-open by design (brief): metering failure must not kill the run.
        # But be LOUD about it — a silent 0.0 would quietly disable the cap.
        warnings.warn(
            f"judge-spend metering unavailable — budget cap not enforced "
            f"this run ({type(e).__name__}: {e})", RuntimeWarning, stacklevel=2)
        return 0.0


def run_gate(pack: Pack, judge_model: str = "mockllm/model",
             log_dir: str = "runs/logs", rubric_judge_model: str | None = None,
             rubric_scores_untrusted: bool = False,
             out_dir: str = "runs") -> RunArtifact:
    task = build_task(pack, judge_model=judge_model,
                      rubric_judge_model=rubric_judge_model)
    logs = inspect_eval(task, model="mockllm/model", log_dir=log_dir, display="none")
    log = logs[0]
    if log.status != "success":
        raise RuntimeError(f"inspect eval did not succeed: status {log.status!r}")
    if log.samples is None and log.location:
        log = read_eval_log(log.location)
    probes = _reduce_log_to_probes(log, pack)
    art = RunArtifact(
        pack_name=pack.spec.name,
        pack_hash=pack_fingerprint(pack),
        judge_model=judge_model,
        created_at=datetime.now(timezone.utc).isoformat(),
        probes=probes,
        log_path=str(log.location) if log.location else log_dir,
        rubric_scores_untrusted=rubric_scores_untrusted,
        total_unsure_trials=sum(p.unsure_trials for p in probes),
    )
    art.judge_usd = _judge_usd()
    # Write the artifact BEFORE any budget check so a partial/complete artifact
    # survives a budget breach for inspection. Atomic temp-then-rename so a
    # crash mid-write never leaves a torn artifact behind.
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    fd, tmp = tempfile.mkstemp(dir=out_path, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(art.to_dict(), indent=2, default=str))
    os.replace(tmp, out_path / f"{stamp}-{pack.spec.name}.json")
    # Post-hoc budget gate: there is no mid-run stop, so the run may already
    # have overshot the cap — the breach is raised after metering.
    cap = pack.spec.budget.max_usd_per_run
    if cap and art.judge_usd > cap:
        raise BudgetExceeded(
            f"judge spend ${art.judge_usd:.4f} exceeded max_usd_per_run ${cap:.2f} "
            f"(partial artifact written)")
    return art
