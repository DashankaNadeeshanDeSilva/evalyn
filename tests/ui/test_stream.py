"""The SSE layer (Plan #4, Task 20).

**This is the file that can hang the suite**, so every test that waits on
anything states its own bound. Three rules hold throughout:

1. **Nothing here waits without a ceiling.** Every test that can block is
   wrapped in `asyncio.wait_for(..., WAIT_CEILING)`, so a regression that
   removes a stop condition fails in seconds with `TimeoutError` instead of
   sitting on CI for six hours.
2. **The endpoint is only ever exercised over a stream that ends by
   construction.** `httpx.ASGITransport` buffers the entire body before it
   returns a response — `handle_async_request` asserts `response_complete` is
   set — so an endpoint test over a stream that never terminates does not test
   streaming, it deadlocks. Endpoint tests therefore use a fixture already
   ending in `run.finished`, or an idle timeout measured in tenths of a second.
   The genuinely live cases are driven against the async generator directly.
3. **No `fastapi.testclient`** (it warns at import); the `asgi_client` fixture
   in `conftest.py` is the whole replacement.

The record shape being framed is the one `engine/events.py` writes:
`{"seq", "ts", "run_id", "mode", "pid", "type", "data": {...}}`.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from evalyn.ui.stream import (
    IDLE_COMMENT,
    event_stream,
    parse_record,
    split_lines,
    sse_frame,
)

#: Every awaited assertion in this file is bounded by this. Generous enough
#: that a loaded CI box does not flake, short enough that a hang is a red.
WAIT_CEILING = 10.0

#: Poll interval used by the live tests. Small, because these tests wait on it.
FAST_POLL = 0.01


def record(seq: int, type: str, **data) -> dict:  # noqa: A002 — the wire name
    """One JSONL record, shaped exactly as `JsonlSink.emit` writes it."""
    return {"seq": seq, "ts": "2026-08-11T00:00:00+00:00",
            "run_id": "20260811T000000000000-deadbeef-example",
            "mode": "gate", "pid": 4242, "type": type, "data": data}


def write_events(path: Path, records) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records),
                    encoding="utf-8")


def append_event(path: Path, rec: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec) + "\n")
        handle.flush()


FINISHED_SCRIPT = [
    record(1, "run.started", run_id="r", mode="gate", pack="example"),
    record(2, "trial.started", probe_id="grounding", epoch=1),
    record(3, "spend.updated", judge_usd=0.0137),
    record(4, "run.finished", run_id="r", exit_code=1),
]


async def drain(agen, *, ceiling: float = WAIT_CEILING) -> list[str]:
    """Every frame the generator produces, under an explicit ceiling."""
    async def _all():
        return [frame async for frame in agen]
    return await asyncio.wait_for(_all(), ceiling)


# --------------------------------------------------------------------------
# 1. `sse_frame` — pure, sync, and the only place framing is decided
# --------------------------------------------------------------------------

def test_sse_frame_puts_the_seq_in_id_the_type_in_event_and_only_data_in_data():
    """`data:` carries the payload alone, NOT the whole record.

    `ui/src/hooks/useRunEvents.ts` reads `judge_usd`, `probe_id`, `pass_k` and
    `exit_code` at the top level of the parsed `data:` body. Framing the whole
    record would put every one of them a level too deep and the live readout
    would silently show nothing at all.
    """
    frame = sse_frame(record(7, "spend.updated", judge_usd=0.25))
    assert frame == 'id: 7\nevent: spend.updated\ndata: {"judge_usd":0.25}\n\n'


def test_sse_frame_ends_every_frame_with_a_blank_line():
    """The frame separator is the protocol; without it the browser buffers."""
    frame = sse_frame(record(1, "run.started"))
    assert frame is not None
    assert frame.endswith("\n\n")
    assert frame.count("\n\n") == 1


def test_sse_frame_emits_an_object_even_when_the_record_carries_no_data():
    """`JSON.parse("")` throws; `JSON.parse("{}")` does not."""
    raw = dict(record(3, "heartbeat"))
    del raw["data"]
    assert sse_frame(raw) == "id: 3\nevent: heartbeat\ndata: {}\n\n"


def test_sse_frame_never_lets_a_payload_newline_break_the_frame():
    """A newline inside the payload would end the frame early and desync the
    stream for every event after it. `json.dumps` escapes it; this asserts
    that rather than trusting it."""
    frame = sse_frame(record(2, "turn.received", text="one\ntwo"))
    assert frame is not None
    # id, event, data, and the blank line that terminates the frame.
    assert frame.count("\n") == 4
    assert "\\n" in frame


@pytest.mark.parametrize("bad", [
    pytest.param({"type": "run.started", "data": {}}, id="no-seq"),
    pytest.param({"seq": "1", "type": "run.started", "data": {}}, id="seq-not-int"),
    pytest.param({"seq": True, "type": "run.started", "data": {}}, id="seq-is-bool"),
    pytest.param({"seq": 1, "data": {}}, id="no-type"),
    pytest.param({"seq": 1, "type": 5, "data": {}}, id="type-not-str"),
    pytest.param({"seq": 1, "type": "a\nb", "data": {}}, id="type-has-newline"),
    pytest.param({"seq": 1, "type": "a\rb", "data": {}}, id="type-has-carriage-return"),
    pytest.param({"seq": 1, "type": "", "data": {}}, id="type-is-empty"),
])
def test_sse_frame_refuses_a_record_it_cannot_address(bad):
    """`id:` IS the resume cursor. A frame without a usable one would be
    replayed forever by a reconnecting browser; a newline or carriage return in
    `event:` forges a frame boundary; and an *empty* name is the quiet one —
    SSE dispatches it as `message`, which `useRunEvents` registers no listener
    for, so the frame vanishes with nothing anywhere reporting a problem."""
    assert sse_frame(bad) is None


def test_sse_frame_passes_a_non_object_payload_through_rather_than_erasing_it():
    """A decision, pinned because a mutation survived without it.

    Every emit site writes an object today. If one ever writes a list,
    forwarding it costs the consumer nothing — `useRunEvents`' readers return
    `null` for a key that is not there either way — whereas substituting `{}`
    would silently destroy the only copy of that event's payload while looking
    entirely healthy on screen.
    """
    frame = sse_frame({"seq": 1, "type": "agent.step", "data": [1, 2]})
    assert frame == "id: 1\nevent: agent.step\ndata: [1,2]\n\n"


def test_sse_frame_survives_a_payload_json_cannot_encode():
    """`sse_frame` is exported and pure, so it is callable with a record this
    module did not read off disk. A `TypeError` raised here would propagate out
    of the tailing loop and kill a live run's readout over one odd value."""
    class Odd:
        def __repr__(self) -> str:
            return "odd-value"

    frame = sse_frame(record(1, "turn.received", thing=Odd()))
    assert frame is not None
    assert "odd-value" in frame


# --------------------------------------------------------------------------
# 2. Reading the JSONL — an unparseable line skipped, a torn line buffered
# --------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    pytest.param('{"seq": 1, "ty', id="truncated-json"),
    pytest.param("not json at all", id="not-json"),
    pytest.param("[1, 2, 3]", id="json-but-not-an-object"),
    pytest.param('"a string"', id="json-but-a-scalar"),
    pytest.param("", id="empty"),
    pytest.param("   ", id="whitespace"),
])
def test_parse_record_skips_a_line_it_cannot_read(line):
    assert parse_record(line) is None


def test_parse_record_reads_a_well_formed_line():
    assert parse_record(json.dumps(record(1, "run.started"))) == record(1, "run.started")


def test_split_lines_buffers_a_torn_trailing_line_rather_than_yielding_it():
    """The writer flushes per line but the reader can still catch a partial
    write. Yielding the fragment would drop the event when the rest arrives."""
    lines, rest = split_lines('{"a": 1}\n{"b": 2}\n{"c": ')
    assert lines == ['{"a": 1}', '{"b": 2}']
    assert rest == '{"c": '


def test_split_lines_keeps_nothing_when_the_buffer_ends_on_a_newline():
    lines, rest = split_lines('{"a": 1}\n')
    assert lines == ['{"a": 1}']
    assert rest == ""


def test_split_lines_holds_a_whole_line_that_has_not_been_terminated_yet():
    lines, rest = split_lines('{"a": 1}')
    assert lines == []
    assert rest == '{"a": 1}'


async def test_a_torn_line_is_completed_by_the_next_write_not_lost(tmp_path):
    """The end-to-end version of the buffering rule: the reader must see the
    event once, whole, after the writer finishes the line — not zero times."""
    events = tmp_path / "run.events.jsonl"
    whole = json.dumps(record(1, "run.started")) + "\n"
    events.write_text(whole[:12], encoding="utf-8")

    async def finish():
        await asyncio.sleep(0.05)
        with events.open("a", encoding="utf-8") as handle:
            handle.write(whole[12:])
            handle.flush()
        await asyncio.sleep(0.05)
        append_event(events, record(2, "run.finished", exit_code=0))

    task = asyncio.create_task(finish())
    try:
        frames = await drain(event_stream(events, idle_timeout=5.0,
                                          poll_interval=FAST_POLL))
    finally:
        await task
    assert [f.split("\n")[0] for f in frames] == ["id: 1", "id: 2"]


async def test_an_unparseable_line_does_not_stop_the_events_after_it(tmp_path):
    """One corrupt line is one event's worth of detail lost, never the rest of
    a live run's readout."""
    events = tmp_path / "run.events.jsonl"
    events.write_text(
        json.dumps(record(1, "run.started")) + "\n"
        + "{ this is not json\n"
        + json.dumps(record(3, "run.finished", exit_code=0)) + "\n",
        encoding="utf-8")
    frames = await drain(event_stream(events, poll_interval=FAST_POLL))
    assert [f.split("\n")[0] for f in frames] == ["id: 1", "id: 3"]


async def test_a_multibyte_character_split_across_two_reads_is_not_mangled(tmp_path):
    """The torn-line rule, one level down, at the byte boundary.

    The sink escapes non-ASCII (`json.dumps` with the default
    `ensure_ascii=True`), so today's engine cannot produce this — but
    `event_stream` tails a plain file that a human can edit and a future sink
    could write differently, and a per-chunk `bytes.decode` would substitute a
    replacement character permanently rather than waiting for the rest.
    """
    events = tmp_path / "run.events.jsonl"
    line = (json.dumps(record(1, "turn.received", text="café ☕"),
                       ensure_ascii=False) + "\n").encode("utf-8")
    cut = line.index("☕".encode("utf-8")) + 1        # mid-sequence
    events.write_bytes(line[:cut])

    async def finish():
        await asyncio.sleep(0.05)
        with events.open("ab") as handle:
            handle.write(line[cut:])
            handle.flush()
        await asyncio.sleep(0.05)
        with events.open("ab") as handle:
            handle.write((json.dumps(record(2, "run.finished", exit_code=0))
                          + "\n").encode("utf-8"))
            handle.flush()

    task = asyncio.create_task(finish())
    try:
        frames = await drain(event_stream(events, idle_timeout=5.0,
                                          poll_interval=FAST_POLL))
    finally:
        await task
    assert "☕" in frames[0]
    assert "�" not in frames[0]


# --------------------------------------------------------------------------
# 3. Replay-only — cannot hang by construction (the fixture ends finished)
# --------------------------------------------------------------------------

async def test_a_repeated_or_backwards_seq_is_delivered_only_once(tmp_path):
    """The cursor advances as frames go out, not only at subscription.

    `JsonlSink._check_owner` refuses to let two processes share one stream, but
    it fails soft on a file it cannot read. If that guard ever gives way, the
    file carries duplicate and out-of-order seqs — and the consumer's fold
    counts `seq` gaps as *lost frames*, so re-delivery would be reported to the
    operator as a run that lost events it never lost.
    """
    events = tmp_path / "run.events.jsonl"
    write_events(events, [
        record(1, "run.started"),
        record(2, "trial.started", epoch=1),
        record(1, "run.started"),                    # a duplicate
        record(2, "trial.started", epoch=1),         # and a backwards step
        record(3, "run.finished", exit_code=0),
    ])
    frames = await drain(event_stream(events, poll_interval=FAST_POLL))
    assert [f.split("\n")[0] for f in frames] == ["id: 1", "id: 2", "id: 3"]

async def test_replay_of_a_finished_stream_returns_every_frame_in_order(tmp_path):
    events = tmp_path / "run.events.jsonl"
    write_events(events, FINISHED_SCRIPT)
    frames = await drain(event_stream(events, poll_interval=FAST_POLL))
    assert [f.split("\n")[0] for f in frames] == ["id: 1", "id: 2", "id: 3", "id: 4"]
    assert frames[-1].startswith("id: 4\nevent: run.finished\n")


async def test_run_finished_stops_the_stream_even_when_more_events_follow(tmp_path):
    """`run.finished` is terminal. Anything after it in the file belongs to a
    stream this build should not be reading, and continuing would keep a
    finished run's socket open forever."""
    events = tmp_path / "run.events.jsonl"
    write_events(events, [*FINISHED_SCRIPT, record(5, "spend.updated", judge_usd=9.0)])
    frames = await drain(event_stream(events, poll_interval=FAST_POLL))
    assert len(frames) == 4
    assert "id: 5" not in "".join(frames)


async def test_last_event_id_resumes_after_the_seq_it_names(tmp_path):
    """`Last-Event-ID: 2` must resume at 3, not replay from 1 — otherwise
    every browser reconnect re-delivers the whole run."""
    events = tmp_path / "run.events.jsonl"
    write_events(events, FINISHED_SCRIPT)
    frames = await drain(event_stream(events, last_id=2, poll_interval=FAST_POLL))
    assert [f.split("\n")[0] for f in frames] == ["id: 3", "id: 4"]


async def test_a_last_event_id_past_a_finished_run_closes_without_replaying(tmp_path):
    """A reconnect after the end must close, not idle.

    Every frame is skipped by the resume cursor, so nothing is emitted — but
    the file still says the run finished, and that is a reason to close. The
    idle timeout here is an hour: this test cannot pass by waiting.
    """
    events = tmp_path / "run.events.jsonl"
    write_events(events, FINISHED_SCRIPT)
    frames = await drain(event_stream(events, last_id=99, idle_timeout=3600.0,
                                      poll_interval=FAST_POLL))
    assert frames == []


async def test_a_missing_events_file_is_not_an_error(tmp_path):
    """The SPA subscribes the instant the 202 lands — before the child has
    created anything. A stream that raised here would make every launch look
    like a failure."""
    frames = await drain(event_stream(tmp_path / "absent.events.jsonl",
                                      idle_timeout=0.2, poll_interval=FAST_POLL))
    assert frames == [IDLE_COMMENT]


async def test_a_file_that_appears_after_subscription_is_picked_up(tmp_path):
    """The launch-then-subscribe race, driven directly."""
    events = tmp_path / "late.events.jsonl"

    async def create_later():
        await asyncio.sleep(0.05)
        write_events(events, [record(1, "run.started"),
                              record(2, "run.finished", exit_code=0)])

    task = asyncio.create_task(create_later())
    try:
        frames = await drain(event_stream(events, idle_timeout=5.0,
                                          poll_interval=FAST_POLL))
    finally:
        await task
    assert [f.split("\n")[0] for f in frames] == ["id: 1", "id: 2"]


# --------------------------------------------------------------------------
# 4. Live tail — three independent stops
# --------------------------------------------------------------------------

async def test_live_tail_delivers_events_as_they_are_appended(tmp_path):
    """Stop #1: `run.finished`. A writer appends on delays while the reader is
    already blocked, which is the only shape that proves the reader is
    tailing rather than reading the file once at open."""
    events = tmp_path / "run.events.jsonl"
    events.write_text("", encoding="utf-8")

    async def writer():
        for rec in [record(1, "run.started"),
                    record(2, "trial.started", probe_id="p", epoch=1),
                    record(3, "run.finished", exit_code=0)]:
            await asyncio.sleep(0.05)
            append_event(events, rec)

    task = asyncio.create_task(writer())
    try:
        frames = await drain(event_stream(events, idle_timeout=5.0,
                                          poll_interval=FAST_POLL))
    finally:
        await task
    assert [f.split("\n")[0] for f in frames] == ["id: 1", "id: 2", "id: 3"]


async def test_the_idle_timeout_emits_a_comment_and_returns(tmp_path):
    """Stop #2: a run that goes quiet must not hold the socket forever.

    The comment is an SSE comment, not an event: it carries no `id:`, so it
    cannot advance the browser's resume cursor or be read as a gap.
    """
    events = tmp_path / "run.events.jsonl"
    write_events(events, [record(1, "run.started")])
    frames = await drain(event_stream(events, idle_timeout=0.2,
                                      poll_interval=FAST_POLL))
    assert frames[-1] == IDLE_COMMENT
    assert IDLE_COMMENT.startswith(":")
    assert "id:" not in IDLE_COMMENT
    assert IDLE_COMMENT.endswith("\n\n")


async def test_the_idle_timeout_is_measured_from_the_last_event_not_from_open(tmp_path):
    """A stream still producing events must never time out. If the clock were
    not reset on each event, a run longer than the timeout would be cut off
    mid-flight — a live eval truncated on screen."""
    events = tmp_path / "run.events.jsonl"
    events.write_text("", encoding="utf-8")

    async def writer():
        for seq in (1, 2, 3):
            await asyncio.sleep(0.12)
            append_event(events, record(seq, "trial.started", epoch=seq))
        await asyncio.sleep(0.12)
        append_event(events, record(4, "run.finished", exit_code=0))

    task = asyncio.create_task(writer())
    try:
        # Each gap (0.12 s) sits UNDER the idle timeout (0.2 s), while the whole
        # run (~0.48 s) runs well past it. Only a clock that fails to reset on
        # each event can fire here.
        frames = await drain(event_stream(events, idle_timeout=0.2,
                                          poll_interval=FAST_POLL))
    finally:
        await task
    assert [f.split("\n")[0] for f in frames] == ["id: 1", "id: 2", "id: 3", "id: 4"]
    assert IDLE_COMMENT not in frames


# --------------------------------------------------------------------------
# 5. Early client disconnect — the path that leaks in production
# --------------------------------------------------------------------------

async def test_closing_the_generator_early_releases_the_file_handle(tmp_path, monkeypatch):
    """The leak, made observable.

    A browser tab closing mid-run is `aclose()` on the generator. Without a
    `finally` that closes the handle, every abandoned subscription holds an
    open descriptor for the life of the server — and on a long demo that is a
    descriptor per reload.
    """
    events = tmp_path / "run.events.jsonl"
    write_events(events, [record(1, "run.started")])

    # Recorded by patching `Path.open` rather than by a seam in the signature:
    # a production parameter that exists only for this assertion is a worse
    # defect than the leak it observes.
    opened: list = []
    real_open = Path.open

    def recording_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        if self == events:
            opened.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", recording_open)
    agen = event_stream(events, idle_timeout=5.0, poll_interval=FAST_POLL)
    first = await asyncio.wait_for(agen.__anext__(), WAIT_CEILING)
    assert first.startswith("id: 1")
    assert opened and not opened[0].closed
    await asyncio.wait_for(agen.aclose(), WAIT_CEILING)
    assert opened[0].closed


async def test_a_disconnected_client_stops_the_stream_before_the_idle_timeout(tmp_path):
    """Stop #3, and the one that matters in production.

    Starlette only notices a dead client when it next tries to *write*. A run
    that goes quiet writes nothing, so without an explicit disconnect check the
    task survives until the idle timeout — one leaked task per abandoned tab.
    The timeout here is set far beyond the test's own ceiling on purpose: if
    the disconnect check is dropped, this test cannot pass by waiting.
    """
    events = tmp_path / "run.events.jsonl"
    write_events(events, [record(1, "run.started")])
    gone = False

    async def is_disconnected() -> bool:
        return gone

    agen = event_stream(events, idle_timeout=3600.0, poll_interval=FAST_POLL,
                        is_disconnected=is_disconnected)
    first = await asyncio.wait_for(agen.__anext__(), WAIT_CEILING)
    assert first.startswith("id: 1")
    gone = True
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(agen.__anext__(), WAIT_CEILING)


async def test_a_connected_client_is_not_mistaken_for_a_disconnected_one(tmp_path):
    """The discriminator for the test above: a check that always returned
    `True` would make it pass while killing every live stream."""
    events = tmp_path / "run.events.jsonl"
    write_events(events, FINISHED_SCRIPT)

    async def is_disconnected() -> bool:
        return False

    frames = await drain(event_stream(events, poll_interval=FAST_POLL,
                                      is_disconnected=is_disconnected))
    assert len(frames) == 4


# --------------------------------------------------------------------------
# 6. Redaction — the chokepoint declines to cover a StreamingResponse
# --------------------------------------------------------------------------

async def test_the_stream_scrubs_its_payloads_itself(tmp_path):
    """`redact.py:626-628` returns a `StreamingResponse` untouched: "streaming,
    file, or empty: not ours". So the one route that is on screen during a live
    run is the one route the chokepoint skips, and the stream must scrub for
    itself or a `not_contains` secret reaches the projector.
    """
    events = tmp_path / "run.events.jsonl"
    write_events(events, [record(1, "turn.received", text="the SECRET value"),
                          record(2, "run.finished", exit_code=0)])

    def scrub(payload):
        return json.loads(json.dumps(payload).replace("SECRET", "«redacted»"))

    frames = await drain(event_stream(events, poll_interval=FAST_POLL, scrub=scrub))
    assert "SECRET" not in "".join(frames)
    assert "«redacted»" in frames[0]
