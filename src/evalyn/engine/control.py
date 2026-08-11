"""Pause, resume and cancel for a running eval (Plan #4, Task 19).

One small file, one control file, and no signals.

**The control file is the only mechanism (ruling R4-11).** The server writes
`runs/<run_id><suffix>.control.json`; the engine polls it at its own
checkpoints. Signals were measured and rejected: `SIGTERM` leaves a partial log
at `status='started'` — which `run_gate` refuses — with a completed,
already-paid-for sample stranded in Inspect's buffer outside the log, and
`SIGINT` returns zero logs to the caller so `logs[0]` raises `IndexError`.
Nothing here sends, installs or escalates to a signal, and `ack_timeout` kills
nothing (see its docstring below).

**"Pause" means "start no new samples". It does not freeze the world, and it
does not stop spending (ruling R4-12).** Samples already past their checkpoint
and inside the solver run to completion: their target HTTP calls and their
judge calls continue and are still billed. With the default `concurrency` of 4
that can be four in-flight paid sessions after the operator clicks Pause. The
cockpit's copy — "Pause (finishes in-flight trials)" — is the honest
description, and nothing here may be documented as more than that.

**Cancel is global, never per-probe (ruling R4-10).** `schedule_sample(id,
epoch)` only decides halt-or-don't, and the `EarlyStop` it returns simply
**echoes back** the id it was handed. There is no ordinal-to-probe-id mapping
here and no dependency on the pack; per-probe cancel would be a new design, not
a patch to this one.

**The `control.*` event IS the acknowledgement.** The HTTP response to a
control request only says the file was written; the run saying `control.paused`
/ `control.resumed` / `control.cancelled` on its event stream is what says the
run actually noticed. A cancel that is never acked is an honest `interrupted`
run that names its pid, not a process anybody killed.

**The sink is a parameter, never ambient state (R4-43)**, for the same reason
`engine/events.py` gives: explicit passing is what makes "a default run
constructs nothing" provable.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai import Task
from inspect_ai.util import EarlyStop

from evalyn.engine.events import NULL_SINK, EventSink
# The action vocabulary has ONE home (the same medicine R4-7 applied to the
# run-id grammar and the event names): the frozen contract in
# `evalyn.ui.models`. The server writes these strings and the engine reads
# them; a second spelling is exactly the drift the contract exists to prevent.
# That module is pure pydantic, so this costs the engine no web dependency.
from evalyn.ui.models import ControlAction

__all__ = ["RunCancelled", "RunController", "CONTROL_ACTIONS",
           "CONTROL_MANAGER_NAME", "CANCEL_REASON", "early_stopping_supported"]

#: Every action the control file may carry, derived from the frozen contract.
CONTROL_ACTIONS = frozenset(a.value for a in ControlAction)

#: The name this early-stopping manager reports to Inspect. It lands in the
#: eval log as `results.early_stopping.manager`, which is how a log alone
#: distinguishes "Evalyn's operator cancelled this" from any other stop.
CONTROL_MANAGER_NAME = "evalyn-control"

#: Carried on every `EarlyStop`, round-tripped to disk in
#: `results.early_stopping.early_stops[].reason`.
CANCEL_REASON = "operator cancelled"


class RunCancelled(Exception):
    """The operator cancelled this run; raised at a checkpoint.

    A control-flow signal, not a failure: `discovery/loop.py` catches it
    **before** its blanket `except Exception` precisely so a cancelled hunt is
    recorded as `stop_reason="cancelled"` and never as `"error"`.
    """


def early_stopping_supported(task_cls: type = Task) -> bool:
    """Does this Inspect version's `Task` accept `early_stopping=`?

    **This must be a signature inspection, and nothing else.** `Task.__init__`
    ends in `**kwargs`, so an unknown keyword is *silently absorbed* rather than
    raising `TypeError` — measured on 0.3.249, where
    `Task(some_unknown_kwarg=1)` constructs happily. A feature-detect written
    as "pass it and catch `TypeError`" would therefore report success on a
    version that ignores the argument entirely, and we would ship a pause button
    that does nothing at all. `tests/engine/test_control.py` pins both halves:
    that the absorption is real, and that this function sees through it.
    """
    try:
        params = inspect.signature(task_cls).parameters
    except (TypeError, ValueError):  # not introspectable — assume not supported
        return False
    return "early_stopping" in params


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunController:
    """Reads (and writes) one run's control file. Polls; never blocks on IO.

    *path* is `ui.paths.control_path(artifact)` — derived, never hand-built.
    *sink* is where the acks go, inert by default.

    The engine side calls `checkpoint()` at the few places a run can safely
    stop, and hands `as_early_stopping()` to `Task(...)` so Inspect asks before
    scheduling each sample. The requester side calls `request()`.

    **Pause starts no new samples; it does not stop the ones already running,
    and those keep spending real money** (R4-12). Say it that way everywhere.
    """

    def __init__(self, path: str | Path, sink: EventSink = NULL_SINK, *,
                 poll_seconds: float = 0.25, ack_timeout: float = 60.0) -> None:
        self.path = Path(path)
        self.sink = sink
        self.poll_seconds = poll_seconds
        #: How long a REQUESTER should wait for the matching `control.*` ack
        #: before calling the run unacknowledged. **This class never acts on
        #: it.** It sends no signal, kills nothing and shortens nothing
        #: (R4-11): an unacked cancel is an honest `interrupted` run that named
        #: its pid on the stream, and what to do about that is an operator's
        #: decision, not this object's.
        self.ack_timeout = ack_timeout
        self._paused = False
        self._cancelled = False
        #: `(st_mtime_ns, st_size)` of the last successfully PARSED read. A
        #: failed parse deliberately does not update it, so a torn write is
        #: re-read on the next poll rather than latched forever.
        self._sig: tuple[int, int] | None = None
        self._action: str | None = None
        self._warned_unknown: set[str] = set()

    # -- requester side ----------------------------------------------------

    def request(self, action: str) -> Path:
        """Write *action* to the control file, atomically. Returns the path.

        Temp-then-rename, the house pattern: the engine polling this file must
        never see half a JSON object. (`refresh` survives one anyway, but the
        guarantee is cheap and the failure mode it removes is a paused run that
        never resumes.)
        """
        if action not in CONTROL_ACTIONS:
            raise ValueError(
                f"not a control action: {action!r} — expected one of "
                f"{', '.join(sorted(CONTROL_ACTIONS))}")
        payload = {"action": action, "requested_at": _now(),
                   "requested_by_pid": os.getpid()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2))
        os.replace(tmp, self.path)
        return self.path

    # -- engine side -------------------------------------------------------

    @property
    def paused(self) -> bool:
        """Last observed pause state. `refresh()` is what updates it."""
        return self._paused

    @property
    def cancelled(self) -> bool:
        """Once true, always true — a cancel is not retractable."""
        return self._cancelled

    def refresh(self, where: str = "") -> str | None:
        """Re-read the control file **only if it changed**; return the action.

        `stat` first, parse second: at a 0.25 s poll and four in-flight samples
        this runs often enough that re-parsing an unchanged file would be
        gratuitous IO on a paid run.

        *where* names the checkpoint, and rides along on the ack so the cockpit
        can say where the run actually stopped.
        """
        if self._cancelled:
            return ControlAction.cancel.value
        try:
            st = self.path.stat()
        except OSError:
            # No control file is the overwhelmingly common case (nobody has
            # asked for anything), and an unreadable one must not take down a
            # run that is spending money. Either way: no change.
            return self._action
        sig = (st.st_mtime_ns, st.st_size)
        if sig == self._sig:
            return self._action
        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A torn write, caught mid-rename on a filesystem that does not
            # give us atomicity. `_sig` is left alone on purpose so the next
            # poll re-reads rather than latching this file as "seen".
            return self._action
        self._sig = sig
        action = obj.get("action") if isinstance(obj, dict) else None
        if action not in CONTROL_ACTIONS:
            if action not in self._warned_unknown:
                self._warned_unknown.add(action if isinstance(action, str) else "")
                warnings.warn(
                    f"ignoring unrecognised control action {action!r} in "
                    f"{self.path} — expected one of "
                    f"{', '.join(sorted(CONTROL_ACTIONS))}; the run continues "
                    f"unchanged",
                    # UserWarning, never RuntimeWarning (R4-44): the suite runs
                    # `-W error::RuntimeWarning` and a control-file typo must
                    # not kill a paid eval.
                    UserWarning, stacklevel=2)
            return self._action
        self._apply(action, where)
        return self._action

    def _apply(self, action: str, where: str) -> None:
        """Adopt *action* and emit its ack — the ack IS the `control.*` event.

        Emitted only on a real transition, so a run that sits paused for ten
        minutes acks once rather than 2,400 times.
        """
        previous = self._action
        self._action = action
        if action == ControlAction.cancel.value:
            if self._cancelled:
                return
            self._cancelled = True
            self._paused = False
            self.sink.emit("control.cancelled", where=where, pid=os.getpid(),
                           reason=CANCEL_REASON)
            return
        if action == ControlAction.pause.value:
            if self._paused:
                return
            self._paused = True
            self.sink.emit("control.paused", where=where, pid=os.getpid())
            return
        # resume
        if previous is not None and not self._paused:
            return
        self._paused = False
        self.sink.emit("control.resumed", where=where, pid=os.getpid())

    async def checkpoint(self, *, key: str) -> None:
        """Block while paused; raise `RunCancelled` if cancelled; else return.

        The one place the engine yields control of a run. Cancel is checked
        first and on every pass, so a run paused for an hour still cancels at
        the next poll.
        """
        while True:
            self.refresh(key)
            if self._cancelled:
                raise RunCancelled(f"run cancelled by operator at {key}")
            if not self._paused:
                return
            await asyncio.sleep(self.poll_seconds)

    def as_early_stopping(self) -> "_ControlEarlyStopping":
        """An Inspect `EarlyStopping` manager backed by this control file."""
        return _ControlEarlyStopping(self)


class _ControlEarlyStopping:
    """Inspect's `EarlyStopping` protocol, driven by a `RunController`.

    Inspect calls `schedule_sample` **before** a sample is scheduled, and the
    spike measured that returning an `EarlyStop` there leaves
    `log.status == "success"` — so `run_gate`'s status guard needs no change —
    while blocking there trips no watchdog and is not charged against any
    sample's time limit.
    """

    def __init__(self, controller: RunController) -> None:
        self._c = controller
        self._stops = 0
        self._scheduled = 0

    async def start_task(self, task, samples, epochs) -> str:  # noqa: ANN001
        return CONTROL_MANAGER_NAME

    async def schedule_sample(self, id, epoch: int) -> EarlyStop | None:  # noqa: A002
        """Halt-or-don't for one (sample, epoch). Pauses here start no new work.

        `id` is **echoed back** untouched (R4-10). This method takes no
        dependency on the pack and does no ordinal-to-probe-id mapping: pause
        and cancel are global, run-level decisions and nothing here needs to
        know which probe it is looking at.
        """
        key = f"{id}#{epoch}"
        while True:
            self._c.refresh(key)
            if self._c.cancelled:
                self._stops += 1
                return EarlyStop(id=id, epoch=epoch, reason=CANCEL_REASON,
                                 metadata={"manager": CONTROL_MANAGER_NAME})
            if not self._c.paused:
                self._scheduled += 1
                return None
            # Pause = start no new samples. Everything already past this line
            # keeps running, and keeps spending (R4-12).
            await asyncio.sleep(self._c.poll_seconds)

    async def complete_sample(self, id, epoch: int, scores) -> None:  # noqa: A002
        return None

    async def complete_task(self) -> dict:
        return {"cancelled": self._c.cancelled, "early_stops": self._stops,
                "scheduled": self._scheduled}
