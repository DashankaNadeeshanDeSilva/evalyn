"""Server-sent events over the engine's JSONL stream (Plan #4, Task 20).

The engine writes one JSON object per line to `runs/<stem>.events.jsonl`
(`engine/events.py`), shaped::

    {"seq": 7, "ts": "...", "run_id": "...", "mode": "gate", "pid": 900,
     "type": "spend.updated", "data": {"judge_usd": 0.25}}

This module turns that file into an SSE stream. It is deliberately small: a
dependency was considered and rejected in writing (`pyproject.toml:44-50` —
"the event stream is ~30 lines of `StreamingResponse`").

**The mapping onto SSE is not arbitrary; the already-merged consumer fixes it.**
`ui/src/hooks/useRunEvents.ts` reads `judge_usd`, `probe_id`, `pass_k` and
`exit_code` at the *top level* of the parsed `data:` body, and takes the frame's
sequence from `EventSource`'s `lastEventId`. So:

* `id:` is the sink's `seq`, which is what makes `Last-Event-ID` resumption work
  without anyone building a cursor by hand;
* `event:` is the record's `type`;
* `data:` is `record["data"]` **alone**, not the whole record. Framing the whole
  record would put every field the SPA reads one level too deep, and the live
  readout would show nothing while looking perfectly healthy.

**Redaction is this module's own job.** The `/api` chokepoint explicitly
declines to touch a streaming body — `redact.py:626-628` returns early with
"streaming, file, or empty: not ours" — so the one route that is on screen
throughout a live run is the one route `RedactingRoute` does not cover. The
`scrub` parameter is not optional decoration; the endpoint always passes the
app's own `Redactor`.

**Three independent ways to stop**, because a generator that can only be
stopped one way is a generator that hangs when that way does not happen:

1. `run.finished` in the file — the run is over, whether or not this subscriber
   was the one to see it emitted.
2. `is_disconnected` — the client went away. Starlette only discovers a dead
   client when it next tries to *write*, and an idle run writes nothing, so
   without this an abandoned tab leaks a task until the idle timeout.
3. The idle timeout — the backstop, for a child that died without ever writing
   `run.finished`.
"""
from __future__ import annotations

import asyncio
import codecs
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from evalyn.ui.models import EventName

__all__ = ["sse_frame", "parse_record", "split_lines", "event_stream",
           "DEFAULT_IDLE_TIMEOUT", "DEFAULT_POLL_INTERVAL", "IDLE_COMMENT"]

#: How long a stream may produce nothing before it closes.
#:
#: A backstop, not a policy: stop (2) already reaps an abandoned subscriber
#: within one poll, and stop (1) handles an orderly finish. This one exists for
#: the case neither covers — a child killed outside the cockpit, which writes no
#: `run.finished` and leaves a socket whose client is still perfectly connected.
#: Closing is cheap for the browser: `EventSource` reconnects on its own and
#: resumes from its `Last-Event-ID`, so nothing is lost by being wrong here.
#:
#: Counted as `poll_interval` per poll that found no bytes, not off a clock, so
#: it is a floor in wall-clock terms: a loaded machine reaches it later, never
#: sooner. That is the safe direction — the failure it must never cause is
#: cutting off a run that is still producing.
DEFAULT_IDLE_TIMEOUT = 120.0

#: Stat-and-read cadence while tailing. The file is local and usually empty on
#: read, so this is a syscall pair ten times a second, against a run whose
#: individual steps are network round-trips to a judge.
DEFAULT_POLL_INTERVAL = 0.1

#: An SSE **comment**, not an event. It carries no `id:`, so it cannot advance
#: the browser's resume cursor and cannot be read as a gap by the consumer's
#: sequence check — which an event named `heartbeat` would be, since the fold
#: counts `seq` gaps as lost frames.
IDLE_COMMENT = ": idle-timeout\n\n"

_RUN_FINISHED = EventName.run_finished.value


def sse_frame(record: Mapping[str, Any]) -> str | None:
    """One `id:`/`event:`/`data:` frame, or `None` for an unusable record.

    Returns `None` rather than raising, because the caller is tailing a file
    that a *different process* is writing: a record this build cannot address
    is one event's worth of detail lost, never a reason to tear down a live
    run's readout.

    Two of the refusals are structural rather than fussy. A record with no
    integer `seq` has no `id:`, and a frame with no `id:` leaves the browser's
    `lastEventId` holding the *previous* frame's value — so a reconnect would
    replay from there, forever. A `type` containing a newline would forge a
    frame boundary and desync every event after it.
    """
    seq = record.get("seq")
    # `bool` is an `int` in Python, and `True` would frame as `id: True`.
    if not isinstance(seq, int) or isinstance(seq, bool):
        return None
    name = record.get("type")
    if not isinstance(name, str) or not name or "\n" in name or "\r" in name:
        return None
    data = record.get("data")
    if data is None:
        # `JSON.parse("")` throws; `JSON.parse("{}")` does not.
        data = {}
    # `ensure_ascii=False` matches the redaction chokepoint's own encoder
    # (`redact.py:637`), so a scrubbed marker survives as the character the
    # operator sees rather than as an escape. `default=str` mirrors the sink.
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                      default=str)
    return f"id: {seq}\nevent: {name}\ndata: {body}\n\n"


def parse_record(line: str) -> dict[str, Any] | None:
    """One JSONL line as a dict, or `None` if it is not one.

    A non-object is refused as firmly as unparseable text: `[1,2,3]` has no
    `seq` to address a frame with, and treating it as a record would mean
    `.get` on a list further down.
    """
    line = line.strip()
    if not line:
        return None
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def split_lines(buffer: str) -> tuple[list[str], str]:
    """`(complete lines, the unterminated remainder)`.

    The remainder is the point. The sink line-buffers and flushes per event
    (`events.py:154`), but a reader can still arrive between the write and the
    newline. Yielding the fragment would drop that event permanently, because
    the rest of it arrives on the *next* read and would then parse as a line of
    its own. Holding it costs one partial line of memory.

    Split on `"\\n"` alone rather than `str.splitlines`, which also breaks on
    `\\v`, `\\f` and `\\x1c` — none of which can appear unescaped inside a
    `json.dumps` line, and all of which would silently tear one here.
    """
    head, sep, rest = buffer.rpartition("\n")
    if not sep:
        return [], buffer
    return head.split("\n"), rest


async def event_stream(
    path: Path,
    *,
    last_id: int = 0,
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    scrub: Callable[[Any], Any] | None = None,
) -> AsyncIterator[str]:
    """Tail *path* and yield SSE frames until one of the three stops fires.

    *last_id* is the browser's `Last-Event-ID`: records with `seq <= last_id`
    are skipped, so a reconnect resumes rather than replaying the run.

    **A missing file is not an error.** The SPA subscribes the instant the
    launch 202 lands, which is before the child has created anything; raising
    here would make every successful launch look like a failure. The file is
    reopened on each poll until it appears.

    Decoding is incremental (`codecs`), so a multi-byte character split across
    two reads is held rather than mangled — the same reasoning as the torn-line
    buffer, one level down.
    """
    path = Path(path)
    handle = None
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    buffer = ""
    idle = 0.0
    try:
        while True:
            if is_disconnected is not None and await is_disconnected():
                return

            if handle is None:
                try:
                    handle = path.open("rb")
                except OSError:
                    handle = None

            chunk = handle.read() if handle is not None else b""
            if chunk:
                idle = 0.0
                buffer += decoder.decode(chunk)
                lines, buffer = split_lines(buffer)
                for line in lines:
                    record = parse_record(line)
                    if record is None:
                        continue
                    # Read BEFORE the resume filter: a run that finished while
                    # this subscriber was away is still finished, and a stream
                    # that skipped the frame but kept waiting would sit here
                    # until the idle timeout for no reason.
                    finished = record.get("type") == _RUN_FINISHED
                    seq = record.get("seq")
                    if (isinstance(seq, int) and not isinstance(seq, bool)
                            and seq > last_id):
                        if scrub is not None:
                            # The WHOLE record, not just `data`. The event
                            # name reaches the wire too (`event: <type>`), and
                            # scrubbing only the payload left a secret in the
                            # name going out verbatim. `seq` is an int and
                            # passes through untouched, so `id:` — the resume
                            # cursor — cannot be rewritten by redaction.
                            scrubbed = scrub(record)
                            if isinstance(scrubbed, dict):
                                record = scrubbed
                        frame = sse_frame(record)
                        if frame is not None:
                            last_id = seq
                            yield frame
                    if finished:
                        return
                continue

            await asyncio.sleep(poll_interval)
            idle += poll_interval
            if idle >= idle_timeout:
                yield IDLE_COMMENT
                return
    finally:
        # Reached on `aclose()` too — i.e. when the client disconnects and the
        # ASGI server tears the generator down. Without it every abandoned
        # subscription holds a descriptor for the life of the server.
        if handle is not None:
            handle.close()
