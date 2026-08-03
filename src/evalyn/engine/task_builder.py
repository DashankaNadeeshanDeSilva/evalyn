from __future__ import annotations

import warnings
from pathlib import Path

from inspect_ai import Epochs, Task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import pass_at, pass_k

from evalyn.engine.solver import session_solver
from evalyn.scoring.tier1 import tier1_scorer
from evalyn.scoring.tier2 import tier2_scorer
from evalyn.scoring.tier3 import tier3_scorer
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


def _model_family(model: str) -> str:
    return model.split("/", 1)[0].lower()


def build_task(pack: Pack, judge_model: str = "mockllm/model",
               rubric_judge_model: str | None = None,
               max_samples: int | None = None,
               cache_dir: Path | None = None) -> Task:
    probes = pack.probes if max_samples is None else pack.probes[:max_samples]
    samples = [Sample(input=p.id, target=p.category, metadata=_probe_metadata(p)) for p in probes]
    k = max((p.samples for p in probes), default=1)
    rubric_model = rubric_judge_model or pack.spec.judge.rubric_model
    generator_family = pack.spec.judge.generator_family
    if generator_family and _model_family(rubric_model) == generator_family.lower():
        # Global Constraint: judge != generator family by default — a match is
        # a self-preference-bias WARNING, never an error.
        warnings.warn(
            f"rubric judge model {rubric_model!r} is the same model family as "
            f"the target's generator ({generator_family!r}) — self-preference "
            f"bias risk; prefer a different judge family",
            UserWarning, stacklevel=2)
    if (generator_family and not judge_model.startswith("mockllm")
            and _model_family(judge_model) == generator_family.lower()):
        # Same rule for the TIER-2 classifier judge (gate parity, #2b Task 10).
        # Only this guard needs the mockllm skip: judge_model DEFAULTS to
        # "mockllm/model" (offline tests), while rubric_model always resolves
        # to a real model from the pack spec or an explicit override.
        warnings.warn(
            f"tier-2 classifier judge model {judge_model!r} is the same model "
            f"family as the target's generator ({generator_family!r}) — "
            f"self-preference bias risk; prefer a different judge family",
            UserWarning, stacklevel=2)
    return Task(
        dataset=MemoryDataset(samples),
        solver=session_solver(pack),
        scorer=[tier1_scorer(pack), tier2_scorer(judge_model),
                tier3_scorer(pack, rubric_model, cache_dir=cache_dir)],
        epochs=Epochs(k, [pass_at(k), pass_k(k), "mean"]),
        # A sample error (target hiccup on ONE probe) must not abort the whole
        # eval: with fail_on_error=False the errored sample lands in the log
        # with no checks, its probe keeps trials == 0, and the gate hard-fails
        # it as MISSING (fail-closed, PR #4 fix #2). Real infra failure still
        # raises via run_gate's log.status check.
        fail_on_error=False,
    )
