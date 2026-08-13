from __future__ import annotations

# httpx is not called here anymore (TargetSession owns the client), but the
# import stays: tests patch the client via this module's namespace
# (`evalyn.engine.solver.httpx.AsyncClient`), which lands on the shared httpx
# module that TargetSession resolves at call time.
import httpx  # noqa: F401
from inspect_ai.model import ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import concurrency

from evalyn.engine.events import NULL_SINK, EventSink, trial_key
from evalyn.targets.loader import Pack, resolve_base_url
from evalyn.targets.session import TargetSession


@solver
def session_solver(pack: Pack, *, sink: EventSink = NULL_SINK) -> Solver:
    """The probe session driver. `sink` defaults to the inert `NULL_SINK`.

    The sink arrives as a **constructor argument** and is captured by the
    closure (ruling R4-43) — never a ContextVar. That is what lets
    `tests/engine/test_events_noop.py` prove a default run constructs no sink at
    all: if the wiring could arrive out of band, the proof would be vacuous.
    """
    # Fail fast at solver construction, before any run is scheduled; open()
    # re-enforces the allowlist on every session (containment layer).
    resolve_base_url(pack)
    max_turns = pack.spec.budget.max_turns_per_session

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        turns = state.metadata["turns"]
        # R4-9: the probe id lives in metadata["id"], NOT sample_id —
        # `task_builder` builds `Sample(input=p.id, …)` with no `id=`, so
        # Inspect assigns ordinals 1..N and `sample_id` is the WRONG identity.
        # This is the same read `run.py`'s reducer makes, so the stream and the
        # artifact agree on probe identity (asserted by the gate call-site test,
        # which requires the keys to read `work-history#…` and not `1#…`).
        # `.get` with a fallback, not `[...]`: adding telemetry must not add a
        # new way for a session to die. Every real run has the key; a hand-built
        # TaskState in a unit test may not, and that is not a reason to raise
        # inside the solver on the paid path.
        probe_id = (state.metadata or {}).get("id", state.sample_id)
        key = trial_key(probe_id, state.epoch)
        sink.emit("trial.started", trial_key=key, probe_id=probe_id,
                  epoch=state.epoch, category=(state.metadata or {}).get("category"),
                  turns=len(turns))
        if len(turns) > max_turns:
            raise RuntimeError(
                f"probe has {len(turns)} turns > max_turns_per_session={max_turns}")
        # Inspect seeds state.messages from Sample.input (the probe id, kept
        # for log/viewer identity). That fabricated "user turn" must never
        # reach the judged transcript — Tier-2/3 prompts would leak probe-id
        # labels the calibration anchors never saw (PR #4 fix #5). The real
        # conversation is rebuilt below from the probe's turns.
        state.messages.clear()
        last = ""
        async with concurrency("evalyn-target-http", pack.spec.concurrency):
            # TargetSession's clock starts INSIDE the concurrency gate (user
            # ruling 2026-08-03): session_seconds measures target session time
            # only (open + every turn), never Evalyn's own scheduler queue
            # wait — otherwise compare-mode latency deltas would shift with
            # concurrency settings.
            async with TargetSession.open(pack) as session:
                try:
                    for i, turn in enumerate(turns, start=1):
                        sink.emit("turn.sent", trial_key=key, turn=i, text=turn)
                        last = await session.send(turn)
                        sink.emit("turn.received", trial_key=key, turn=i, text=last)
                finally:
                    # Runs even when a send fails mid-session: the errored
                    # sample's log keeps the partial transcript (completed
                    # pairs + the failed turn's dangling user message), as it
                    # did before the TargetSession extraction.
                    state.messages.extend(session.messages)
            elapsed = session.elapsed_seconds
        # Store persists to the log sample, where the reducer picks it up as
        # trial_records.session_seconds (Task 6, #2b).
        state.store.set("evalyn:session_seconds", elapsed)
        state.output = ModelOutput.from_content(model="evalyn-target", content=last)
        # After the store write, so a cockpit that reacts to trial.finished sees
        # the same session_seconds the artifact will carry. NOT in a `finally`:
        # a trial that raised did not finish, and Inspect's fail_on_error=False
        # already records the errored sample.
        sink.emit("trial.finished", trial_key=key, session_seconds=elapsed)
        return state

    return solve
