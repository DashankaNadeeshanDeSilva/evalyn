"""The opt-in event stream (Plan #4, Task 18) — and its provable no-op default.

A run that nobody is watching must behave **exactly** as it did before this
module existed. That is not an aspiration here, it is the acceptance criterion:
`tests/engine/test_events_noop.py` proves it four ways (a sink that explodes, a
`JsonlSink` that refuses to be constructed, an empty `runs/`, and byte-equal
artifacts). Everything below is shaped by that requirement.

**The sink is a parameter, never ambient state (ruling R4-43).** `run_gate`,
`build_task`, `session_solver`, `run_compare`, `run_discovery`, … all take
`sink: EventSink = NULL_SINK`. A `ContextVar` or a module-level global would be
less typing and would make the inertness claim unfalsifiable — you cannot
monkeypatch `JsonlSink` into a sentinel and *prove* nobody constructed one if
the wiring can arrive out of band. Explicit passing **is** the proof.

**`NULL_SINK` costs one Python method call that returns `None`.** No branch at
the call sites, no `if sink is not None`, nothing to get wrong on the path that
runs a paid gate.

**Concurrency is real, and it is not asyncio-only.** `gate` emits from Inspect's
event-loop thread; `discover` emits from an `asyncio.to_thread` worker. So the
lock is a `threading.Lock`, and the seq increment and the file write happen
**inside the same acquisition** — otherwise two writers could take seqs 1 and 2
and then write them in the order 2, 1, which passes a uniqueness assertion and
silently breaks the "file order == seq order" contract a live tail depends on.

**Losing telemetry must never take down a run that is spending money
(ruling R4-44).** An `OSError` mid-run (full disk, deleted file, revoked
permission) makes `emit` warn **once** with a `UserWarning` — never a
`RuntimeWarning`, because the suite runs `-W error::RuntimeWarning` and an I/O
hiccup would then become a hard failure — and then self-demote to a no-op for
the rest of the process.

**The wire shape**, one JSON object per line::

    {"seq": 1, "ts": "2026-08-11T…+00:00", "run_id": "…", "mode": "gate",
     "pid": 4242, "type": "run.started", "data": {…}}

The caller's `**fields` live under ``data`` rather than at the top level so a
field called ``type`` or ``seq`` can never shadow the envelope. `type` is
constrained by `EventName` in `evalyn.ui.models` — the frozen contract, imported
here rather than re-spelled (ruling R4-7), so the emitter and the SPA's switch
cannot drift. `tests/engine/test_events.py` walks the instrumented source files
and asserts every literal we emit is in that enum.

**A torn trailing line is expected, not exceptional.** `read_events` is reading
a file another process is appending to; seeing half of the last line is the
normal case, not corruption. It skips unparseable lines and returns what it
has.
"""
from __future__ import annotations

import json
import os
import threading
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

# The run-id grammar and the event-name vocabulary have ONE home each (R4-7):
# the frozen contract in `evalyn.ui.models`. That module is pure pydantic — no
# fastapi/starlette/uvicorn, asserted by `tests/ui/test_models.py` — so
# importing it costs the engine no web dependency. `engine/run.py` already does
# exactly this for `is_run_id`.
from evalyn.ui.models import EventName, RunMode, is_run_id

__all__ = ["EventSink", "NullSink", "NULL_SINK", "JsonlSink", "read_events",
           "trial_key", "hunt_key", "EVENT_NAMES"]

#: Every event name the engine is allowed to emit. Derived from the frozen
#: contract, never retyped.
EVENT_NAMES = frozenset(e.value for e in EventName)


@runtime_checkable
class EventSink(Protocol):
    """Where a run's progress goes. `NULL_SINK` is the default everywhere."""

    def emit(self, type: str, /, **fields) -> None:  # noqa: A002 — the wire name
        ...


class NullSink:
    """The default. Does nothing, cannot fail, allocates nothing."""

    def emit(self, type: str, /, **fields) -> None:  # noqa: A002 — the wire name
        return None

    def close(self) -> None:
        return None


#: The module singleton every engine entry point defaults to. One instance, so
#: `sink is NULL_SINK` is a meaningful identity check in a test.
NULL_SINK = NullSink()


def trial_key(probe_id: str, epoch: int) -> str:
    """`"<probe_id>#<epoch>"` — one trial's identity in the stream.

    The probe id comes from the sample's `metadata["id"]`, **not** `sample_id`
    (ruling R4-9): `engine/task_builder.py` builds `Sample(input=p.id, …)` with
    no `id=`, so Inspect assigns ordinal integers and `sample_id` is `1..N`.
    `engine/run.py`'s reducer already reads `metadata["id"]`; the stream must
    agree with the artifact or the cockpit cannot join them.
    """
    return f"{probe_id}#{epoch}"


def hunt_key(objective_id: str, persona_id: str) -> str:
    """`"<objective_id>::<persona_id>"` — one hunt's identity in the stream.

    The same string `discovery/task_builder.py` gives the sample as its `id`,
    so a hunt event and the discovery log's sample are joinable without a
    second convention.
    """
    return f"{objective_id}::{persona_id}"


class JsonlSink:
    """Append-only JSONL, one line per event. Constructed only when asked for.

    `buffering=1` (line buffering) plus an explicit `flush()` per event: the
    server tails this file live, and a fully-buffered writer makes a running
    eval look frozen for kilobytes at a time. Deliberately **no `fsync`** — a
    per-event sync would tax a paid run to protect against machine loss, and
    the artifact, not the stream, is the durable record.
    """

    def __init__(self, path: str | Path, *, run_id: str, mode: str) -> None:
        if not is_run_id(run_id):
            # The one grammar (R4-7). Refused at construction, before a run
            # spends anything, rather than writing a stream nothing can find.
            raise ValueError(
                f"not a run_id: {run_id!r} — expected an artifact stem like "
                f"'20260807T101112000000-deadbeef-example'")
        if mode not in {m.value for m in RunMode}:
            raise ValueError(
                f"not a run mode: {mode!r} — expected one of "
                f"{', '.join(sorted(m.value for m in RunMode))}")
        self.path = Path(path)
        self.run_id = run_id
        self.mode = mode
        self._pid = os.getpid()
        self._seq = 0
        self._lock = threading.Lock()
        self._demoted = False
        self._closed = False
        self._check_owner()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Append, never truncate: an existing stream belongs to this run and a
        # reopen must extend it, not silently delete the evidence already in it.
        self._fh = open(self.path, "a", encoding="utf-8", buffering=1)

    # -- construction guard ------------------------------------------------

    def _check_owner(self) -> None:
        """Refuse to append to a stream another process is writing.

        Two processes interleaving into one file would produce duplicate seqs
        and a stream whose order means nothing — and the shape that produces it
        (a stale `EVALYN_RUN_ID` exported in a shell, two launches racing for
        one id) is a configuration mistake worth failing loudly on, at
        construction, before either run spends. Reopening in the SAME process
        is fine and appends.
        """
        for event in read_events(self.path):
            pid = event.get("pid")
            if pid is not None and pid != self._pid:
                raise ValueError(
                    f"{self.path} is already being written by pid {pid} (this "
                    f"process is {self._pid}) — two processes must not share "
                    f"one event stream")
            return  # the first well-formed line settles ownership

    # -- emit --------------------------------------------------------------

    def emit(self, type: str, /, **fields) -> None:  # noqa: A002 — the wire name
        """Append one event. Never raises for an I/O reason (R4-44)."""
        if self._demoted or self._closed:
            return
        try:
            # The increment and the write are ONE critical section: splitting
            # them lets two threads take seqs 1 and 2 and then write 2 before
            # 1, which still looks unique but breaks file-order == seq-order.
            with self._lock:
                self._seq += 1
                line = json.dumps({
                    "seq": self._seq,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "run_id": self.run_id,
                    "mode": self.mode,
                    "pid": self._pid,
                    "type": type,
                    "data": fields,
                }, default=str)
                self._fh.write(line + "\n")
                self._fh.flush()
        except OSError as e:
            # `type` is the event name here (the wire spelling shadows the
            # builtin), so the exception class is read off the instance.
            self._demote(f"emitting {type!r}: {e.__class__.__name__}: {e}")

    def _demote(self, detail: str) -> None:
        """Warn once, then go quiet for the rest of the run."""
        self._demoted = True
        warnings.warn(
            f"the evalyn event stream at {self.path} failed and has been "
            f"disabled for the rest of this run ({detail}) — the run itself is "
            f"unaffected and its artifact will still be written",
            UserWarning, stacklevel=3)

    def close(self) -> None:
        """Idempotent. Closing never raises — the run has already finished."""
        if self._closed:
            return
        self._closed = True
        try:
            self._fh.close()
        except OSError:
            pass


def read_events(path: str | Path) -> list[dict]:
    """Every well-formed event in *path*, in file order. Missing file -> `[]`.

    **A torn trailing line is the normal case, not corruption.** This reads a
    file another process is appending to; catching it mid-`write` is expected
    and the half line is simply not an event yet. Lines that do not parse are
    skipped rather than raised on, so a live tail can never crash the reader.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return []
    events: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events
