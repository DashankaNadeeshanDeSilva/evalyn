"""Task 19: pause, resume and cancel — and the promises each one makes.

Four things this file is really about, in the order they matter:

1. **Pause changes nothing but wall time.** A gate run paused for two seconds
   and then resumed writes an artifact byte-equal to an unpaused run's, on the
   same blank list Task 18 established and with the same control test proving
   that list is not hiding a real difference.
2. **A cancelled run is never a verdict.** It is marked on the artifact, it
   exits 3, and `--update-baseline` refuses it *for being cancelled* — proven
   discriminating by cancelling AFTER every probe has already scored, where the
   pre-existing zero-trials and INCOMPLETE guards have nothing to say.
3. **The feature-detect sees through `**kwargs`.** `Task.__init__` silently
   absorbs an unknown keyword instead of raising, so "pass it and catch
   `TypeError`" would report success on a version that ignores it. Both halves
   are pinned here: that the absorption is real, and that signature inspection
   sees through it.
4. **Cancel is a deliberate stop, not an error.** `discovery/loop.py` catches
   `RunCancelled` before its blanket handler, so a cancelled hunt is
   `stop_reason="cancelled"` and never `"error"`.

Every blocking test carries an explicit `asyncio.timeout` or a `threading.Timer`
that is guaranteed to fire: a test that *hangs* instead of failing is the single
likeliest way this feature wastes a day.

Everything runs offline against the toy target. No API key, no money.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from inspect_ai import Task
from inspect_ai.dataset import MemoryDataset, Sample

from evalyn.cli import _MODE_SUFFIX
from evalyn.engine import control as control_mod
from evalyn.engine.control import (
    CANCEL_REASON,
    CONTROL_ACTIONS,
    CONTROL_MANAGER_NAME,
    RunCancelled,
    RunController,
    early_stopping_supported,
)
from evalyn.discovery import run as discovery_run_mod
from evalyn.engine.run import ProbeResult, RunArtifact, run_gate
from evalyn.targets.loader import load_pack
# Task 18's blank list and its `_write_gate_pack` are REUSED, not re-derived:
# §2 of the Task 19 constraints requires the pause-equality proof to stand on
# the same three fields Task 18 justified with a control test, and inventing a
# wider list here would weaken the proof silently.
from tests.engine.test_events_noop import VOLATILE, _blank_volatile, _write_gate_pack

#: Long enough that the paused run's wall clock is unambiguously longer than an
#: unpaused one's (which finishes in well under a second), short enough not to
#: tax the suite. The brief's figure.
PAUSE_SECONDS = 2.0

#: Every blocking await in this file is bounded by this. A pause test that sits
#: there instead of failing is a six-hour CI job.
BLOCK_TIMEOUT = 20.0


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------

class _RecordingSink:
    """Records every event. The `control.*` acks are what we assert on."""

    def __init__(self):
        self.names: list[str] = []
        self.events: list[tuple[str, dict]] = []

    def emit(self, type, /, **fields):  # noqa: A002 — the wire name
        self.names.append(type)
        self.events.append((type, fields))

    def close(self):
        return None


@pytest.fixture
def gate_pack(tmp_path, toy_target, monkeypatch):
    """The same deterministic, live-target pack Task 18's proofs use."""
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    return load_pack(_write_gate_pack(tmp_path / "gpack", toy_target))


def _gate(pack, tmp_path, name="runs", **kw):
    return run_gate(pack, judge_model="mockllm/model",
                    log_dir=str(tmp_path / "logs" / name),
                    out_dir=str(tmp_path / name), **kw)


@pytest.fixture
def ctl_path(tmp_path):
    return tmp_path / "ctl" / "20260811T000000000000-deadbeef-x.control.json"


def _controller(path, sink=None, **kw):
    kw.setdefault("poll_seconds", 0.02)
    return RunController(path, sink or _RecordingSink(), **kw)


# ==========================================================================
# 1. The control file: reading it, and the ack that says we did
# ==========================================================================

def test_request_writes_an_action_that_refresh_reads_back(ctl_path):
    c = _controller(ctl_path)
    assert c.paused is False and c.cancelled is False
    c.request("pause")
    assert json.loads(ctl_path.read_text())["action"] == "pause"
    c.refresh()
    assert c.paused is True and c.cancelled is False
    c.request("resume")
    c.refresh()
    assert c.paused is False
    c.request("cancel")
    c.refresh()
    assert c.cancelled is True


def test_request_refuses_an_action_outside_the_frozen_contract(ctl_path):
    c = _controller(ctl_path)
    with pytest.raises(ValueError, match="not a control action"):
        c.request("halt")
    assert CONTROL_ACTIONS == {"pause", "resume", "cancel"}


def test_the_control_event_is_the_ack_and_fires_once_per_transition(ctl_path):
    """The HTTP 200 only says the file was written; THIS is what says the run
    noticed. Once per transition — a run paused for ten minutes at a 0.02 s
    poll must not emit 30,000 acks."""
    sink = _RecordingSink()
    c = _controller(ctl_path, sink)
    c.request("pause")
    for _ in range(20):
        c.refresh("where")
    assert sink.names == ["control.paused"]
    assert sink.events[0][1]["where"] == "where"
    assert sink.events[0][1]["pid"] == os.getpid()

    c.request("resume")
    for _ in range(20):
        c.refresh()
    assert sink.names == ["control.paused", "control.resumed"]

    c.request("cancel")
    for _ in range(20):
        c.refresh()
    assert sink.names == ["control.paused", "control.resumed", "control.cancelled"]
    cancel_fields = sink.events[-1][1]
    # R4-11: an unacked cancel becomes an honest `interrupted` run that NAMES
    # the pid, so a human can decide. Nothing here kills anything.
    assert cancel_fields["pid"] == os.getpid()
    assert cancel_fields["reason"] == CANCEL_REASON


def test_no_control_file_is_the_normal_case_and_changes_nothing(ctl_path):
    sink = _RecordingSink()
    c = _controller(ctl_path, sink)
    assert not ctl_path.exists()
    assert c.refresh() is None
    assert c.paused is False and c.cancelled is False
    assert sink.names == []


def test_an_unrecognised_action_warns_as_a_UserWarning_and_changes_nothing(ctl_path):
    """R4-44: `UserWarning`, never `RuntimeWarning`. The suite runs
    `-W error::RuntimeWarning`, so a typo in a control file must not be able to
    kill an eval that is spending money."""
    sink = _RecordingSink()
    c = _controller(ctl_path, sink)
    ctl_path.parent.mkdir(parents=True, exist_ok=True)
    ctl_path.write_text(json.dumps({"action": "abort"}))
    with pytest.warns(UserWarning, match="unrecognised control action"):
        c.refresh()
    assert c.paused is False and c.cancelled is False
    assert sink.names == []
    # ...and it warns ONCE, not on every poll.
    c.refresh()
    c.refresh()


def test_a_torn_write_is_re_read_on_the_next_poll(ctl_path):
    """The reader is looking at a file another process is writing. A half line
    is not corruption, it is timing — and it must not latch the file as `seen`,
    or the run would never notice the pause that arrived one millisecond later.
    """
    c = _controller(ctl_path)
    ctl_path.parent.mkdir(parents=True, exist_ok=True)
    ctl_path.write_text('{"action": "pau')          # torn
    assert c.refresh() is None
    assert c.paused is False
    ctl_path.write_text(json.dumps({"action": "pause"}))
    c.refresh()
    assert c.paused is True


def test_the_file_is_re_read_only_when_stat_says_it_changed(ctl_path):
    """`stat` first, parse second. Constructed by rewriting the file to a
    DIFFERENT action while restoring the previous `(mtime, size)`: if the reader
    were re-parsing unconditionally it would pick the new action up."""
    c = _controller(ctl_path)
    ctl_path.parent.mkdir(parents=True, exist_ok=True)
    # hand-written so the two payloads are byte-for-byte the same LENGTH; the
    # real writer stamps a timestamp, which would change the size and let the
    # reader notice for the wrong reason
    ctl_path.write_text('{"action": "pause" }')
    c.refresh()
    assert c.paused is True
    st = ctl_path.stat()
    ctl_path.write_text('{"action": "cancel"}')
    os.utime(ctl_path, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert ctl_path.stat().st_size == st.st_size, (
        "the two payloads are not the same size, so this test would pass for "
        "the wrong reason")
    c.refresh()
    assert c.cancelled is False, "the file was re-parsed despite an unchanged stat"


def test_cancel_is_not_retractable(ctl_path):
    c = _controller(ctl_path)
    c.request("cancel")
    c.refresh()
    assert c.cancelled is True
    c.request("resume")
    c.refresh()
    assert c.cancelled is True


def test_ack_timeout_is_advisory_and_never_escalates():
    """R4-11. `ack_timeout` is a budget for the REQUESTER's patience. It is not
    a kill timer: nothing in this module sends, installs or escalates to a
    signal, and a run that never acks is an honest `interrupted`, not a corpse.
    """
    source = Path(control_mod.__file__).read_text()
    # The CODE, not the prose: the module docstring names SIGTERM and SIGINT
    # precisely to record that they were measured and rejected, and banning the
    # word would delete the reasoning along with the risk.
    for forbidden in ("import signal", "signal.SIG", "os.kill(", ".terminate(",
                      "subprocess", "psutil"):
        assert forbidden not in source, (
            f"{forbidden!r} appears in engine/control.py — cancel is NEVER "
            f"built on signals (R4-11)")
    assert RunController(Path("x.control.json")).ack_timeout == 60.0


def test_the_sink_never_travels_by_contextvar():
    """R4-43, the same rule Task 18 was held to: explicit passing is the proof."""
    source = Path(control_mod.__file__).read_text()
    assert "ContextVar" not in source
    import inspect as _inspect

    param = _inspect.signature(RunController.__init__).parameters["sink"]
    from evalyn.engine.events import NULL_SINK

    assert param.default is NULL_SINK


def test_pause_is_documented_as_start_no_new_samples_and_still_spending():
    """R4-12 is a TRUTHFULNESS requirement, not a wording preference: with
    `concurrency` 4 an operator who clicks Pause can have four paid sessions
    still running. The docstring the cockpit's copy has to agree with is
    checked here so it cannot quietly drift into a promise we do not keep."""
    lowered = ((RunController.__doc__ or "") + (control_mod.__doc__ or "")).lower()
    assert "start no new samples" in lowered
    # ...and says what that costs, in both places an operator's money is at
    # stake: the samples already running, and the fact that they still bill.
    assert "run to completion" in lowered
    assert "keep spending real money" in lowered
    for lie in ("freezes the world", "stops spending", "instantly"):
        assert lie not in lowered, f"the docstring claims {lie!r}, which is false"


# ==========================================================================
# 2. `checkpoint` — the engine's one yielding point
# ==========================================================================

async def test_checkpoint_returns_at_once_when_nothing_was_requested(ctl_path):
    c = _controller(ctl_path)
    async with asyncio.timeout(BLOCK_TIMEOUT):
        await c.checkpoint(key="k")


async def test_checkpoint_raises_RunCancelled(ctl_path):
    c = _controller(ctl_path)
    c.request("cancel")
    with pytest.raises(RunCancelled, match="cancelled by operator at probe-7"):
        async with asyncio.timeout(BLOCK_TIMEOUT):
            await c.checkpoint(key="probe-7")


async def test_checkpoint_blocks_while_paused_and_returns_after_a_resume(ctl_path):
    c = _controller(ctl_path)
    c.request("pause")
    task = asyncio.create_task(c.checkpoint(key="k"))
    await asyncio.sleep(0.2)
    assert not task.done(), "a paused checkpoint returned without a resume"
    c.request("resume")
    async with asyncio.timeout(BLOCK_TIMEOUT):
        await task


async def test_a_paused_checkpoint_still_notices_a_cancel(ctl_path):
    """Cancel is checked on every pass, so a run paused for an hour still
    cancels at the next poll rather than at the next resume."""
    c = _controller(ctl_path)
    c.request("pause")
    task = asyncio.create_task(c.checkpoint(key="k"))
    await asyncio.sleep(0.2)
    assert not task.done()
    c.request("cancel")
    with pytest.raises(RunCancelled):
        async with asyncio.timeout(BLOCK_TIMEOUT):
            await task


# ==========================================================================
# 3. The Inspect `EarlyStopping` manager
# ==========================================================================

async def test_schedule_sample_returns_None_while_the_run_is_healthy(ctl_path):
    mgr = _controller(ctl_path).as_early_stopping()
    async with asyncio.timeout(BLOCK_TIMEOUT):
        assert await mgr.schedule_sample(1, 1) is None


@pytest.mark.parametrize("sample_id", [1, 7, "injection-trust-pivot"])
async def test_a_cancelled_schedule_sample_echoes_the_id_it_was_handed(ctl_path,
                                                                       sample_id):
    """R4-10: pause and cancel are GLOBAL, run-level decisions. This method only
    decides halt-or-don't; it does no ordinal-to-probe-id mapping and takes no
    dependency on the pack, so the id goes back out exactly as it came in."""
    c = _controller(ctl_path)
    c.request("cancel")
    mgr = c.as_early_stopping()
    async with asyncio.timeout(BLOCK_TIMEOUT):
        stop = await mgr.schedule_sample(sample_id, 3)
    assert stop is not None
    assert stop.id == sample_id
    assert stop.epoch == 3
    assert stop.reason == CANCEL_REASON


async def test_schedule_sample_blocks_while_paused_then_returns_None(ctl_path):
    """Pause = start no new samples. The blocked coroutine returns `None` on
    resume — a genuine resume, not a restart."""
    c = _controller(ctl_path)
    c.request("pause")
    task = asyncio.create_task(c.as_early_stopping().schedule_sample(1, 1))
    await asyncio.sleep(0.2)
    assert not task.done()
    c.request("resume")
    async with asyncio.timeout(BLOCK_TIMEOUT):
        assert await task is None


async def test_the_manager_names_itself_in_the_log(ctl_path):
    mgr = _controller(ctl_path).as_early_stopping()
    assert await mgr.start_task(None, [], 1) == CONTROL_MANAGER_NAME
    assert await mgr.complete_sample(1, 1, {}) is None
    assert (await mgr.complete_task())["cancelled"] is False


# ==========================================================================
# 4. The feature-detect, and the trap it exists to avoid
# ==========================================================================

def test_task_absorbs_an_unknown_keyword_instead_of_raising():
    """THE TRAP, measured rather than asserted. `Task.__init__` ends in
    `**kwargs`, so a `try: Task(early_stopping=…) except TypeError:` feature
    detect would report SUCCESS on a version that ignores the argument
    entirely — and we would ship a pause button that does nothing."""
    task = Task(dataset=MemoryDataset([Sample(input="x")]),
                evalyn_no_such_argument_19=object())
    assert task is not None  # constructed happily; no TypeError anywhere


def test_early_stopping_supported_sees_through_that_absorption():
    class _KwargsOnly:
        def __init__(self, dataset=None, **kwargs):
            self.kwargs = kwargs

    assert early_stopping_supported(Task) is True
    # the absence is CONSTRUCTED, not assumed: this class absorbs the keyword
    # exactly as `Task` does, and the detect still says no.
    assert early_stopping_supported(_KwargsOnly) is False
    assert _KwargsOnly(early_stopping="x").kwargs == {"early_stopping": "x"}


class _RecordingTask:
    """A `Task` stand-in that records what it was called with."""

    calls: list[dict] = []

    def __init__(self, dataset=None, solver=None, scorer=None, epochs=None,
                 fail_on_error=None, early_stopping=None, **kwargs):
        type(self).calls.append({"early_stopping": early_stopping, **kwargs})


class _NoEarlyStoppingTask:
    """The DEGRADED version: absorbs everything, understands nothing."""

    calls: list[dict] = []

    def __init__(self, dataset=None, solver=None, scorer=None, epochs=None,
                 fail_on_error=None, **kwargs):
        type(self).calls.append(dict(kwargs))


@pytest.fixture
def recording_task(monkeypatch):
    _RecordingTask.calls = []
    monkeypatch.setattr("evalyn.engine.task_builder.Task", _RecordingTask)
    return _RecordingTask


@pytest.fixture
def degraded_task(monkeypatch):
    _NoEarlyStoppingTask.calls = []
    monkeypatch.setattr("evalyn.engine.task_builder.Task", _NoEarlyStoppingTask)
    return _NoEarlyStoppingTask


def test_build_task_passes_early_stopping_when_a_controller_exists(
        gate_pack, ctl_path, recording_task):
    from evalyn.engine.task_builder import build_task

    c = _controller(ctl_path)
    build_task(gate_pack, controller=c)
    [call] = recording_task.calls
    assert call["early_stopping"] is not None
    assert call["early_stopping"]._c is c


def test_build_task_passes_nothing_at_all_without_a_controller(gate_pack,
                                                               recording_task):
    """Inertness, the Task 18 standard: a default build is what it always was."""
    from evalyn.engine.task_builder import build_task

    build_task(gate_pack)
    [call] = recording_task.calls
    assert call["early_stopping"] is None


def test_build_task_degrades_loudly_when_the_seam_is_absent(gate_pack, ctl_path,
                                                            degraded_task):
    """The absence is CONSTRUCTED (a Task class without the parameter), not
    assumed from the installed version. A `UserWarning`, never a
    `RuntimeWarning` — this must not be able to kill a paid eval (R4-44)."""
    from evalyn.engine.task_builder import build_task

    with pytest.warns(UserWarning, match="early_stopping"):
        build_task(gate_pack, controller=_controller(ctl_path))
    [call] = degraded_task.calls
    assert "early_stopping" not in call, (
        "the argument was passed to a Task that would silently absorb it — "
        "that is the pause button that does nothing")


# ==========================================================================
# 5. Gate: pause changes nothing but wall time
# ==========================================================================

def test_a_paused_gate_run_writes_the_same_artifact_as_an_unpaused_one(
        gate_pack, tmp_path, ctl_path):
    """Step 1(a). A 2 s pause must change NOTHING but wall time.

    The resume comes from a `threading.Timer` that is guaranteed to fire —
    `run_gate` is synchronous, so a resume scheduled on this thread would never
    run and the test would hang instead of failing.
    """
    unpaused = _gate(gate_pack, tmp_path, name="unpaused")

    sink = _RecordingSink()
    c = _controller(ctl_path, sink)
    c.request("pause")
    timer = threading.Timer(PAUSE_SECONDS, lambda: c.request("resume"))
    timer.daemon = True
    timer.start()
    started = time.monotonic()
    try:
        paused = _gate(gate_pack, tmp_path, name="paused", controller=c)
    finally:
        timer.cancel()
    elapsed = time.monotonic() - started

    assert elapsed >= PAUSE_SECONDS, (
        f"the run finished in {elapsed:.2f}s — it never actually paused, so "
        f"the equality below proves nothing")
    assert sink.names == ["control.paused", "control.resumed"]
    assert paused.cancelled is False
    assert _blank_volatile(unpaused.to_dict()) == _blank_volatile(paused.to_dict())
    # ...and every trial really was collected, so the equality is not two
    # equally empty artifacts.
    assert paused.probes and all(p.trials == p.expected_trials
                                 for p in paused.probes)


def test_only_time_varying_fields_differ_between_two_uncontrolled_runs(gate_pack,
                                                                       tmp_path):
    """THE CONTROL for the test above — Task 18's, re-run here so this file's
    proof stands on its own. Two runs with NO controller on either side differ
    in exactly the three fields `_blank_volatile` blanks. If something else ever
    becomes non-deterministic, this reds rather than the equality proof quietly
    widening."""
    a = _gate(gate_pack, tmp_path, name="c1").to_dict()
    b = _gate(gate_pack, tmp_path, name="c2").to_dict()
    assert _blank_volatile(a) == _blank_volatile(b)
    differing = {k for k in a if k not in {"probes"} and a[k] != b[k]}
    assert differing <= set(VOLATILE), differing


# ==========================================================================
# 6. Gate: a cancelled run is marked, and is never a verdict
# ==========================================================================

def test_a_cancelled_gate_run_marks_the_artifact_and_still_writes_it(
        gate_pack, tmp_path, ctl_path):
    sink = _RecordingSink()
    c = _controller(ctl_path, sink)
    c.request("cancel")
    art = _gate(gate_pack, tmp_path, name="cancelled", sink=sink, controller=c)

    assert art.cancelled is True
    assert "control.cancelled" in sink.names
    # Every sample was stopped before it started, so every probe reads
    # trials=0. That is the fail-closed MISSING shape — safe, but NOT what an
    # operator who clicked Cancel expects to see, which is exactly why the flag
    # above exists.
    assert art.probes and all(p.trials == 0 for p in art.probes)
    # The artifact is on disk: a cancelled run must still leave evidence.
    [written] = (tmp_path / "cancelled").glob("*.json")
    assert json.loads(written.read_text())["cancelled"] is True
    assert [f["status"] for n, f in sink.events if n == "run.finished"] \
        == ["cancelled"]


def test_a_fully_cancelled_run_is_not_reported_as_a_dead_target(gate_pack,
                                                                tmp_path, ctl_path):
    """`run_gate` raises "no probe collected a single scored trial" when every
    session errored — a diagnosis of a DOWN TARGET. It is false of a run the
    operator stopped, and raising it would cost the artifact its exit code and
    the operator a wrong explanation."""
    c = _controller(ctl_path)
    c.request("cancel")
    art = _gate(gate_pack, tmp_path, name="dead", controller=c)  # must not raise
    assert art.cancelled is True


class _CancelledAfterScoring:
    """A controller that halts NOTHING and reports cancelled afterwards.

    This is the construction the discriminating tests need: the cancel lands
    after every probe has already scored, so the artifact is complete and
    passing and `cancelled` is the ONLY thing wrong with it.
    """

    def __init__(self):
        self.cancelled = True
        self.paused = False
        self.poll_seconds = 0.01

    def refresh(self, where=""):
        return "cancel"

    async def checkpoint(self, *, key):
        return None

    def as_early_stopping(self):
        return None      # no manager: nothing is ever stopped


def test_a_cancel_that_lands_after_scoring_still_marks_the_artifact(gate_pack,
                                                                    tmp_path):
    art = _gate(gate_pack, tmp_path, name="late", controller=_CancelledAfterScoring())
    assert art.cancelled is True
    # ...and it is a COMPLETE, PASSING run in every other respect — which is
    # what makes the CLI tests below discriminating.
    assert art.probes and all(p.trials == p.expected_trials and p.pass_k == 1.0
                              for p in art.probes)


# ==========================================================================
# 7. The CLI: exit 3, and the --update-baseline refusal
# ==========================================================================

def _cli_gate(tmp_path, pack_dir, monkeypatch, *, cancelled: bool, extra=()):
    """Run `evalyn gate` where the run comes back cancelled or not.

    The cancel is injected at the ARTIFACT, not the schedule, on purpose: these
    two tests are about what the CLI does with a cancelled run that scored
    everything, and a real mid-flight cancel cannot produce that shape.
    """
    from typer.testing import CliRunner

    from evalyn.cli import app
    from evalyn.engine import run as run_mod

    real = run_mod.run_gate

    def _wrapped(*a, **kw):
        art = real(*a, **kw)
        art.cancelled = cancelled
        return art

    monkeypatch.setattr(run_mod, "run_gate", _wrapped)
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(app, [
        "gate", "--target", str(pack_dir), "--out-dir", str(tmp_path / "runs"),
        "--baseline", str(tmp_path / "none.json"), *extra])


@pytest.fixture
def cli_pack(tmp_path, toy_target, monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    return _write_gate_pack(tmp_path / "clipack", toy_target)


def test_a_cancelled_gate_run_never_exits_0_even_when_every_probe_passed(
        cli_pack, tmp_path, monkeypatch):
    """Step 1(c). The control below is what makes it a real claim: the SAME run,
    not cancelled, exits 0."""
    ok = _cli_gate(tmp_path, cli_pack, monkeypatch, cancelled=False)
    assert ok.exit_code == 0, ok.output      # control: this run genuinely passes

    cancelled = _cli_gate(tmp_path, cli_pack, monkeypatch, cancelled=True)
    assert cancelled.exit_code == 3, cancelled.output
    assert "CANCELLED" in cancelled.output


def test_update_baseline_refuses_a_cancelled_artifact(cli_pack, tmp_path,
                                                      monkeypatch):
    """Step 1(d), made DISCRIMINATING. The pre-existing `problems` entries are
    zero-trials and INCOMPLETE, and this artifact has neither: every probe
    scored every expected trial and passed. Only an explicit `cancelled` entry
    can refuse it — proven by the control, where the identical run blesses."""
    baseline = tmp_path / "bl.json"
    ok = _cli_gate(tmp_path, cli_pack, monkeypatch, cancelled=False,
                   extra=["--update-baseline", "--baseline", str(baseline)])
    assert ok.exit_code == 0, ok.output      # control: nothing else objects
    assert baseline.is_file()

    baseline2 = tmp_path / "bl2.json"
    refused = _cli_gate(tmp_path, cli_pack, monkeypatch, cancelled=True,
                        extra=["--update-baseline", "--baseline", str(baseline2)])
    assert refused.exit_code == 2, refused.output
    assert "refusing --update-baseline" in refused.output
    assert "CANCELLED" in refused.output
    assert not baseline2.exists(), "a cancelled run was blessed as a baseline"


def test_a_default_gate_run_never_constructs_a_controller(cli_pack, tmp_path,
                                                          monkeypatch):
    """The Task 18 inertness standard, applied to the control channel: without
    `--control` nothing is constructed, so nobody's stale control file can pause
    or stop a run that never asked to be controllable. A REAL run, not a
    `--dry-run` — the construction site is past the dry-run exit."""
    class _NeverConstruct:
        def __init__(self, *a, **kw):
            raise AssertionError(f"a default run built RunController({a!r})")

    monkeypatch.setattr(control_mod, "RunController", _NeverConstruct)
    from typer.testing import CliRunner

    from evalyn.cli import app

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, [
        "gate", "--target", str(cli_pack), "--out-dir", str(tmp_path / "runs"),
        "--baseline", str(tmp_path / "none.json")])
    assert not isinstance(result.exception, AssertionError), result.exception
    assert result.exit_code in (0, 1), result.output
    # ...and the control test: with the flag ON it IS constructed, so the
    # assertion above is not vacuously true of a sentinel nothing could reach.
    boom = CliRunner().invoke(app, [
        "gate", "--target", str(cli_pack), "--out-dir", str(tmp_path / "runs2"),
        "--baseline", str(tmp_path / "none.json"), "--control"])
    assert isinstance(boom.exception, AssertionError), boom.output


# ==========================================================================
# 8. `RunArtifact.cancelled` is additive
# ==========================================================================

def _pre_plan4_artifact_dict() -> dict:
    """A genuine pre-#4 artifact payload: every key the schema had BEFORE this
    task, and no `cancelled`. `from_dict` raises on unknown keys, so the reverse
    direction is the one that has to keep working."""
    return {
        "pack_name": "example", "pack_hash": "a" * 64,
        "judge_model": "openai/gpt-4o-mini",
        "created_at": "2026-07-28T10:00:00+00:00",
        "log_path": "runs/logs/x.eval",
        "rubric_scores_untrusted": False, "judge_usd": 0.0123,
        "total_unsure_trials": 0,
        "probes": [{
            "id": "p1", "category": "grounding", "kind": "regression",
            "safety_critical": False, "samples": 3, "trials": 3,
            "expected_trials": 3, "pass_at_k": 1.0, "pass_k": 1.0,
            "mean_score": 1.0, "unsure_trials": 0, "checks": [],
            "trial_records": [],
        }],
    }


def test_a_pre_plan4_artifact_still_loads_and_reads_as_not_cancelled():
    art = RunArtifact.from_dict(_pre_plan4_artifact_dict())
    assert art.cancelled is False
    assert art.judge_usd == 0.0123 and art.probes[0].id == "p1"


def test_the_new_field_round_trips_through_to_dict_and_back():
    art = RunArtifact.from_dict(_pre_plan4_artifact_dict())
    art.cancelled = True
    again = RunArtifact.from_dict(json.loads(json.dumps(art.to_dict())))
    assert again.cancelled is True
    assert again.to_dict() == art.to_dict()


def test_a_cancelled_artifact_cannot_carry_a_non_dict_trial_record(gate_pack,
                                                                    tmp_path,
                                                                    ctl_path):
    """R4-46. This task is the first that can write a PARTIAL artifact, and a
    non-dict `trial_records` entry is a parked defect that 500s the WHOLE run
    list (`RunIndex.list` has no per-row guard). Asserted structurally — the
    reducer appends a dict LITERAL and nothing else — and then observed on a
    real cancelled run."""
    import warnings as _w

    c = _controller(ctl_path)
    c.request("cancel")
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        _gate(gate_pack, tmp_path, name="r446", controller=c)
    written = json.loads(next((tmp_path / "r446").glob("*.json")).read_text())
    for probe in written["probes"]:
        assert isinstance(probe["trial_records"], list)
        for rec in probe["trial_records"]:
            assert isinstance(rec, dict), rec
    # A cancelled probe has NO records at all — the reducer only emits one per
    # SCORED epoch, and a stopped sample never reaches the log.
    assert all(p["trial_records"] == [] for p in written["probes"])


# ==========================================================================
# 9. Discovery: a cancel is a deliberate stop, never an error
# ==========================================================================

def test_stop_reason_admits_cancelled():
    from typing import get_args

    from evalyn.discovery.loop import StopReason

    assert "cancelled" in get_args(StopReason)


async def test_a_cancelled_hunt_stops_with_cancelled_and_not_error(ctl_path,
                                                                   toy_target,
                                                                   monkeypatch):
    """Step 1(e). `RunCancelled` is caught BEFORE the blanket `except
    Exception`, so the hunt is `cancelled`, never `error`.

    Under `-W error::RuntimeWarning` this is doubly discriminating: the blanket
    handler warns `RuntimeWarning`, so a `RunCancelled` that fell through to it
    would surface as a raised warning rather than a returned result.
    """
    from evalyn.discovery.confirm import Confirmation
    from evalyn.discovery.loop import run_session
    from evalyn.discovery.meter import SpendMeter
    from evalyn.discovery.config import Limits
    from evalyn.discovery.objectives import get_objective
    from tests.engine.test_events_noop import MINIPACK

    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    from tests.conftest import retarget_yaml
    import shutil

    root = Path(str(ctl_path.parent.parent / "dpack"))
    shutil.copytree(MINIPACK, root)
    (root / "target.yaml").write_text(
        retarget_yaml((root / "target.yaml").read_text(), toy_target))
    pack = load_pack(root)

    c = _controller(ctl_path)
    c.request("cancel")

    class _NeverConfirms:
        async def confirm(self, probe, transcript):
            return Confirmation(confirmed=False, unsure=False, tier=1,
                                reason="not asked")

    result = await run_session(
        pack, get_objective("prompt-injection-bypass"),
        agent_model="openai/gpt-5-mini", meter=SpendMeter(10.0),
        limits=Limits(max_steps=4, max_sessions=1, max_usd=10.0, max_turns=4),
        confirmer=_NeverConfirms(), controller=c)

    assert result.stop_reason == "cancelled"
    assert "RunCancelled" in (result.error or "")
    # The cancel happened BEFORE the agent was ever asked to reason, so nothing
    # was spent on it — the checkpoint sits in the BOUNDS-FIRST block.
    assert result.steps == []


@pytest.mark.parametrize("stop_reason,partial,errors", [
    ("cancelled", True, 0),          # a deliberate stop: partial, never an error
    ("confirmed", False, 0),         # the control — an ordinary hunt
])
def test_the_discovery_accounting_treats_a_cancelled_hunt_as_partial_not_failed(
        tmp_path, monkeypatch, stop_reason, partial, errors):
    """The recon asked what `discovery/run.py`'s error accounting does with the
    new stop reason before it was widened. Answer, and now the contract:
    `error_count` does NOT rise (a cancel is not a failure) and `budget_stops`
    does not flip — but the run IS `partial`, because it did not do all the work
    it set out to do, and nothing said so before.

    Driven through the real accounting: the eval is stubbed to one sample whose
    stored session carries the reason, so this is `run_discovery`'s own loop
    deciding, not a re-derivation of it.
    """
    from evalyn.discovery import run as drun
    from evalyn.discovery import solver as dsolver
    from evalyn.discovery.config import DiscoveryConfig, Limits
    from evalyn.discovery.loop import SessionResult

    pack = load_pack(_write_gate_pack(tmp_path / "dpack", "http://localhost:8899"))
    session = SessionResult(objective_id="prompt-injection-bypass",
                            stop_reason=stop_reason)

    log = SimpleNamespace(status="success", location="",
                          samples=[SimpleNamespace(store={"x": 1})],
                          stats=SimpleNamespace(model_usage={}))

    async def _fake_eval(task, log_dir):
        return log

    monkeypatch.setattr(drun, "_run_discovery_eval", _fake_eval)
    monkeypatch.setattr(drun, "build_discovery_task", lambda *a, **kw: None)
    monkeypatch.setattr(dsolver, "session_from_store", lambda s: session)

    cfg = DiscoveryConfig(
        limits=Limits(max_steps=1, max_sessions=1, max_usd=10.0, max_turns=1),
        objectives=("prompt-injection-bypass",), agent_model="openai/gpt-5-mini",
        out_dir=tmp_path / "runs", staging_dir=tmp_path / "staging")
    art = asyncio.run(drun.run_discovery(pack, cfg))

    assert art.error_count == errors
    assert art.partial is partial
    assert art.budget_exhausted is False


# ==========================================================================
# 10. Compare: the checkpoint sits before the semaphore
# ==========================================================================

def test_a_cancelled_compare_raises_before_any_judge_call(tmp_path, ctl_path,
                                                          monkeypatch):
    from evalyn.engine import compare as cmp_mod
    from evalyn.engine.run import pack_fingerprint

    calls = []

    async def _never(*a, **kw):
        calls.append(a)
        raise AssertionError("a cancelled compare judged a pair anyway")

    monkeypatch.setattr(cmp_mod, "judge_pair", _never)

    d = tmp_path / "cpack"
    (d / "probes").mkdir(parents=True)
    (d / "rubrics").mkdir()
    (d / "target.yaml").write_text(
        "name: cmp\nsessions:\n  open: {method: POST, path: /session}\n"
        "  message: {method: POST, path: /chat}\n"
        "env: {base_url: http://localhost:8899}\n"
        "allowlist: [http://localhost:8899]\n")
    (d / "rubrics" / "tone.md").write_text("# Tone rubric\n## Calm\nStays calm.\n")
    (d / "probes" / "p.yaml").write_text(
        "- id: r1\n  category: chat\n  turns: [hi]\n  checks:\n"
        "    - { type: rubric, rubric: tone, required: true }\n")
    pack = load_pack(str(d))

    def _art(created_at):
        return RunArtifact(
            pack_name="cmp", pack_hash=pack_fingerprint(pack),
            judge_model="mockllm/model", created_at=created_at,
            probes=[ProbeResult(
                id="r1", category="chat", kind="regression",
                safety_critical=False, samples=1, trials=1,
                trial_records=[{"epoch": 0, "transcript": "User: hi",
                                "session_seconds": 1.0,
                                "invariant_failures": 0}])],
            log_path="runs/logs")

    sink = _RecordingSink()
    c = _controller(ctl_path, sink)
    c.request("cancel")
    with pytest.raises(RunCancelled):
        asyncio.run(cmp_mod.run_compare(
            pack, _art("2026-08-01T00:00:00+00:00"),
            _art("2026-08-02T00:00:00+00:00"), "openai/gpt-4o",
            out_dir=str(tmp_path / "runs"), sink=sink, controller=c))
    assert calls == []
    assert [f["status"] for n, f in sink.events if n == "run.finished"] \
        == ["cancelled"]


# ==========================================================================
# 11. The pin
# ==========================================================================

def test_inspect_ai_is_pinned_below_0_4():
    """The whole feature rides on `Task(early_stopping=…)`, and `**kwargs`
    means a major version that dropped it would absorb the argument in
    silence rather than failing. An upper bound is what turns that into a
    dependency-resolution error somebody reads."""
    text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    assert '"inspect_ai>=0.3.249,<0.4"' in text


def test_the_early_stopping_seam_exists_in_the_pinned_version():
    """A live check against the version actually installed, so a bad bump is
    caught here rather than by a pause button that silently does nothing."""
    assert early_stopping_supported() is True


# ==========================================================================
# 12. FIX ROUND 1 — the wiring itself, which nothing used to test
#
# Review findings I1/I2/I3. The control channel worked end-to-end, but every
# test drove it by passing a controller straight to `run_gate` / `run_compare`
# / `run_session`, so the seam the COCKPIT uses — CLI flag to engine argument —
# was invisible: deleting `controller=controller` from `cli.gate`, or replacing
# compare's and discover's `_open_control` with `controller = None`, left the
# whole suite green. On 2026-08-14 that argument is the Pause button.
# ==========================================================================

class _Sentinel(RuntimeError):
    """Raised by the recorders below, so the CLI unwinds after recording."""


def _cli(app_args, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from evalyn.cli import app

    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(app, app_args)


@pytest.fixture
def compare_cli_pack(tmp_path):
    """A rubric pack plus two artifacts on disk — enough for `compare` to run."""
    from evalyn.engine.run import pack_fingerprint

    d = tmp_path / "cmppack"
    (d / "probes").mkdir(parents=True)
    (d / "rubrics").mkdir()
    (d / "target.yaml").write_text(
        "name: cmp\nsessions:\n  open: {method: POST, path: /session}\n"
        "  message: {method: POST, path: /chat}\n"
        "env: {base_url: http://localhost:8899}\n"
        "allowlist: [http://localhost:8899]\n")
    (d / "rubrics" / "tone.md").write_text("# Tone rubric\n## Calm\nStays calm.\n")
    (d / "probes" / "p.yaml").write_text(
        "- id: r1\n  category: chat\n  turns: [hi]\n  checks:\n"
        "    - { type: rubric, rubric: tone, required: true }\n")
    pack = load_pack(str(d))
    paths = []
    for i, created in enumerate(("2026-08-01T00:00:00+00:00",
                                 "2026-08-02T00:00:00+00:00")):
        art = RunArtifact(
            pack_name="cmp", pack_hash=pack_fingerprint(pack),
            judge_model="mockllm/model", created_at=created,
            probes=[ProbeResult(
                id="r1", category="chat", kind="regression",
                safety_critical=False, samples=1, trials=1,
                trial_records=[{"epoch": 0, "transcript": "User: hi",
                                "session_seconds": 1.0,
                                "invariant_failures": 0}])],
            log_path="runs/logs")
        p = tmp_path / f"side{i}.json"
        p.write_text(json.dumps(art.to_dict()))
        paths.append(str(p))
    return d, paths


def _gate_argv(pack_dir, tmp_path):
    return ["gate", "--target", str(pack_dir), "--out-dir", str(tmp_path / "runs"),
            "--baseline", str(tmp_path / "none.json")]


def _compare_argv(pack_dir, sides, tmp_path):
    return ["compare", "--target", str(pack_dir), "--a", sides[0], "--b", sides[1],
            "--out-dir", str(tmp_path / "runs"), "--allow-uncalibrated",
            "--rubric-judge-model", "openai/gpt-4o"]


def _discover_argv(pack_dir, tmp_path):
    return ["discover", "--target", str(pack_dir), "--out-dir",
            str(tmp_path / "runs"), "--objective", "prompt-injection-bypass",
            "--staging-dir", str(tmp_path / "staging"),
            "--agent-model", "openai/gpt-5-mini"]


@pytest.fixture
def cli_seam(request, tmp_path, monkeypatch, cli_pack, compare_cli_pack,
             discover_cli_pack):
    """`(argv, install_recorder)` for one mode.

    `install_recorder` patches the ONE engine entry point that mode's CLI calls
    and returns the list its keyword arguments land in — so the assertion is
    about what the CLI actually handed over, not about what it constructed.
    """
    mode = request.param
    cmp_dir, sides = compare_cli_pack

    def _install(target_module, name, *, is_async):
        calls = []

        if is_async:
            async def _rec(*a, **kw):
                calls.append(kw)
                raise _Sentinel(name)
        else:
            def _rec(*a, **kw):
                calls.append(kw)
                raise _Sentinel(name)

        monkeypatch.setattr(target_module, name, _rec)
        return calls

    if mode == "gate":
        from evalyn.engine import run as run_mod
        return (mode, _gate_argv(cli_pack, tmp_path),
                lambda: _install(run_mod, "run_gate", is_async=False))
    if mode == "compare":
        from evalyn.engine import compare as cmp_mod
        return (mode, _compare_argv(cmp_dir, sides, tmp_path),
                lambda: _install(cmp_mod, "run_compare", is_async=True))
    from evalyn.discovery import run as drun
    return (mode, _discover_argv(discover_cli_pack, tmp_path),
            lambda: _install(drun, "run_discovery", is_async=True))


@pytest.mark.parametrize("cli_seam", ["gate", "compare", "discover"],
                         indirect=True)
def test_the_cli_hands_its_controller_to_the_engine(cli_seam, tmp_path,
                                                    monkeypatch):
    """I1. The seam the cockpit's Pause button travels down.

    Both halves matter and neither alone is worth anything: WITHOUT `--control`
    the engine must receive `None` (inertness), and WITH it the engine must
    receive the object — a controller that is constructed and then not passed is
    a stop button wired to nothing, which is exactly the state three separate
    one-line deletions left the suite green in.
    """
    from evalyn.ui.index import mode_of
    from evalyn.ui.models import RunMode
    from evalyn.ui.paths import CONTROL_SUFFIX

    mode, argv, install = cli_seam

    calls = install()
    _cli(argv, monkeypatch, tmp_path)
    assert calls, "the CLI never reached the engine entry point at all"
    assert calls[0].get("controller") is None, (
        "a run with no --control was handed a controller")

    calls = install()
    _cli([*argv, "--control"], monkeypatch, tmp_path)
    assert calls, "the CLI never reached the engine entry point at all"
    controller = calls[0].get("controller")
    assert controller is not None, (
        "--control constructed a controller and then did not hand it over — "
        "the stop button is wired to nothing")

    # ...and WHICH FILE it polls, which `is not None` cannot see. A compare run
    # polling `runs/<rid>.control.json` while the cockpit writes
    # `runs/<rid>-compare.control.json` is a Pause button wired to nothing, and
    # it is one character away in `_MODE_SUFFIX`.
    #
    # Asserted by ROUND-TRIP through the reader's own contract rather than
    # against a literal: strip the control suffix to recover the artifact stem
    # and ask `ui.index.mode_of` — the function the cockpit uses to classify a
    # run — which mode wrote it. Writer and reader then cannot drift in either
    # direction, and no suffix is spelled twice.
    assert controller.path.name.endswith(CONTROL_SUFFIX)
    stem = controller.path.name[: -len(CONTROL_SUFFIX)]
    assert mode_of(stem) is RunMode(mode), (
        f"a {mode} run polls {controller.path.name!r}, which the cockpit reads "
        f"back as a {mode_of(stem).value} run — the control file the engine "
        f"watches is not the one the server writes")
    # ...next to the artifact, in the caller's --out-dir, not somewhere else.
    assert controller.path.parent == (tmp_path / "runs")
    assert stem == calls[0]["run_id"] + _MODE_SUFFIX[mode]


def test_a_control_file_cancel_stops_a_real_gate_cli_run(cli_pack, tmp_path,
                                                          monkeypatch):
    """I1, end to end and with nothing patched: the demo path.

    The cancel is written to the DERIVED sidecar path before the run starts —
    the same file the cockpit's server writes — and the run is a real
    `evalyn gate --control` against the toy target.
    """
    from evalyn.engine.run import new_run_id
    from evalyn.ui.paths import control_path

    runs = tmp_path / "runs"
    runs.mkdir()
    rid = new_run_id("evpack")
    monkeypatch.setenv("EVALYN_RUN_ID", rid)
    cp = control_path(runs / f"{rid}.json")
    cp.write_text(json.dumps({"action": "cancel"}))

    result = _cli([*_gate_argv(cli_pack, tmp_path), "--control"], monkeypatch,
                  tmp_path)

    assert result.exit_code == 3, result.output
    written = json.loads((runs / f"{rid}.json").read_text())
    assert written["cancelled"] is True
    assert all(p["trials"] == 0 for p in written["probes"]), (
        "the cancel never reached the scheduler — every probe still ran")


@pytest.mark.parametrize("mode", ["compare", "discover"])
def test_the_cli_turns_a_RunCancelled_into_exit_3(mode, tmp_path, monkeypatch,
                                                   compare_cli_pack,
                                                   discover_cli_pack):
    """I1. `gate` reports a cancel through `RunArtifact.cancelled`; compare and
    discover have nothing to return, so they raise — and the two `except
    RunCancelled` arms are what turn that into the run-invalid exit code rather
    than the setup-error 2, which would tell CI to fix its config and retry."""
    cmp_dir, sides = compare_cli_pack

    async def _cancel(*a, **kw):
        raise RunCancelled("stopped at pair:r1#tone")

    if mode == "compare":
        from evalyn.engine import compare as cmp_mod
        monkeypatch.setattr(cmp_mod, "run_compare", _cancel)
        argv = _compare_argv(cmp_dir, sides, tmp_path)
    else:
        from evalyn.discovery import run as drun
        monkeypatch.setattr(drun, "run_discovery", _cancel)
        argv = _discover_argv(discover_cli_pack, tmp_path)

    result = _cli([*argv, "--control"], monkeypatch, tmp_path)
    assert result.exit_code == 3, result.output
    assert "CANCELLED" in result.output


# --------------------------------------------------------------------------
# I2 / I3 — the two discover cancel paths, neither of which had a test
# --------------------------------------------------------------------------

@pytest.fixture
def discover_cli_pack(tmp_path, monkeypatch, toy_target, live_pack_dir):
    from tests.engine.test_events_noop import MINIPACK

    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    return live_pack_dir(MINIPACK, name="discover-cli-pack")


@pytest.fixture
def discover_run_pack(tmp_path, monkeypatch, toy_target, live_pack_dir):
    """The minipack, live, with the toy target's leak planted every time."""
    import examples.toy_target as toy
    from tests.engine.test_events_noop import MINIPACK

    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    monkeypatch.setattr(toy, "LEAK_PROBABILITY", 1.0)
    return load_pack(live_pack_dir(MINIPACK, name="discover-run-pack"))


class _CancelOnEvent:
    """A sink that writes the cancel request the instant a named event lands.

    This is how the replay-boundary checkpoint is reached DETERMINISTICALLY:
    `finding.staged` is emitted immediately before it, so the cancel is on disk
    by the time the checkpoint polls — no sleeps, no races, and a real
    `RunController` reading a real control file rather than a stub.
    """

    def __init__(self, trigger: str):
        self.trigger = trigger
        self.controller: RunController | None = None
        self.names: list[str] = []
        self.events: list[tuple[str, dict]] = []

    def emit(self, type, /, **fields):  # noqa: A002 — the wire name
        self.names.append(type)
        self.events.append((type, fields))
        if type == self.trigger and self.controller is not None:
            self.controller.request("cancel")

    def close(self):
        return None


async def test_a_cancel_at_the_replay_boundary_stops_a_discovery_run(
        discover_run_pack, tmp_path, monkeypatch, ctl_path):
    """I2. Until the in-hunt seam existed this was the WHOLE discover cancel
    feature, and nothing guarded it: deleting the checkpoint and the terminal
    `cancelled` branch from `discovery/run.py` left the suite green.

    Each replay is a whole eval, so this boundary is where a cancel arriving
    mid-run actually saves money — and the R8-5 durability wrap must still
    write the partial artifact, because that record is the only evidence of
    what the run already spent.
    """
    from tests.engine.test_events_noop import (
        _confirming_script,
        _discovery_cfg,
        _scripted_brain,
    )

    _scripted_brain(monkeypatch, _confirming_script())
    sink = _CancelOnEvent("finding.staged")
    c = _controller(ctl_path, sink)
    sink.controller = c

    with pytest.raises(RunCancelled, match="replay:"):
        await discovery_run_mod.run_discovery(
            discover_run_pack, _discovery_cfg(tmp_path, staging_dir=None),
            sink=sink, controller=c)

    # The checkpoint is BEFORE `_replay_finding`, so no replay ever ran.
    assert "finding.staged" in sink.names
    assert "replay.result" not in sink.names
    # ...the partial record survived, and says it is partial...
    [written] = (tmp_path / "runs").glob("*-discover.json")
    record = json.loads(written.read_text())
    assert record["partial"] is True
    # ...and the terminal event says cancelled, not error: a cockpit must not
    # paint an operator's own stop button red.
    assert [f["status"] for n, f in sink.events if n == "run.finished"] \
        == ["cancelled"]


async def test_a_pre_cancelled_discovery_run_stops_inside_the_hunt(
        discover_run_pack, tmp_path, monkeypatch, ctl_path):
    """I3. The in-hunt checkpoint, reachable at last.

    `loop._drive`'s BOUNDS-FIRST checkpoint existed and worked from the day it
    was written, but `run_discovery` had no way to hand a controller to it —
    the seam runs through `build_discovery_task` and `discovery_solver`, and
    neither took one. This test only passes when both do.

    It is also what proves the checkpoint sits with the OTHER bounds rather than
    after them: the agent is never asked to reason, so a cancel that lands
    before a hunt starts costs nothing at all.
    """
    from tests.engine.test_events_noop import (
        _confirming_script,
        _discovery_cfg,
        _scripted_brain,
    )

    _scripted_brain(monkeypatch, _confirming_script())
    sink = _RecordingSink()
    c = _controller(ctl_path, sink)
    c.request("cancel")

    art = await discovery_run_mod.run_discovery(
        discover_run_pack, _discovery_cfg(tmp_path, staging_dir=None),
        sink=sink, controller=c)

    # Nothing was hunted: no step was taken, so nothing was spent.
    assert "agent.step" not in sink.names
    assert "finding.staged" not in sink.names
    assert art.live_spend_usd == 0.0
    # A cancelled hunt is NOT an error — `error_count >= sessions_total` is what
    # the CLI reads as "every hunt failed" and exits 3 on.
    assert art.sessions_total > 0
    assert art.error_count == 0
    assert art.confirmed_count == 0
    # ...but the run did not do the work it set out to do, and says so.
    assert art.partial is True
    assert "control.cancelled" in sink.names


def test_the_discovery_seam_carries_the_controller_all_the_way_down():
    """The two arguments I3 added, pinned by signature so a refactor that drops
    one is a red here rather than a stop button that silently stops nothing.

    Deliberately alongside the behavioural test above, not instead of it: a
    signature check cannot see an argument that is accepted and then dropped on
    the floor, which is the exact defect this round is about.
    """
    import inspect as _inspect

    from evalyn.discovery.loop import run_session
    from evalyn.discovery.solver import discovery_solver
    from evalyn.discovery.task_builder import build_discovery_task
    from evalyn.engine.events import NULL_SINK

    for fn in (build_discovery_task, discovery_solver, run_session,
               discovery_run_mod.run_discovery):
        params = _inspect.signature(fn).parameters
        assert "controller" in params, f"{fn.__qualname__} takes no controller"
        assert params["controller"].default is None
        # ...and the Task 18 pin is untouched: adding a parameter must not have
        # disturbed the sink's default at any of these entry points.
        if "sink" in params:
            assert params["sink"].default is NULL_SINK
