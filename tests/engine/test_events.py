"""Task 18 step 1: the sink itself.

What is pinned here is the contract a live tail depends on — a strictly
increasing `seq` whose order matches the file's, a reader that survives being
mid-write, an `emit` that swallows I/O failure with a `UserWarning` (never a
`RuntimeWarning`: the suite runs `-W error::RuntimeWarning` and telemetry must
never kill a paid run), and a refusal to let two processes share one stream.

The no-op guarantees — the ones that protect the shipping gate path — live next
door in `test_events_noop.py`.
"""
from __future__ import annotations

import json
import os
import re
import threading
import warnings
from pathlib import Path

import pytest

from evalyn.engine.events import (
    EVENT_NAMES,
    NULL_SINK,
    JsonlSink,
    NullSink,
    hunt_key,
    read_events,
    trial_key,
)
from evalyn.engine.run import new_run_id

SRC = Path(__file__).resolve().parents[2] / "src" / "evalyn"


@pytest.fixture
def sink(tmp_path):
    s = JsonlSink(tmp_path / "r.events.jsonl", run_id=new_run_id("t"), mode="gate")
    yield s
    s.close()


# --------------------------------------------------------------------- seq

def test_seq_starts_at_one_and_increments(sink):
    sink.emit("run.started", probes=3)
    sink.emit("run.finished", status="ok")
    assert [e["seq"] for e in read_events(sink.path)] == [1, 2]


def test_seq_is_contiguous_and_file_order_equals_seq_order_across_threads(sink):
    """8 threads x 50 emits: 400 unique contiguous seqs, in file order.

    Uniqueness alone is not the contract. A counter bumped under one lock and a
    write done under another yields unique seqs written out of order — which a
    tailing reader renders as events arriving backwards. The second assertion
    is the one that catches it.
    """
    barrier = threading.Barrier(8)

    def worker(n: int) -> None:
        barrier.wait(timeout=10)  # maximise real contention; never hang
        for i in range(50):
            sink.emit("turn.sent", worker=n, i=i)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "an emitting thread hung — the lock deadlocked"

    seqs = [e["seq"] for e in read_events(sink.path)]
    assert len(seqs) == 400
    assert len(set(seqs)) == 400, "seqs collided under concurrency"
    assert seqs == sorted(seqs) == list(range(1, 401)), (
        "file order does not equal seq order — the increment and the write are "
        "not in one critical section")


# ------------------------------------------------------------------ reader

def test_reader_skips_a_torn_trailing_line(sink):
    sink.emit("run.started")
    sink.emit("run.finished")
    # exactly what a tail sees when it catches a writer mid-flush
    with open(sink.path, "a", encoding="utf-8") as f:
        f.write('{"seq": 3, "ts": "2026-08-11T00:00:0')

    events = read_events(sink.path)
    assert [e["type"] for e in events] == ["run.started", "run.finished"]


def test_reader_returns_empty_for_a_missing_file(tmp_path):
    assert read_events(tmp_path / "nope.events.jsonl") == []


# ---------------------------------------------------------------- envelope

def test_envelope_carries_run_id_mode_pid_and_nests_caller_fields(tmp_path):
    rid = new_run_id("t")
    s = JsonlSink(tmp_path / "r.events.jsonl", run_id=rid, mode="discover")
    s.emit("agent.step", hunt_key=hunt_key("obj", "persona"), step=2)
    s.close()

    [e] = read_events(tmp_path / "r.events.jsonl")
    assert e["run_id"] == rid and e["mode"] == "discover" and e["type"] == "agent.step"
    assert isinstance(e["pid"], int) and e["ts"]
    # caller fields are nested, so a field named `type` or `seq` cannot shadow
    # the envelope
    assert e["data"] == {"hunt_key": "obj::persona", "step": 2}


def test_caller_field_named_type_cannot_shadow_the_envelope(sink):
    sink.emit("probe.scored", type="not-an-event-name", seq=999)
    [e] = read_events(sink.path)
    assert e["type"] == "probe.scored" and e["seq"] == 1
    assert e["data"] == {"type": "not-an-event-name", "seq": 999}


def test_unserialisable_field_does_not_kill_the_run(sink):
    sink.emit("probe.scored", path=Path("/tmp/x"))  # default=str
    [e] = read_events(sink.path)
    assert e["data"]["path"] == "/tmp/x"


def test_keys(tmp_path):
    assert trial_key("p1", 3) == "p1#3"
    assert hunt_key("prompt-injection-bypass", "curious-user") == \
        "prompt-injection-bypass::curious-user"


# ------------------------------------------------------------ failure modes

class _BrokenFile:
    """A file handle whose every write fails, as a full disk would."""

    def write(self, _data):
        raise OSError(28, "No space left on device")

    def flush(self):
        raise OSError(28, "No space left on device")

    def close(self):
        return None


def test_emit_swallows_oserror_warns_userwarning_once_then_self_demotes(sink):
    sink._fh = _BrokenFile()

    # UserWarning, NEVER RuntimeWarning: the suite runs -W error::RuntimeWarning
    # and a full disk must not abort a run that is spending money (R4-44).
    with pytest.warns(UserWarning, match="event stream .* failed"):
        sink.emit("run.started")

    # Self-demoted: silent AND non-raising for the rest of the run. `simplefilter
    # ("error")` is the negative assertion (a second warning would raise here) —
    # `pytest.warns` has no "nothing warned" form, and the house rule bans
    # `catch_warnings(record=True)`.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for _ in range(5):
            sink.emit("turn.sent")


def test_a_demoted_sink_is_silent_but_still_closeable(sink):
    sink._fh = _BrokenFile()
    with pytest.warns(UserWarning):
        sink.emit("run.started")
    sink.close()
    sink.close()  # idempotent


def test_emit_after_close_is_a_no_op(tmp_path):
    s = JsonlSink(tmp_path / "r.events.jsonl", run_id=new_run_id("t"), mode="gate")
    s.emit("run.started")
    s.close()
    s.emit("run.finished")
    assert [e["type"] for e in read_events(s.path)] == ["run.started"]


# ------------------------------------------------------------- construction

def test_reopening_a_stream_written_by_another_pid_raises(tmp_path):
    path = tmp_path / "r.events.jsonl"
    path.write_text(json.dumps({
        "seq": 1, "ts": "2026-08-11T00:00:00+00:00", "run_id": new_run_id("t"),
        "mode": "gate", "pid": os.getpid() + 1, "type": "run.started",
        "data": {}}) + "\n")

    with pytest.raises(ValueError, match="already being written by pid"):
        JsonlSink(path, run_id=new_run_id("t"), mode="gate")


def test_reopening_in_the_same_process_appends(tmp_path):
    rid = new_run_id("t")
    a = JsonlSink(tmp_path / "r.events.jsonl", run_id=rid, mode="gate")
    a.emit("run.started")
    a.close()
    b = JsonlSink(tmp_path / "r.events.jsonl", run_id=rid, mode="gate")
    b.emit("run.finished")
    b.close()
    assert [e["type"] for e in read_events(tmp_path / "r.events.jsonl")] == [
        "run.started", "run.finished"]


def test_construction_creates_missing_parent_directories(tmp_path):
    s = JsonlSink(tmp_path / "deep" / "er" / "r.events.jsonl",
                  run_id=new_run_id("t"), mode="gate")
    s.emit("run.started")
    s.close()
    assert (tmp_path / "deep" / "er" / "r.events.jsonl").is_file()


def test_a_bad_run_id_is_refused_at_construction(tmp_path):
    with pytest.raises(ValueError, match="not a run_id"):
        JsonlSink(tmp_path / "r.events.jsonl", run_id="../escape", mode="gate")


def test_a_bad_mode_is_refused_at_construction(tmp_path):
    with pytest.raises(ValueError, match="not a run mode"):
        JsonlSink(tmp_path / "r.events.jsonl", run_id=new_run_id("t"), mode="calibrate")


# ------------------------------------------------------- the null sink

def test_null_sink_is_a_singleton_that_does_nothing():
    assert isinstance(NULL_SINK, NullSink)
    assert NULL_SINK.emit("run.started", anything=object()) is None
    assert NULL_SINK.close() is None


# ------------------------------------------- every emitted name is contracted

INSTRUMENTED = [
    "engine/run.py", "engine/solver.py", "engine/task_builder.py",
    "engine/compare.py", "discovery/run.py", "discovery/solver.py",
    "discovery/loop.py", "discovery/task_builder.py", "cli.py",
]
_EMIT_RE = re.compile(r"""\.emit\(\s*["']([^"']+)["']""")


def test_every_emitted_event_name_is_in_the_frozen_contract():
    """A typo'd event name is invisible at runtime — the SPA just ignores it.

    So the check is source-level: every literal handed to `.emit(...)` anywhere
    in the instrumented engine must be an `EventName` (R4-7). This also fails
    if someone adds an emit site with a name nobody taught the cockpit.
    """
    emitted: dict[str, set[str]] = {}
    for rel in INSTRUMENTED:
        text = (SRC / rel).read_text(encoding="utf-8")
        for name in _EMIT_RE.findall(text):
            emitted.setdefault(name, set()).add(rel)
    assert emitted, "found no emit sites at all — the regex or the paths are stale"
    unknown = {n: sorted(f) for n, f in emitted.items() if n not in EVENT_NAMES}
    assert not unknown, f"event names absent from ui.models.EventName: {unknown}"
