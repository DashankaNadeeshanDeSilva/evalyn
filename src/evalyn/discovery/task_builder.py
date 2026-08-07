"""The hunt dataset: objectives x personas, capped fairly.

`build_discovery_task` is the `gate` task builder's opposite number, and the
differences are the interesting part:

* **No scorer** (spec §7, ruling R8-8). `discover` has no pass/fail verdict —
  the agent proposes and Evalyn's real scorers dispose, inside the session, via
  `Confirmer`. A record-only scorer here would be a fake judge sitting exactly
  where the trust boundary lives, and the resulting Inspect metrics would look
  like verdicts. The consequence — a discovery log carries no metrics — is
  intended; the evidence travels in the sample store instead.
* **`fail_on_error=False`**, as in `gate`: one hunt that explodes must not take
  the other hunts down with it. `run_session` already converts errors into a
  partial result, so this is defence in depth.
* **The dataset is capped by `Limits.max_sessions`, round-robin over
  objectives** (ruling R8-12). Truncating a sorted product would hand every
  session to the first objective and silently drop the other hunt types — a
  failure that reads as "discover found nothing" rather than "discover never
  looked". Ordering is deterministic (objectives in config order, personas by
  id) so a seeded run is reproducible.

* **A tier-3 hunt with no rubric judge warns here**, because this is the one
  place that is decidable before anything runs — see `_warn_unjudgeable_hunts`.

The playbook is a run-level choice, not a dataset dimension: one more axis
would multiply sessions without adding coverage of a *different* weakness.
"""
from __future__ import annotations

import warnings
from collections.abc import Sequence

from inspect_ai import Task
from inspect_ai.dataset import MemoryDataset, Sample

from evalyn.discovery.config import DiscoveryConfig
from evalyn.discovery.confirm import Confirmer
from evalyn.discovery.meter import SpendMeter
from evalyn.discovery.objectives import Objective, get_objective
from evalyn.discovery.personas import load_personas, load_playbooks
from evalyn.discovery.solver import discovery_solver
from evalyn.targets.loader import Pack


def plan_hunts(objective_ids: Sequence[str], persona_ids: Sequence[str],
               max_sessions: int) -> list[tuple[str, str]]:
    """`(objective_id, persona_id)` pairs, at most `max_sessions` of them.

    Persona-major on purpose: every objective gets a session with the first
    persona before any objective gets a second one. Never repeats a pair — the
    product is the ceiling, whatever the cap says.
    """
    pairs = [(oid, pid) for pid in persona_ids for oid in objective_ids]
    return pairs[:max(max_sessions, 0)]


def _needs_rubric_judge(objective: Objective) -> bool:
    """True when confirming this hunt would call the rubric judge.

    Asks the objective's own check factory rather than trusting `tier`: the
    checks are what `Confirmer` actually evaluates, `tier` is bookkeeping
    alongside them, and this warning must not go quiet if the two ever drift.
    The factory validates its slots, so it is fed placeholders — and if it
    rejects them anyway, `tier` is the fallback rather than a crashed build.
    """
    placeholders = {name: "placeholder" for name in objective.slot_schema}
    try:
        checks = objective.confirm_checks(placeholders)
    except Exception:  # noqa: BLE001 — a build-time warning may not be fatal
        return objective.tier >= 3
    return any(c.type == "rubric" for c in checks)


def _warn_unjudgeable_hunts(objective_ids: Sequence[str],
                            rubric_judge_model: str | None) -> None:
    """A tier-3 hunt with no judge configured can never produce a finding.

    `Confirmer.confirm` fails closed without a rubric model — every rubric
    candidate comes back `unsure`, and unsure is never a finding. So the run
    would report "found nothing" when the truth is "could not judge": the same
    failure shape R8-12 exists to prevent, on a different axis. This is the one
    place it is decidable in advance, and warning here covers the Python API
    and not just the CLI. A WARNING, never a refusal — refusing is the CLI
    preflight's call (Task 10), and a run that selected only deterministic
    objectives must stay silent.
    """
    if rubric_judge_model:
        return
    blind = [oid for oid in objective_ids if _needs_rubric_judge(get_objective(oid))]
    if not blind:
        return
    warnings.warn(
        f"no rubric judge is configured (rubric_judge_model is None), so the "
        f"tier-3 hunt(s) {', '.join(blind)} CANNOT produce a finding — every "
        f"rubric-checked candidate comes back unsure, which is never a "
        f"finding; set a rubric judge model or deselect those objectives",
        UserWarning, stacklevel=3)


def _select(kind: str, loaded: dict, requested: str | None) -> dict:
    if requested is None:
        return loaded
    if requested not in loaded:
        raise KeyError(
            f"unknown {kind} {requested!r} — this pack offers: "
            f"{', '.join(sorted(loaded))}")
    return {requested: loaded[requested]}


def build_discovery_task(pack: Pack, cfg: DiscoveryConfig, *,
                         meter: SpendMeter, confirmer: Confirmer | None = None
                         ) -> Task:
    """The `discover` task. `meter` is the caller's — one meter per run, shared
    by every hunt, so the caller can read `spent_usd` and reconcile afterwards.
    """
    personas = _select("persona", load_personas(pack), cfg.persona)
    playbooks = _select("playbook", load_playbooks(pack), cfg.playbook)
    # Deterministic pick when the pack ships several and the operator named
    # none: first by id, not dict insertion order.
    playbook_id = sorted(playbooks)[0]

    pairs = plan_hunts(list(cfg.objectives), sorted(personas),
                       cfg.limits.max_sessions)
    # Over the objectives actually SCHEDULED, not everything selected: a hunt
    # the session cap dropped is not a hunt that reports nothing.
    _warn_unjudgeable_hunts(list(dict.fromkeys(oid for oid, _ in pairs)),
                            cfg.rubric_judge_model)
    samples = [
        Sample(id=f"{oid}::{pid}",
               input=f"hunt {oid} as {pid}",
               metadata={"objective_id": oid, "persona_id": pid,
                         "playbook_id": playbook_id})
        for oid, pid in pairs]

    # The default Confirmer is metered by construction: `Confirmer` refuses a
    # rubric model without a meter, and tier-3 confirmations are live spend.
    confirmer = confirmer or Confirmer(
        pack, rubric_model=cfg.rubric_judge_model, meter=meter)

    return Task(
        dataset=MemoryDataset(samples),
        solver=discovery_solver(
            pack, agent_model=cfg.agent_model, meter=meter, limits=cfg.limits,
            confirmer=confirmer, personas=personas, playbooks=playbooks,
            seed=cfg.seed),
        fail_on_error=False,
    )
