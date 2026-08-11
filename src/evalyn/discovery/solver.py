"""One Inspect Sample = one hunt.

The solver is deliberately thin: it resolves the sample's hunt (objective,
persona, playbook), runs `run_session` **inside the sample**, and puts the
`SessionResult` in the sample store. Three of those words are load-bearing.

**"inside the sample."** The agent's reasoning calls go through
`get_model(agent_model)` in `loop.py`, and Inspect records a model call against
whichever sample is executing when it happens. Hosting the hunt here is
therefore what makes agent spend appear in the discovery eval log's
`stats.model_usage` (keyed by the agent's own model name, aggregated
independently of the task's default model) — which is the only reason
`meter.reconcile(log)` can see it at all. Move the hunt out of the solver and
the live meter becomes the sole record of agent spend, with no log-authoritative
cross-check. *Caveat:* this proves the plumbing, not the provider. `mockllm`
synthesises usage; a real provider that omits `ModelOutput.usage` makes the log
inherit the omission, and `reconcile` then **under-reports silently** — which is
exactly why `charge_output`'s pessimistic fallback must stay (it over-reports
loudly in the same situation).

**"the sample store."** The discovery task has NO scorer (spec §7: a
record-only scorer would be a fake judge sitting exactly where the trust
boundary lives), so `state.store` is the only channel out of a sample.
`evalyn:discovery_session` mirrors `evalyn:session_seconds` in `engine/`:
written as a plain dict, read back with `session_from_store`. A dataclass would
not survive the JSON round-trip through the log file.

**"resolves."** Nothing here decides anything about the hunt. The objective is
looked up by id and an unknown id raises rather than defaulting — a
dataset/solver mismatch is an Evalyn bug and must not degrade into a silently
different hunt.

Two bounds this module owns:

* **Concurrency (R8-6).** `TargetSession` carries no `concurrency()` gate — the
  gate lives in the caller, exactly as in `engine/solver.py`. Discovery opens
  its own around the whole session, keyed `evalyn-target-http` with the pack's
  own limit, so `discover` cannot hammer a target harder than `gate` does.
* **The shared meter (R8-11).** One `SpendMeter` is shared by every hunt and
  `exhausted()` is a check-then-act across `await` points: two concurrent
  sessions can both observe "not exhausted" and both spend. The overshoot is
  bounded by one call per in-flight session — i.e. by the gate above — and that
  is accepted, not fixed: making the meter strictly atomic with locks would
  trade a bounded, documented overshoot for deadlock risk on the hot path.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

from inspect_ai.model import ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import concurrency

from evalyn.discovery.confirm import Confirmation
from evalyn.discovery.config import Limits
from evalyn.discovery.loop import SessionResult, StepRecord, run_session
from evalyn.discovery.meter import SpendMeter
from evalyn.discovery.objectives import get_objective
from evalyn.discovery.personas import (
    DEFAULT_PERSONA,
    DEFAULT_PLAYBOOK,
    Persona,
    Playbook,
)
from evalyn.engine.control import RunController
from evalyn.engine.events import NULL_SINK, EventSink
from evalyn.targets.loader import Pack, resolve_base_url

#: Sample-store key for one hunt's `SessionResult`. Stable: `run.py` (Task 8b)
#: and any future reader of a discovery log depend on this exact string.
DISCOVERY_STORE_KEY = "evalyn:discovery_session"


def session_to_store(result: SessionResult) -> dict:
    """`SessionResult` -> a plain JSON-able dict, for the sample store."""
    return asdict(result)


def session_from_store(value: Mapping | None) -> SessionResult | None:
    """The inverse, over a store dict read back from an eval log.

    Returns `None` for a missing entry (a sample that errored before the solver
    stored anything) — absence is a state the caller must handle, not a crash.
    Everything else is reconstructed strictly: an unexpected shape raises, so a
    contract drift between writer and reader fails loudly instead of yielding a
    half-populated result that reads like a hunt which found nothing.
    """
    if value is None:
        return None
    data = dict(value)
    confirmed = data.pop("confirmed", None)
    steps = data.pop("steps", None) or []
    return SessionResult(
        confirmed=Confirmation(**confirmed) if confirmed else None,
        steps=[StepRecord(**s) for s in steps],
        **data,
    )


def _resolve(kind: str, mapping: Mapping[str, object], key: str):
    try:
        return mapping[key]
    except KeyError:
        raise KeyError(
            f"sample requests {kind} {key!r}, which this run did not load — "
            f"available: {', '.join(sorted(mapping)) or '(none)'}") from None


@solver
def discovery_solver(pack: Pack, *, agent_model: str, meter: SpendMeter,
                     limits: Limits, confirmer,
                     personas: Mapping[str, Persona] | None = None,
                     playbooks: Mapping[str, Playbook] | None = None,
                     seed: int | None = None,
                     sink: EventSink = NULL_SINK,
                     controller: RunController | None = None) -> Solver:
    """One hunt per sample. `state.metadata` carries `objective_id`,
    `persona_id`, `playbook_id`; the result lands in the sample store.

    `sink` is a constructor argument captured by the closure (R4-43), inert by
    default. `controller` travels the same way and for the same reason — it is
    the last hop from `run_discovery` to `loop._drive`'s pause/cancel
    checkpoint, and `None` means this run cannot be paused or stopped."""
    # Fail fast at solver construction, before any run is scheduled — the same
    # containment check `gate` makes. `TargetSession.open` re-enforces the
    # allowlist on every session.
    resolve_base_url(pack)
    personas = dict(personas) if personas else {DEFAULT_PERSONA.id: DEFAULT_PERSONA}
    playbooks = dict(playbooks) if playbooks else {DEFAULT_PLAYBOOK.id: DEFAULT_PLAYBOOK}

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        objective = get_objective(state.metadata["objective_id"])
        persona_id = state.metadata.get("persona_id") or DEFAULT_PERSONA.id
        playbook_id = state.metadata.get("playbook_id") or DEFAULT_PLAYBOOK.id
        persona = _resolve("persona", personas, persona_id)
        playbook = _resolve("playbook", playbooks, playbook_id)

        async with concurrency("evalyn-target-http", pack.spec.concurrency):
            # `run_session` never raises: budget stops and unexpected errors
            # come back as a partial result, which the store write below keeps.
            result = await run_session(
                pack, objective, persona, playbook, agent_model=agent_model,
                meter=meter, limits=limits, confirmer=confirmer, seed=seed,
                sink=sink, controller=controller)

        state.store.set(DISCOVERY_STORE_KEY, session_to_store(result))
        # No scorer runs, so this is purely the viewer's one-line summary.
        state.output = ModelOutput.from_content(
            model="evalyn-discovery",
            content=f"{objective.id}: {result.stop_reason}")
        return state

    return solve
