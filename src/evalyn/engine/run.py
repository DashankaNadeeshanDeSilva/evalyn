from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

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
    payload = {
        "spec": pack.spec.model_dump(),
        "probes": sorted((p.model_dump() for p in pack.probes), key=lambda x: x["id"]),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


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


def run_gate(pack: Pack, judge_model: str = "mockllm/model",
             log_dir: str = "runs/logs") -> RunArtifact:
    task = build_task(pack, judge_model=judge_model)
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
    )
    out_dir = Path("runs")
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (out_dir / f"{stamp}-{pack.spec.name}.json").write_text(
        json.dumps(art.to_dict(), indent=2, default=str))
    return art
