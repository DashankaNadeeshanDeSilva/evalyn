from __future__ import annotations

import warnings
from pathlib import Path

from inspect_ai import Epochs, Task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import pass_at, pass_k

from evalyn.engine.control import RunController, early_stopping_supported
from evalyn.engine.events import NULL_SINK, EventSink
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


# Stable, machine-detectable sentinel: a `family_warnings` entry that begins with
# REFUSE_PREFIX is a DISQUALIFYING (refuse-class) collision; every other entry is
# a warn-class soft caution. Task 10's CLI turns any refuse-class entry into exit
# code 2 by matching this prefix alone — it must never sniff the prose. Keep the
# literal stable; import the constant rather than hard-coding the string.
REFUSE_PREFIX = "REFUSE: "


def family_warnings(pack: Pack, *, judge_model: str, rubric_model: str,
                    discovery_model: str | None = None) -> list[str]:
    """Family-parity checks across the judge / generator / discovery-agent triad.

    Returns human-readable messages. An entry beginning with ``REFUSE_PREFIX`` is
    refuse-class (disqualifying); any other entry is warn-class (soft caution).
    With ``discovery_model=None`` (the default) the output is exactly the two
    pre-existing judge<->generator warnings, so callers that pass no discovery
    model see zero behaviour change (R9-2).
    """
    generator_family = pack.spec.judge.generator_family
    gen_fam = generator_family.lower() if generator_family else None
    msgs: list[str] = []

    # --- pre-existing warn-class entries (verbatim — do not alter) ---
    if gen_fam and _model_family(rubric_model) == gen_fam:
        # Global Constraint: judge != generator family by default — a match is
        # a self-preference-bias WARNING, never an error.
        msgs.append(
            f"rubric judge model {rubric_model!r} is the same model family as "
            f"the target's generator ({generator_family!r}) — self-preference "
            f"bias risk; prefer a different judge family")
    if (gen_fam and not judge_model.startswith("mockllm")
            and _model_family(judge_model) == gen_fam):
        # Same rule for the TIER-2 classifier judge (gate parity, #2b Task 10).
        # Only this guard needs the mockllm skip: judge_model DEFAULTS to
        # "mockllm/model" (offline tests), while rubric_model always resolves
        # to a real model from the pack spec or an explicit override.
        msgs.append(
            f"tier-2 classifier judge model {judge_model!r} is the same model "
            f"family as the target's generator ({generator_family!r}) — "
            f"self-preference bias risk; prefer a different judge family")

    # --- discovery-agent entries (Task 9) ---
    if discovery_model is not None:
        disc_fam = _model_family(discovery_model)
        # discovery <-> rubric judge, same family -> REFUSE (disqualifying): the
        # agent hunting for failures would be graded by its own family. Global
        # Constraint: refuse on judge<->agent collision.
        if _model_family(rubric_model) == disc_fam:
            msgs.append(
                f"{REFUSE_PREFIX}discovery agent model {discovery_model!r} is "
                f"the same model family as the rubric judge ({rubric_model!r}) "
                f"— the agent that hunts for failures would be graded by its "
                f"own family; this judge/agent self-preference collision is "
                f"disqualifying")
        # discovery <-> generator, same family -> WARN (soft caution), mirroring
        # the judge<->generator warnings above.
        if gen_fam and disc_fam == gen_fam:
            msgs.append(
                f"discovery agent model {discovery_model!r} is the same model "
                f"family as the target's generator ({generator_family!r}) — "
                f"self-preference bias risk; prefer a different discovery agent "
                f"family")

    return msgs


def build_task(pack: Pack, judge_model: str = "mockllm/model",
               rubric_judge_model: str | None = None,
               max_samples: int | None = None,
               cache_dir: Path | None = None,
               sink: EventSink = NULL_SINK, *,
               controller: RunController | None = None) -> Task:
    probes = pack.probes if max_samples is None else pack.probes[:max_samples]
    samples = [Sample(input=p.id, target=p.category, metadata=_probe_metadata(p)) for p in probes]
    k = max((p.samples for p in probes), default=1)
    rubric_model = rubric_judge_model or pack.spec.judge.rubric_model
    # build_task drives the gate/compare paths, which have no discovery agent —
    # so discovery_model stays None here and the discovery-family entries never
    # fire. The discover path (Task 10 CLI) calls family_warnings() directly.
    for msg in family_warnings(pack, judge_model=judge_model, rubric_model=rubric_model):
        warnings.warn(msg, UserWarning, stacklevel=2)
    # Task 19. `early_stopping` is passed ONLY when a controller exists, so a
    # default build is byte-identical to the one this function made before the
    # control channel existed (the Task 18 inertness standard).
    #
    # The detect is `inspect.signature`, and it has to be: `Task.__init__` ends
    # in `**kwargs`, so an unknown keyword is SILENTLY ABSORBED rather than
    # raising `TypeError`. "Pass it and catch TypeError" would report success on
    # a version that ignores it entirely — a pause button that does nothing.
    extra: dict = {}
    if controller is not None:
        if early_stopping_supported(Task):
            extra["early_stopping"] = controller.as_early_stopping()
        else:
            warnings.warn(
                "this inspect_ai build's Task takes no `early_stopping` "
                "parameter, so pause and cancel cannot stop this run — it will "
                "run to completion and spend in full. Install "
                "inspect_ai>=0.3.249,<0.4. (Detected by signature inspection: "
                "passing the argument would have been absorbed silently.)",
                # UserWarning, never RuntimeWarning (R4-44): a degraded control
                # channel must not kill an eval that is spending money.
                UserWarning, stacklevel=2)
    return Task(
        dataset=MemoryDataset(samples),
        # The sink is threaded through the task the same way `cache_dir` is:
        # as a plain argument. `NULL_SINK` by default, so a task built by any
        # existing caller is byte-identical to the one it built before.
        solver=session_solver(pack, sink=sink),
        scorer=[tier1_scorer(pack), tier2_scorer(judge_model),
                tier3_scorer(pack, rubric_model, cache_dir=cache_dir)],
        epochs=Epochs(k, [pass_at(k), pass_k(k), "mean"]),
        # A sample error (target hiccup on ONE probe) must not abort the whole
        # eval: with fail_on_error=False the errored sample lands in the log
        # with no checks, its probe keeps trials == 0, and the gate hard-fails
        # it as MISSING (fail-closed, PR #4 fix #2). Real infra failure still
        # raises via run_gate's log.status check.
        fail_on_error=False,
        **extra,
    )
