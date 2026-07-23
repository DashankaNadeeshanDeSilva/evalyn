from __future__ import annotations

from inspect_ai import Epochs, Task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import pass_at, pass_k

from evalyn.engine.solver import session_solver
from evalyn.scoring.tier1 import tier1_scorer
from evalyn.scoring.tier2 import tier2_scorer
from evalyn.targets.loader import Pack


def _probe_metadata(probe) -> dict:
    return {
        "id": probe.id,
        "category": probe.category,
        "kind": probe.kind,
        "safety_critical": probe.safety_critical,
        "turns": probe.turns,
        "samples": probe.samples,
        "checks": [c.model_dump() for c in probe.checks],
    }


def build_task(pack: Pack, judge_model: str = "mockllm/model",
               max_samples: int | None = None) -> Task:
    probes = pack.probes if max_samples is None else pack.probes[:max_samples]
    samples = [Sample(input=p.id, target=p.category, metadata=_probe_metadata(p)) for p in probes]
    k = max((p.samples for p in probes), default=1)
    return Task(
        dataset=MemoryDataset(samples),
        solver=session_solver(pack),
        scorer=[tier1_scorer(pack), tier2_scorer(judge_model)],
        epochs=Epochs(k, [pass_at(k), pass_k(k), "mean"]),
    )
