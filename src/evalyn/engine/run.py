from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.scorer import CORRECT

from evalyn.engine.task_builder import build_task
from evalyn.targets.loader import Pack


@dataclass
class ProbeResult:
    id: str
    category: str
    kind: str
    safety_critical: bool
    samples: int
    reducers: dict[str, dict[str, float]] = field(default_factory=dict)


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
        probes = [ProbeResult(**p) for p in d["probes"]]
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
    # per-probe reducer accuracies: the log's results.scores carry reducer name + metrics,
    # but reducers are task-level, so recompute per-probe from per-sample scores.
    # Each sample.metadata["id"] identifies the probe; sample.scores[scorer].value is per-epoch.
    # gather per-probe, per-scorer list of per-epoch pass(1)/fail(0)
    raw: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for sample in log.samples or []:
        pid = sample.metadata["id"]
        for scorer_name, sc in (sample.scores or {}).items():
            raw[pid][scorer_name].append(1.0 if sc.value == CORRECT else 0.0)

    results: list[ProbeResult] = []
    for pid, probe in by_id.items():
        reducers: dict[str, dict[str, float]] = {}
        for scorer_name, vals in raw.get(pid, {}).items():
            # Amendment A1: label reducers by the ACTUAL number of trials collected
            # (the task runs every probe at the pack-wide max), not the probe's
            # declared `samples`. pass_at_3 must mean "3 actual trials".
            n = len(vals)
            correct = sum(vals)
            pass_at = 1.0 if correct >= 1 else 0.0                     # pass@k
            pass_k = 1.0 if correct == n and n > 0 else 0.0            # pass^k (all pass)
            mean = correct / n if n else 0.0
            reducers.setdefault(f"pass_at_{n}", {})[scorer_name] = pass_at
            reducers.setdefault(f"pass_k_{n}", {})[scorer_name] = pass_k
            reducers.setdefault("mean", {})[scorer_name] = mean
        results.append(ProbeResult(
            id=pid, category=probe.category, kind=probe.kind,
            safety_critical=probe.safety_critical, samples=probe.samples,
            reducers=reducers))
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
