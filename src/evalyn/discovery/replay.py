"""Replay-once — does the staged probe actually red the gate?

A confirmed finding has been graded by Evalyn's scorers against a transcript
that already happened. That is not the same claim as "this probe, run from
scratch, fails". Replay-once closes that gap, and it closes it by running the
**gate's own machinery** rather than a second opinion of its own: `build_task`
-> `inspect_eval` -> `reduce_log_to_probes`, exactly the pipeline `run_gate`
uses. If replay had its own reducer, a probe could reproduce here and pass in
`gate`, and the flywheel would be emitting probes that do not hold.

Three properties are load-bearing.

**1. The bytes on disk are the subject.** The staged file is read back and
`Probe.model_validate`d — never the in-memory `Probe` that `stage_probe` was
handed. What a human will `git mv` into `probes/` is a file; proving the object
reproduces would prove nothing about the file (a bad serialization, a mangled
provenance header, an unparseable value would all survive).

**2. `validate_pack` runs before the eval.** A one-probe pack — the real pack
with this probe as its only probe, so pack identity, invariants and `raw_files`
are intact — is validated first. That catches a `reference` that contradicts
the probe's own required check, an unknown invariant ref (which would silently
no-op at Tier-1 and make a real finding look unreproducible) and a missing
rubric file, all **before** a token is spent. Note the deliberate contrast with
`confirm.py`, which blanks the pack invariants so a candidate is judged on its
own checks alone: replay asks the opposite question — "does this probe red the
gate as configured?" — so the invariants stay.

**3. Reproduced ⇔ `trials >= 1 and pass_k == 0.0`** (spec §7). Both halves
matter. A run where every session errored has `pass_k == 0.0` too, and calling
that "reproduced" would launder a dead target into a confirmed finding. A
confirmed-but-not-reproduced finding is still a real finding — it happened
once — so this function only reports the verdict; flagging it flaky is the
caller's decision.

**Spend.** Replaying a probe that carries a `rubric` check invokes the real
tier-3 judge — that is money, and it is outside `SpendMeter`'s live charging,
which only sees the discovery agent's own calls. `ReplayResult.log_path` is
therefore populated whenever an eval ran, reproduced or not, so the caller can
reconcile the log into the meter; it is empty exactly when nothing ran and
nothing was spent. `rubric_model` defaults to the pack's configured judge,
which for most packs is a paid model — pass it explicitly to control that.

**Nothing raises out of `replay_staged_probe`** except Evalyn's own bug
classes. It runs once per confirmed finding inside a longer discovery run: an
unparseable staged file or a judge outage must come back as a verdict, not
abort the run and destroy every other finding. Programmer errors still surface
loudly, matching `confirm.py`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml
from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from evalyn.engine.run import reduce_log_to_probes
from evalyn.engine.task_builder import build_task
from evalyn.engine.validate import validate_pack
from evalyn.targets.loader import Pack
from evalyn.targets.schema import Probe

#: Evalyn's own bug classes. Everything else about a replay is environmental
#: (a hand-edited file, a judge outage, a target that died) and is reported;
#: these mean *this code* is wrong and must not be swallowed — same choice as
#: `confirm.py`.
_PROGRAMMER_ERRORS = (TypeError, AttributeError, NameError, KeyError)


@dataclass
class ReplayResult:
    """The verdict on one staged probe.

    `log_path` is the Inspect eval log — populated whenever an eval ran (so the
    caller can reconcile judge spend), empty when replay failed closed before
    the eval started. `reason` explains any verdict that is not `reproduced`.
    """
    reproduced: bool
    trials: int
    pass_k: float
    checks: list[dict] = field(default_factory=list)
    log_path: str = ""
    reason: str = ""


def _load_staged_probe(staged: Path) -> Probe:
    """The probe as it exists **on disk**, or `ValueError` explaining why not.

    `stage_probe` writes a one-entry YAML list (the `probes/*.yaml` shape, so
    adoption is a `git mv`). Anything else is a hand-edited or half-written
    file: rejected whole, with the shape checked explicitly so a mapping or an
    empty document cannot reach `Probe.model_validate` as an index error.
    """
    entries = yaml.safe_load(staged.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError(
            f"expected the one-entry YAML list `stage_probe` writes, got "
            f"{type(entries).__name__}"
            + (f" of {len(entries)} entries" if isinstance(entries, list) else ""))
    return Probe.model_validate(entries[0])


async def replay_staged_probe(pack: Pack, staged: Path, *,
                              judge_model: str = "mockllm/model",
                              rubric_model: str | None = None,
                              cache_dir: str | Path | None = None,
                              log_dir: str = "runs/logs") -> ReplayResult:
    """Run the staged probe through the gate and report whether it reds it.

    `rubric_model` defaults to the pack's configured tier-3 judge (a paid model
    for most packs) — see the module docstring on spend.
    """
    staged = Path(staged)
    try:
        one_probe_pack = replace(pack, probes=[_load_staged_probe(staged)])
    except _PROGRAMMER_ERRORS:
        raise
    except Exception as e:  # noqa: BLE001 — any unusable file is a verdict
        return ReplayResult(
            False, 0, 0.0,
            reason=f"staged file {staged.name!r} is not a loadable probe "
                   f"({type(e).__name__}: {e})")

    report = validate_pack(one_probe_pack)
    if not report.ok:
        # Fail closed BEFORE the eval: these are probes that cannot render an
        # honest verdict, and a tier-3 one would cost money to find that out.
        return ReplayResult(
            False, 0, 0.0,
            reason=f"staged probe {staged.name!r} fails validate-pack: "
                   + "; ".join(report.errors))

    # Same default as `run_gate`: the pack's own .cache, where `evalyn
    # calibrate` puts the validated grading steps.
    steps_cache = Path(cache_dir) if cache_dir is not None else Path(pack.root) / ".cache"
    try:
        task = build_task(one_probe_pack, judge_model=judge_model,
                          rubric_judge_model=rubric_model, cache_dir=steps_cache)
        # `inspect_eval` drives its own event loop, so it cannot be called from
        # inside one — replay is awaited from the discovery run. The worker
        # thread gets the loop; this one stays free.
        logs = await asyncio.to_thread(
            inspect_eval, task, model="mockllm/model", log_dir=log_dir,
            display="none")
        log = logs[0]
        if log.samples is None and log.location:
            log = await asyncio.to_thread(read_eval_log, log.location)
    except _PROGRAMMER_ERRORS:
        raise
    except Exception as e:  # noqa: BLE001 — a dead target/judge is a verdict
        return ReplayResult(
            False, 0, 0.0,
            reason=f"replay eval failed ({type(e).__name__}: {e})")

    log_path = str(log.location) if log.location else log_dir
    if log.status != "success":
        return ReplayResult(False, 0, 0.0, log_path=log_path,
                            reason=f"replay eval did not succeed: "
                                   f"status {log.status!r}")

    # The gate's own reducer, on the one-probe pack -> exactly one result.
    result = reduce_log_to_probes(log, one_probe_pack)[0]
    reproduced = result.trials >= 1 and result.pass_k == 0.0
    if reproduced:
        reason = ""
    elif result.trials == 0:
        reason = ("no scored trial — every replay session errored (target down "
                  "or misconfigured?), so nothing was reproduced")
    else:
        reason = (f"the probe passed the gate on replay "
                  f"(pass^k {result.pass_k} over {result.trials} trial(s))")
    return ReplayResult(reproduced, result.trials, result.pass_k,
                        result.checks, log_path, reason)
