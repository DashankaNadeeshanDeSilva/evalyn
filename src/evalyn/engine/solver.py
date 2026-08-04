from __future__ import annotations

# httpx is not called here anymore (TargetSession owns the client), but the
# import stays: tests patch the client via this module's namespace
# (`evalyn.engine.solver.httpx.AsyncClient`), which lands on the shared httpx
# module that TargetSession resolves at call time.
import httpx  # noqa: F401
from inspect_ai.model import ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import concurrency

from evalyn.targets.loader import Pack, resolve_base_url
from evalyn.targets.session import TargetSession


@solver
def session_solver(pack: Pack) -> Solver:
    # Fail fast at solver construction, before any run is scheduled; open()
    # re-enforces the allowlist on every session (containment layer).
    resolve_base_url(pack)
    max_turns = pack.spec.budget.max_turns_per_session

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        turns = state.metadata["turns"]
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
                for turn in turns:
                    last = await session.send(turn)
            state.messages.extend(session.messages)
            elapsed = session.elapsed_seconds
        # Store persists to the log sample, where the reducer picks it up as
        # trial_records.session_seconds (Task 6, #2b).
        state.store.set("evalyn:session_seconds", elapsed)
        state.output = ModelOutput.from_content(model="evalyn-target", content=last)
        return state

    return solve
