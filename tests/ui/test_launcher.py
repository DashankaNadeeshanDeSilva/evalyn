"""The run launcher and the control channel (Plan #4, Task 20).

## Nothing in this file may spend money

The module under test exists to start paid evaluations. Every test that spawns
a process spawns something **inert** — `sys.executable -c "..."` or
`python -m evalyn --help` — never a real `gate`, `compare` or `discover`. A
test that accidentally worked would be a test that accidentally billed, so the
`spawn` seam on `RunLauncher` is injected in every test that does not
explicitly need a real child, and the two that do need one assert on a child
that cannot reach a model.

`build_argv` is pure, so the exhaustive coverage lives there — it is the
cheapest place in the whole task to be complete.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evalyn.targets.loader import load_pack
from evalyn.ui.launcher import (
    Busy,
    RunLauncher,
    build_argv,
    clamp_max_usd,
    pack_id_for,
    refusal_for,
    spawn_child,
)
from evalyn.ui.models import ControlAction, LaunchRequest, RunMode
from evalyn.ui.paths import (
    META_EXIT_CODE_KEY,
    META_LAUNCHED_KEY,
    control_path,
    meta_path,
    sidecar_dir,
)

#: Derived locally, the way every other path constant under `tests/ui` is
#: (`test_index.py:827`, `test_redact.py:1130`), rather than imported from
#: `conftest` — pytest may hold a second module object for that file.
EXAMPLE_PACK = Path(__file__).resolve().parents[2] / "packs" / "example"

#: A child that exits at once, touches no network and costs nothing.
INERT = [sys.executable, "-c", "pass"]
#: A child that stays alive until it is reaped, so "busy" can be observed.
INERT_SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]


@pytest.fixture
def pack():
    return load_pack(EXAMPLE_PACK)


def request_for(mode: str, **overrides) -> LaunchRequest:
    body = {"mode": mode, "pack_id": pack_id_for("example"), "confirm": "example"}
    body.update(overrides)
    return LaunchRequest(**body)


def launcher_spawning(argv_to_use: list[str], runs_dir: Path) -> RunLauncher:
    """A launcher whose child is always inert, whatever `build_argv` says."""
    calls: list[dict] = []

    def spawn(argv, *, env, stderr, cwd=None):
        calls.append({"argv": argv, "env": env})
        return subprocess.Popen(argv_to_use, env=env, stderr=stderr,
                                start_new_session=True)

    made = RunLauncher(runs_dir, spawn=spawn)
    made.calls = calls        # type: ignore[attr-defined]
    return made


# --------------------------------------------------------------------------
# 1. `python -m evalyn` — the form the launcher actually spawns
# --------------------------------------------------------------------------

def run_module_form(*args: str) -> subprocess.CompletedProcess:
    """`python -m evalyn ...`, with colour forced OFF in the child.

    Not cosmetic. CI forces colour, the child inherits the environment, and
    `rich` then renders `--target` as `-` and `-target` with escape sequences
    between them — so an assertion on the literal string passes locally and
    fails only in the coloured leg. These tests are about which commands the
    module form reaches, not about how they are painted.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in {"FORCE_COLOR", "CLICOLOR_FORCE"}}
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    return subprocess.run([sys.executable, "-m", "evalyn", *args],
                          capture_output=True, text=True, timeout=120, env=env)


def test_the_module_form_actually_starts_a_process():
    """`sys.executable -m evalyn` must WORK, not merely be the string we build.

    `pyproject.toml` declares only a console script, so `evalyn.__main__` has
    to exist for this spawn to resolve at all — and a test that asserted on the
    argv string would have shipped a launcher that dies with `No module named
    evalyn.__main__` in front of an audience. `--help` spends nothing.
    """
    done = run_module_form("--help")
    assert done.returncode == 0, done.stderr
    assert "No module named" not in done.stderr
    assert "gate" in done.stdout


def test_the_module_form_reaches_the_same_commands_as_the_console_script():
    """The module entry point must be the same `app`, not a second CLI."""
    done = run_module_form("gate", "--help")
    assert done.returncode == 0, done.stderr
    assert "--target" in done.stdout


# --------------------------------------------------------------------------
# 2. `build_argv` — pure, so table-test all three modes exhaustively
# --------------------------------------------------------------------------

def test_build_argv_starts_with_the_interpreter_and_the_module_form():
    argv = build_argv(request_for("gate"), pack_path=EXAMPLE_PACK,
                      runs_dir=Path("/runs"))
    assert argv[:3] == [sys.executable, "-m", "evalyn"]
    assert argv[3] == "gate"


@pytest.mark.parametrize("mode", ["gate", "compare", "discover"])
def test_build_argv_always_asks_for_the_event_stream(mode):
    """Without `--events` the engine constructs no sink and writes no file
    (`cli.py:_open_sink`), so the cockpit's live panel would tail nothing. This
    is the flag whose absence looks exactly like a frozen run."""
    argv = build_argv(request_for(mode, run_id_a="20260101T000000000000-aaaaaaaa-example",
                                  run_id_b="20260101T000000000001-bbbbbbbb-example"),
                      pack_path=EXAMPLE_PACK, runs_dir=Path("/runs"))
    assert "--events" in argv


def cli_option_names(mode: str) -> set[str]:
    """Every long option `evalyn <mode>` actually accepts, read off the CLI.

    Introspected rather than spelled out, so a test that says "this flag is
    passed" cannot pass while the flag it names is one the child would reject.
    """
    import typer.main

    from evalyn.cli import app as cli_app

    command = typer.main.get_command(cli_app).commands[mode]
    return {opt for param in command.params for opt in param.opts}


@pytest.mark.parametrize("mode", ["gate", "compare", "discover"])
def test_build_argv_always_arms_the_control_channel(mode):
    """T20-d(a). `--control` defaults to `False` on all three modes
    (`cli.py`), so a child spawned without it never opens the control file at
    all: `_open_control` returns `(None, run_id)` and every poll point is
    skipped. The cockpit would still answer `202 accepted:true` to a cancel,
    write the file, and watch the run complete — an acknowledgement of an
    action nothing can act on. Measured, not reasoned about: the child's live
    argv was read out of `ps` and a cancel produced zero `control.*` events in
    a 62-event stream.
    """
    argv = build_argv(request_for(mode, run_id_a="20260101T000000000000-aaaaaaaa-example",
                                  run_id_b="20260101T000000000001-bbbbbbbb-example"),
                      pack_path=EXAMPLE_PACK, runs_dir=Path("/runs"))
    assert "--control" in argv
    assert "--control" in cli_option_names(mode), "the spelling the child accepts"


@pytest.mark.parametrize("mode", ["gate", "compare", "discover"])
def test_build_argv_always_names_the_pack_and_the_runs_directory(mode):
    argv = build_argv(request_for(mode, run_id_a="20260101T000000000000-aaaaaaaa-example",
                                  run_id_b="20260101T000000000001-bbbbbbbb-example"),
                      pack_path=EXAMPLE_PACK, runs_dir=Path("/runs"))
    assert argv[argv.index("--target") + 1] == str(EXAMPLE_PACK)
    assert argv[argv.index("--out-dir") + 1] == "/runs"


def test_build_argv_gate_passes_the_baseline_when_one_was_chosen():
    baseline = "20260101T000000000000-aaaaaaaa-example"
    argv = build_argv(request_for("gate", baseline_run_id=baseline),
                      pack_path=EXAMPLE_PACK, runs_dir=Path("/runs"))
    assert argv[argv.index("--baseline") + 1] == f"/runs/{baseline}.json"


def test_build_argv_gate_omits_the_baseline_flag_when_none_was_chosen():
    """Omitted, not passed empty: the CLI has its own default
    (`runs/baseline.json`) and passing `--baseline ""` would defeat it."""
    argv = build_argv(request_for("gate"), pack_path=EXAMPLE_PACK,
                      runs_dir=Path("/runs"))
    assert "--baseline" not in argv


def test_build_argv_compare_resolves_both_run_ids_to_artifact_paths():
    a = "20260101T000000000000-aaaaaaaa-example"
    b = "20260101T000000000001-bbbbbbbb-example"
    argv = build_argv(request_for("compare", run_id_a=a, run_id_b=b),
                      pack_path=EXAMPLE_PACK, runs_dir=Path("/runs"))
    assert argv[argv.index("--a") + 1] == f"/runs/{a}.json"
    assert argv[argv.index("--b") + 1] == f"/runs/{b}.json"


def test_build_argv_discover_passes_each_objective_as_its_own_flag():
    """`--objective` is `list[str]` on the CLI; a comma-joined single flag
    would be read as one objective named "a,b" and refused."""
    argv = build_argv(request_for("discover", objectives=["hallucination", "pii"]),
                      pack_path=EXAMPLE_PACK, runs_dir=Path("/runs"))
    assert argv.count("--objective") == 2
    pairs = [argv[i + 1] for i, flag in enumerate(argv) if flag == "--objective"]
    assert pairs == ["hallucination", "pii"]


def test_build_argv_discover_omits_objectives_entirely_when_none_were_picked():
    """Empty means "all of them" (`LaunchRequest.objectives`), which the CLI
    expresses as the flag being absent."""
    argv = build_argv(request_for("discover"), pack_path=EXAMPLE_PACK,
                      runs_dir=Path("/runs"))
    assert "--objective" not in argv


def test_build_argv_discover_passes_the_clamped_ceiling_it_is_given():
    argv = build_argv(request_for("discover", max_usd=9.0), pack_path=EXAMPLE_PACK,
                      runs_dir=Path("/runs"), max_usd=1.0)
    assert argv[argv.index("--max-usd") + 1] == "1.0"
    assert "9.0" not in argv


def test_build_argv_never_passes_the_browsers_unclamped_figure():
    """The clamp is the server's job; `build_argv` must take the resolved
    ceiling as a parameter rather than reading `request.max_usd` itself, or the
    clamp could be bypassed by the one caller that forgot."""
    argv = build_argv(request_for("discover", max_usd=100.0), pack_path=EXAMPLE_PACK,
                      runs_dir=Path("/runs"), max_usd=None)
    assert "--max-usd" not in argv


@pytest.mark.parametrize("mode", ["gate", "compare", "discover"])
def test_build_argv_forwards_allow_uncalibrated_only_when_asked(mode):
    common = {"run_id_a": "20260101T000000000000-aaaaaaaa-example",
              "run_id_b": "20260101T000000000001-bbbbbbbb-example"}
    off = build_argv(request_for(mode, **common), pack_path=EXAMPLE_PACK,
                     runs_dir=Path("/runs"))
    on = build_argv(request_for(mode, allow_uncalibrated=True, **common),
                    pack_path=EXAMPLE_PACK, runs_dir=Path("/runs"))
    assert "--allow-uncalibrated" not in off
    assert "--allow-uncalibrated" in on


@pytest.mark.parametrize("mode", ["gate", "compare", "discover"])
def test_build_argv_produces_only_strings(mode):
    """`subprocess` rejects a `Path` mixed into argv on some platforms and
    silently stringifies on others; pinning it here keeps the spawn portable."""
    argv = build_argv(request_for(mode, max_usd=1.0,
                                  run_id_a="20260101T000000000000-aaaaaaaa-example",
                                  run_id_b="20260101T000000000001-bbbbbbbb-example"),
                      pack_path=EXAMPLE_PACK, runs_dir=Path("/runs"), max_usd=1.0)
    assert all(isinstance(part, str) for part in argv)


# --------------------------------------------------------------------------
# 3. The clamp — down, never up, and `0` means opposite things on each side
# --------------------------------------------------------------------------

@pytest.mark.parametrize("requested,cap,expected", [
    pytest.param(9.0, 1.0, 1.0, id="above-the-cap-is-clamped-down"),
    pytest.param(0.5, 1.0, 0.5, id="below-the-cap-is-left-alone"),
    pytest.param(1.0, 1.0, 1.0, id="exactly-the-cap-is-left-alone"),
    pytest.param(None, 1.0, None, id="no-request-defers-to-the-packs-own-cap"),
    pytest.param(None, 0.0, None, id="no-request-against-an-uncapped-pack"),
])
def test_clamp_max_usd(requested, cap, expected):
    assert clamp_max_usd(requested, cap) == expected


def test_clamp_never_raises_a_request_up_to_meet_a_bigger_cap():
    """The browser can lower the ceiling, never raise it — and it must not be
    raised to the pack's cap either, which would spend more than was asked."""
    assert clamp_max_usd(0.25, 5.0) == 0.25


def test_an_uncapped_pack_passes_the_request_through_rather_than_clamping_to_zero():
    """R10-4, and the sharpest edge in this task.

    A pack's `budget.max_usd_per_run: 0` means **uncapped**; the CLI's
    `--max-usd 0` means **spend nothing** and is refused outright with exit 2
    (`cli.py:576-586`). `min(request, 0)` would therefore turn an uncapped pack
    into a run that refuses to start — the clamp becoming a footgun exactly
    where the operator asked for the fewest limits.
    """
    assert clamp_max_usd(3.0, 0.0) == 3.0


# --------------------------------------------------------------------------
# 4. The refusals — all three are `launch_refused`, plus the zero-spend one
# --------------------------------------------------------------------------

def test_an_unknown_pack_id_is_refused(pack):
    why = refusal_for(request_for("gate", pack_id="pack-nope"), pack=None,
                      allow_discover=True)
    assert why is not None
    assert "allowlist" in why


def test_confirm_must_echo_the_pack_name(pack):
    why = refusal_for(request_for("gate", confirm="Example"), pack=pack,
                      allow_discover=True)
    assert why is not None
    assert "confirm" in why


def test_confirm_matching_the_name_is_accepted(pack):
    assert refusal_for(request_for("gate"), pack=pack, allow_discover=True) is None


def test_discover_is_refused_unless_the_operator_asked_for_it(pack):
    why = refusal_for(request_for("discover"), pack=pack, allow_discover=False)
    assert why is not None
    assert "--allow-discover" in why


def test_gate_is_unaffected_by_the_discover_switch(pack):
    """The switch gates `discover` alone; a gate run must not be collateral."""
    assert refusal_for(request_for("gate"), pack=pack, allow_discover=False) is None


def test_a_zero_dollar_discover_is_refused_rather_than_spawned(pack):
    """The CLI exits 2 on `--max-usd 0`. Refusing here turns a child that dies
    instantly into a sentence the operator reads on the launch screen."""
    why = refusal_for(request_for("discover", max_usd=0.0), pack=pack,
                      allow_discover=True)
    assert why is not None
    assert "0" in why


def test_compare_without_both_run_ids_is_refused(pack):
    why = refusal_for(request_for("compare"), pack=pack, allow_discover=True)
    assert why is not None


# --------------------------------------------------------------------------
# 5. The pack id scheme
# --------------------------------------------------------------------------

def test_a_pack_id_is_never_a_path():
    """`PackRow.id` is documented as "an index into that allowlist, never a
    path", and `PackRow.path` carries a display-safe label instead."""
    made = pack_id_for("example")
    assert "/" not in made
    assert "\\" not in made
    assert not made.startswith("~")


def test_the_same_pack_gets_the_same_id_every_time():
    """Stable across a restart: the id is derived from the pack's own name, so
    it survives the server being restarted, `--target` being reordered, the
    operator's cwd changing, and the pack directory being moved."""
    assert pack_id_for("example") == pack_id_for("example")


def test_different_packs_get_different_ids():
    assert pack_id_for("example") != pack_id_for("twincore")


def test_a_pack_id_is_url_safe_for_a_path_parameter():
    made = pack_id_for("a name with spaces/and a slash")
    assert made == "".join(c for c in made if c.isalnum() or c == "-")


# --------------------------------------------------------------------------
# 6. Launching — the id, the sidecar, the env, and the process group
# --------------------------------------------------------------------------

def test_launch_returns_an_id_that_is_the_stem_of_the_artifact_that_appears(
        tmp_path, pack):
    """The contract `LaunchResponse` states (`models.py:967-975`): the id is
    minted before the process starts and IS the stem of the artifact that later
    appears, which is what makes subscribing before the file exists valid.

    Proven by having the inert child write the artifact the engine would have
    written, at the path the engine derives from `EVALYN_RUN_ID` — the same
    `out_dir/<run_id><suffix>.json` composition `cli.py:_open_sink` uses.
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    writer = [sys.executable, "-c",
              "import os, pathlib; "
              "pathlib.Path(os.environ['OUT'], os.environ['EVALYN_RUN_ID'] + '.json')"
              ".write_text('{}')"]
    made = launcher_spawning(writer, runs)
    os.environ["OUT"] = str(runs)
    try:
        run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
        made.live.process.wait(timeout=60)
    finally:
        del os.environ["OUT"]
    assert (runs / f"{run_id}.json").exists()
    assert sorted(p.stem for p in runs.glob("*.json")) == [run_id]


@pytest.mark.parametrize("mode,suffix", [("gate", ""), ("compare", "-compare"),
                                         ("discover", "-discover")])
def test_the_returned_id_carries_the_modes_artifact_suffix(tmp_path, pack, mode, suffix):
    """The cockpit keys everything by the artifact **stem**, suffix included
    (`server.py` module docstring, C-T6/7), while `EVALYN_RUN_ID` is the engine
    id without it. Confusing the two would key the sidecar under a name
    `RunIndex` never looks for."""
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    body = {"run_id_a": "20260101T000000000000-aaaaaaaa-example",
            "run_id_b": "20260101T000000000001-bbbbbbbb-example"}
    run_id = made.launch(request_for(mode, **body), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    assert run_id.endswith(suffix)
    engine_id = made.calls[0]["env"]["EVALYN_RUN_ID"]
    assert run_id == engine_id + suffix


def test_the_child_is_told_its_run_id_through_the_environment(tmp_path, pack):
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    assert made.calls[0]["env"]["EVALYN_RUN_ID"] == run_id


def test_the_child_inherits_the_servers_environment_not_a_bare_one(tmp_path, pack):
    """An API key lives in the operator's environment. A child spawned with a
    bare env would reach the judge with no credentials and fail the demo at the
    first scored probe."""
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    os.environ["EVALYN_TEST_MARKER"] = "inherited"
    try:
        made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
        made.live.process.wait(timeout=60)
    finally:
        del os.environ["EVALYN_TEST_MARKER"]
    assert made.calls[0]["env"]["EVALYN_TEST_MARKER"] == "inherited"


def test_launch_writes_the_meta_file_the_index_reads(tmp_path, pack):
    """`RunIndex._sidecar` reads exactly `launched` and `exit_code`, from
    `ui.paths` constants. This is the writer half of that pair."""
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    meta = json.loads(meta_path(runs, run_id).read_text(encoding="utf-8"))
    assert meta[META_LAUNCHED_KEY] is True


def test_launch_sends_the_childs_stderr_to_the_sidecar(tmp_path, pack):
    """`/api/runs/{id}/stderr` is the only place a setup error the engine
    printed can be read from the browser."""
    runs = tmp_path / "runs"
    runs.mkdir()
    noisy = [sys.executable, "-c", "import sys; sys.stderr.write('boom\\n')"]
    made = launcher_spawning(noisy, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    made.reap()
    assert "boom" in (sidecar_dir(runs, run_id) / "stderr.log").read_text(
        encoding="utf-8")


def test_a_spawn_that_fails_leaves_a_run_that_reads_as_failed_to_start(tmp_path, pack):
    """`launched: false` is the only thing that distinguishes "the child never
    ran" from "the child ran and vanished"."""
    runs = tmp_path / "runs"
    runs.mkdir()

    def exploding_spawn(argv, *, env, stderr, cwd=None):
        raise OSError("no such executable")

    made = RunLauncher(runs, spawn=exploding_spawn)
    with pytest.raises(OSError):
        made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    metas = sorted((runs / ".evalyn-ui").glob("*/meta.json"))
    assert len(metas) == 1
    assert json.loads(metas[0].read_text(encoding="utf-8"))[META_LAUNCHED_KEY] is False


def test_a_failed_spawn_does_not_leave_the_launcher_wedged_as_busy(tmp_path, pack):
    """A launch that never started must not hold the one-run-at-a-time slot,
    or a single typo would end the demo with no way back."""
    runs = tmp_path / "runs"
    runs.mkdir()
    calls = {"n": 0}

    def spawn_once_then_work(argv, *, env, stderr, cwd=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("no such executable")
        return subprocess.Popen(INERT, env=env, stderr=stderr, start_new_session=True)

    made = RunLauncher(runs, spawn=spawn_once_then_work)
    with pytest.raises(OSError):
        made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    assert made.live is None
    made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)


# --------------------------------------------------------------------------
# 7. One run at a time, and the stale-lock question
# --------------------------------------------------------------------------

def test_a_second_launch_while_one_is_live_is_refused(tmp_path, pack):
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT_SLEEPER, runs)
    made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    try:
        with pytest.raises(Busy):
            made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    finally:
        made.live.process.kill()
        made.live.process.wait(timeout=60)


def test_the_slot_is_released_as_soon_as_the_child_exits(tmp_path, pack):
    """A lock that outlived its process would end the demo with no way to
    clear it. `reap` is called on the way into every launch, so a dead child
    can never block the next one."""
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    assert len(made.calls) == 2


def test_reap_records_the_exit_code_so_a_dead_run_stops_reading_as_live(tmp_path, pack):
    """`index.py:198-200` says it outright: a run whose child exited but whose
    exit code was never recorded is indistinguishable from a live one, and
    spins in the table forever."""
    runs = tmp_path / "runs"
    runs.mkdir()
    failing = [sys.executable, "-c", "raise SystemExit(3)"]
    made = launcher_spawning(failing, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    made.reap()
    meta = json.loads(meta_path(runs, run_id).read_text(encoding="utf-8"))
    assert meta[META_EXIT_CODE_KEY] == 3


def test_reap_leaves_a_still_running_child_alone(tmp_path, pack):
    """The discriminator for the test above: a `reap` that recorded an exit
    code unconditionally would satisfy it while killing the live readout."""
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT_SLEEPER, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    try:
        made.reap()
        assert made.live is not None
        meta = json.loads(meta_path(runs, run_id).read_text(encoding="utf-8"))
        assert meta[META_EXIT_CODE_KEY] is None
    finally:
        made.live.process.kill()
        made.live.process.wait(timeout=60)


# --------------------------------------------------------------------------
# 8. The control channel — a file, and nothing else
# --------------------------------------------------------------------------

@pytest.mark.parametrize("action", list(ControlAction))
def test_control_writes_the_action_the_engine_reads(tmp_path, action):
    """`index.py:571-577` reads `{"action": "<pause|resume|cancel>"}` into a
    `ControlAction`. This writes exactly that shape and nothing else."""
    runs = tmp_path / "runs"
    runs.mkdir()
    run_id = "20260811T000000000000-deadbeef-example"
    RunLauncher(runs).control(run_id, action)
    body = json.loads(control_path(runs / f"{run_id}.json").read_text(encoding="utf-8"))
    assert body == {"action": action.value}


def test_control_overwrites_the_previous_action(tmp_path):
    """Pause then resume must leave `resume`, not two actions or the first."""
    runs = tmp_path / "runs"
    runs.mkdir()
    run_id = "20260811T000000000000-deadbeef-example"
    made = RunLauncher(runs)
    made.control(run_id, ControlAction.pause)
    made.control(run_id, ControlAction.resume)
    body = json.loads(control_path(runs / f"{run_id}.json").read_text(encoding="utf-8"))
    assert body == {"action": "resume"}


def test_control_never_signals_the_child(tmp_path, pack, monkeypatch):
    """R4-11, pinned as a test rather than a comment.

    Signalling was measured and retracted: `SIGTERM` strands a completed,
    already-paid-for sample outside the Inspect log. The control file is the
    only mechanism, so a cancel must reach no signalling call at all.
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT_SLEEPER, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    signalled: list = []
    monkeypatch.setattr(os, "kill",
                        lambda *a, **k: signalled.append(a))
    monkeypatch.setattr(os, "killpg",
                        lambda *a, **k: signalled.append(a))
    monkeypatch.setattr(subprocess.Popen, "terminate",
                        lambda self: signalled.append("terminate"))
    monkeypatch.setattr(subprocess.Popen, "kill",
                        lambda self: signalled.append("kill"))
    try:
        made.control(run_id, ControlAction.cancel)
        made.reap()
        assert signalled == []
        assert made.live is not None      # still running: nothing killed it
    finally:
        monkeypatch.undo()
        made.live.process.kill()
        made.live.process.wait(timeout=60)


def test_the_default_spawn_puts_the_child_in_its_own_session(tmp_path):
    """`start_new_session=True`: a Ctrl-C in the terminal running `evalyn ui`
    sends `SIGINT` to the foreground process **group**, and a paid run in
    flight must not be in it.

    Driven against `spawn_child` — the production default — with an inert
    argv. Asserting this through an injected `spawn` would only have tested
    the injected one, which is to say nothing at all.
    """
    log = tmp_path / "stderr.log"
    with log.open("wb") as handle:
        proc = spawn_child(INERT_SLEEPER, env=os.environ.copy(), stderr=handle)
    try:
        assert os.getpgid(proc.pid) != os.getpgid(os.getpid())
    finally:
        proc.kill()
        proc.wait(timeout=60)


# --------------------------------------------------------------------------
# 9. The writer and the reader must agree about the suffix
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["gate", "compare", "discover"])
def test_the_reader_recovers_the_mode_from_the_id_the_launcher_minted(
        tmp_path, pack, mode):
    """`_MODE_SUFFIX` (the writer, in `cli.py`) and `mode_of` (the reader, in
    `ui/index.py`) are two separate tables. The launcher imports the writer's
    rather than keeping a third copy; this is the assertion that the two agree,
    so a suffix added to one and not the other fails here instead of producing
    runs the cockpit files under the wrong mode."""
    from evalyn.ui.index import mode_of

    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    body = {"run_id_a": "20260101T000000000000-aaaaaaaa-example",
            "run_id_b": "20260101T000000000001-bbbbbbbb-example"}
    run_id = made.launch(request_for(mode, **body), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    assert mode_of(run_id).value == mode


# --------------------------------------------------------------------------
# 10. R4-46 — every state this launcher can leave behind must still LIST
# --------------------------------------------------------------------------
#
# `RunIndex.list()` has no per-row guard where `get()` does, so one bad row
# 500s the whole run list — and the run list is the cockpit's first screen.
# The launcher introduces a second way to reach a partial row: a child that
# dies before writing an artifact leaves a `meta.json` and nothing else. Each
# case below is a state this launcher can genuinely produce.

def _list_ids(runs: Path) -> list[str]:
    from evalyn.ui.index import RunIndex
    return [row.run_id for row in RunIndex(runs).list()]


def test_r4_46_a_child_that_never_started_still_lists(tmp_path, pack):
    runs = tmp_path / "runs"
    runs.mkdir()

    def exploding_spawn(argv, *, env, stderr, cwd=None):
        raise OSError("no such executable")

    with pytest.raises(OSError):
        RunLauncher(runs, spawn=exploding_spawn).launch(
            request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    assert _list_ids(runs) == []      # no artifact, so no row — and no crash


def test_r4_46_a_child_that_died_instantly_still_lists(tmp_path, pack):
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning([sys.executable, "-c", "raise SystemExit(2)"], runs)
    made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    made.reap()
    assert _list_ids(runs) == []


def test_r4_46_a_half_written_meta_file_still_lists(tmp_path, pack):
    """A torn `meta.json` must degrade to `interrupted`, never raise inside
    `list()`. The launcher writes atomically so this should be unreachable —
    which is exactly why it is worth proving the reader survives it anyway."""
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    (runs / f"{run_id}.json").write_text('{"schema_version": 1, "probes": []}',
                                         encoding="utf-8")
    meta_path(runs, run_id).write_text('{"launched": tr', encoding="utf-8")
    assert _list_ids(runs) == [run_id]


def test_r4_46_an_artifact_that_is_truncated_still_lists(tmp_path, pack):
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    (runs / f"{run_id}.json").write_text("{", encoding="utf-8")
    assert _list_ids(runs) == [run_id]


def test_r4_46_an_events_file_with_no_artifact_still_lists(tmp_path, pack):
    """The documented "run died" shape (`ui/paths.py` module docstring): an
    events file with no artifact is evidence, not an error."""
    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    (runs / f"{run_id}.events.jsonl").write_text(
        '{"seq": 1, "type": "run.started", "data": {}}\n', encoding="utf-8")
    assert _list_ids(runs) == []


#: The five fields `ProbeResult` requires (`engine/run.py:33-38`). Named here
#: because the FIRST version of the test below omitted them: the artifact then
#: failed validation, `typed` was `None`, and the failure branch was
#: unreachable in every possible world. A tripwire that cannot fire is worse
#: than no tripwire, because it is read as protection.
REQUIRED_PROBE_FIELDS = {"id": "p", "category": "grounding", "kind": "probe",
                         "safety_critical": False, "samples": 1}

#: And the six `RunArtifact` requires. Both sets were introspected with
#: `dataclasses.fields(...)`, not remembered. Note there is **no**
#: `schema_version` and **no** per-probe `tier`: both are rejected as unexpected
#: keyword arguments, and either one alone is enough to make an artifact fail to
#: validate — which is how the original version of this test ended up proving
#: nothing while passing.
REQUIRED_ARTIFACT_FIELDS = {"pack_name": "example", "pack_hash": "0" * 8,
                            "judge_model": "mockllm/model",
                            "created_at": "2026-08-11T00:00:00+00:00",
                            "log_path": "logs/none.eval"}


def test_r4_46_a_non_dict_trial_record_still_breaks_the_run_list(tmp_path, pack):
    """The parked `list()` 500, pinned as it ACTUALLY behaves today.

    This asserts the bug, not the fix. `RunIndex.list()` has no per-row guard
    where `get()` does, so a probe whose `trial_records` holds a non-dict makes
    `capabilities_of` raise `AttributeError` and 500s the entire run list —
    the cockpit's first screen. R4-46 parks the guard as structural work, so
    this test's job is to be *honest* about the state of the tree, and to go
    red the moment somebody fixes it.

    **No Evalyn code path produces this artifact.** `ProbeResult.trial_records`
    is written only by the engine, one dict per scored epoch, and this task's
    launcher never writes artifact content at all — it is reachable only by
    hand-editing a file in `runs/`. That is why it is parked rather than urgent.

    When the guard lands: this test fails, and it should be inverted to assert
    the run lists with one degraded row.
    """
    from evalyn.ui.index import RunIndex

    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    (runs / f"{run_id}.json").write_text(json.dumps({
        **REQUIRED_ARTIFACT_FIELDS,
        "probes": [{**REQUIRED_PROBE_FIELDS,
                    "trial_records": ["not-a-dict"]}],
    }), encoding="utf-8")

    # The artifact must actually VALIDATE, or the branch is never reached and
    # this test proves nothing — which is precisely how its predecessor passed.
    assert RunIndex(runs)._load(runs / f"{run_id}.json", run_id,
                                RunMode.gate).typed is not None

    with pytest.raises(AttributeError):
        RunIndex(runs).list()


def test_the_vacuous_form_of_the_tripwire_would_not_have_reached_the_defect(
        tmp_path, pack):
    """The discriminator for the test above, and the reason it was rewritten.

    The original artifact carried only `id` and `tier`, and it failed for two
    independent reasons: `ProbeResult` requires five fields it did not have,
    **and** `tier` is not a `ProbeResult` field at all (it belongs to a check).
    Either alone is enough — `typed` stayed `None`, and `list()` returned a
    degraded row without ever touching `trial_records`. This pins that
    difference, so the fix cannot silently regress to the vacuous shape.
    """
    from evalyn.ui.index import RunIndex

    runs = tmp_path / "runs"
    runs.mkdir()
    made = launcher_spawning(INERT, runs)
    run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
    made.live.process.wait(timeout=60)
    (runs / f"{run_id}.json").write_text(json.dumps({
        **REQUIRED_ARTIFACT_FIELDS,
        "probes": [{"id": "p", "tier": 1, "trial_records": ["not-a-dict"]}],
    }), encoding="utf-8")

    assert RunIndex(runs)._load(runs / f"{run_id}.json", run_id,
                                RunMode.gate).typed is None
    assert [row.run_id for row in RunIndex(runs).list()] == [run_id]


# --------------------------------------------------------------------------
# 11. Atomicity — pinned as a mechanism, because it has no observable output
# --------------------------------------------------------------------------

def test_the_sidecar_files_are_written_by_rename_never_in_place(tmp_path, pack):
    """A mutation that wrote `meta.json` in place survived every other test
    here, and it would: torn writes cannot be raced deterministically, so
    atomicity has no output to assert on. It is pinned as the mechanism that
    makes the race impossible instead.

    It matters because `RunIndex._sidecar` reads these files from inside
    `list()` — the cockpit's first screen — which must never raise. A reader
    that catches a half-written `meta.json` degrades a perfectly healthy live
    run to `interrupted`, and a half-written control file is an action the
    operator watched succeed and that silently never happened.
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    renames: list[tuple[str, str]] = []
    real_replace = os.replace

    def recording_replace(src, dst):
        renames.append((str(src), str(dst)))
        return real_replace(src, dst)

    made = launcher_spawning(INERT, runs)
    original_write = Path.write_text
    direct: list[str] = []

    def recording_write(self, *args, **kwargs):
        direct.append(str(self))
        return original_write(self, *args, **kwargs)

    os.replace = recording_replace
    Path.write_text = recording_write          # type: ignore[method-assign]
    try:
        run_id = made.launch(request_for("gate"), pack=pack, pack_path=EXAMPLE_PACK)
        made.live.process.wait(timeout=60)
        made.control(run_id, ControlAction.cancel)
    finally:
        os.replace = real_replace
        Path.write_text = original_write        # type: ignore[method-assign]

    meta = str(meta_path(runs, run_id))
    control = str(control_path(runs / f"{run_id}.json"))
    landed = [dst for _, dst in renames]
    assert meta in landed
    assert control in landed
    # Every direct write went to a `.tmp`; neither final name was ever the
    # target of a write that a reader could have caught mid-flight.
    assert all(path.endswith(".tmp") for path in direct), direct
    assert meta not in direct
    assert control not in direct


# --------------------------------------------------------------------------
# 12. The endpoints — through the real app, over the real allowlist
# --------------------------------------------------------------------------
#
# `asgi_client` speaks ASGI in-process: no socket, no port, and no
# `fastapi.testclient` (which warns at import). Every app below has its
# launcher's spawn seam replaced with an inert child before any test can reach
# `POST /api/runs`, because the production seam would start a paid evaluation.

def cockpit(runs_dir: Path, *, allow_discover: bool = False,
            child: list[str] | None = None):
    """The real app over the real `packs/example`, with an inert child."""
    from evalyn.ui.server import create_app

    app = create_app(runs_dir, [EXAMPLE_PACK], allow_discover=allow_discover)
    spawned: list[dict] = []

    def spawn(argv, *, env, stderr, cwd=None):
        spawned.append({"argv": argv, "env": env})
        return subprocess.Popen(child or INERT, env=env, stderr=stderr,
                                start_new_session=True)

    app.state.launcher._spawn = spawn
    app.state.spawned = spawned
    app.state.sse_idle_timeout = 0.3
    return app


def launch_body(**overrides) -> dict:
    body = {"mode": "gate", "pack_id": pack_id_for("example"), "confirm": "example"}
    body.update(overrides)
    return body


def reap_app(app) -> None:
    live = app.state.launcher.live
    if live is not None:
        live.process.wait(timeout=60)
        app.state.launcher.reap()


# -- packs -----------------------------------------------------------------

async def test_packs_lists_the_allowlist_as_an_envelope(tmp_path, asgi_client):
    """An envelope, never a bare array — a top-level array cannot grow a
    field, and this is the list most likely to want one."""
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        response = await client.get("/api/packs")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "next_cursor"}
    assert body["next_cursor"] is None
    assert [row["name"] for row in body["items"]] == ["example"]
    assert body["items"][0]["probe_count"] > 0


async def test_a_pack_row_never_carries_a_usable_filesystem_path(tmp_path, asgi_client):
    """`PackRow.path` is a display label. Its own validator collapses `~`, and
    the id — the only thing that goes back to the server — is opaque."""
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        row = (await client.get("/api/packs")).json()["items"][0]
    assert str(Path.home()) not in row["path"]
    assert "/" not in row["id"]


async def test_the_pack_id_is_the_same_across_a_restart(tmp_path, asgi_client):
    """Two independently built apps — the closest in-process analogue of the
    server being stopped and started — must address the same pack by the same
    id, or a bookmarked launch URL silently names a different pack."""
    async with asgi_client(cockpit(tmp_path)) as client:
        first = (await client.get("/api/packs")).json()["items"][0]["id"]
    async with asgi_client(cockpit(tmp_path)) as client:
        second = (await client.get("/api/packs")).json()["items"][0]["id"]
    assert first == second


async def test_axes_reports_the_packs_own_ceiling_and_its_markdown_axes(
        tmp_path, asgi_client):
    app = cockpit(tmp_path)
    pack_id = pack_id_for("example")
    async with asgi_client(app) as client:
        response = await client.get(f"/api/packs/{pack_id}/axes")
    assert response.status_code == 200
    body = response.json()
    assert body["pack_id"] == pack_id
    # `packs/example/target.yaml` sets `max_usd_per_run: 1.00`.
    assert body["max_usd_per_run"] == 1.0
    assert body["personas"] == ["curious-auditor"]
    assert body["playbooks"] == ["trust-then-pivot"]
    assert body["objectives"]


async def test_axes_for_an_unknown_pack_is_a_not_found_envelope(tmp_path, asgi_client):
    async with asgi_client(cockpit(tmp_path)) as client:
        response = await client.get("/api/packs/pack-nope/axes")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# -- launch ----------------------------------------------------------------

async def test_launch_answers_202_with_the_run_id(tmp_path, asgi_client):
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        response = await client.post("/api/runs", json=launch_body())
    reap_app(app)
    assert response.status_code == 202
    assert set(response.json()) == {"run_id"}
    assert response.json()["run_id"].endswith("-example")


async def test_the_child_this_server_spawns_is_actually_told_to_poll_the_control_file(
        tmp_path, asgi_client):
    """T20-d(a), one layer above `build_argv`: the argv the *server* hands to
    `subprocess` is the one an operator's cancel depends on. Read off the spawn
    seam rather than off the function, because the seam is where the wiring
    pass caught it — `ps` on the real child showed no `--control`.
    """
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        response = await client.post("/api/runs", json=launch_body())
    reap_app(app)
    assert response.status_code == 202
    (spawned,) = app.state.spawned
    assert "--control" in spawned["argv"]


@pytest.mark.parametrize("body,because", [
    pytest.param(launch_body(pack_id="pack-nope"), "allowlist", id="unknown-pack"),
    pytest.param(launch_body(confirm="Example"), "confirm", id="wrong-confirm"),
    pytest.param(launch_body(mode="discover"), "--allow-discover", id="discover-not-allowed"),
])
async def test_the_three_refusals_are_all_launch_refused(tmp_path, asgi_client,
                                                         body, because):
    app = cockpit(tmp_path)                       # allow_discover=False
    async with asgi_client(app) as client:
        response = await client.post("/api/runs", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "launch_refused"
    assert because in response.json()["error"]["message"]
    assert app.state.spawned == [], "a refused launch must spawn nothing"


async def test_a_pack_path_in_the_body_is_refused_by_the_contract(tmp_path, asgi_client):
    """R4-5: `extra="forbid"` is the guard, not a hand-rolled path check.
    `LaunchRequest` has no path field, so a body carrying one is rejected
    upstream of the handler — which is why nothing in the handler looks."""
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        response = await client.post(
            "/api/runs", json=launch_body(target=str(EXAMPLE_PACK)))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "launch_refused"
    assert app.state.spawned == []


async def test_a_second_concurrent_launch_is_409_busy(tmp_path, asgi_client):
    app = cockpit(tmp_path, child=INERT_SLEEPER)
    async with asgi_client(app) as client:
        first = await client.post("/api/runs", json=launch_body())
        second = await client.post("/api/runs", json=launch_body())
    try:
        assert first.status_code == 202
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "busy"
        assert len(app.state.spawned) == 1
    finally:
        app.state.launcher.live.process.kill()
        reap_app(app)


async def test_the_launch_clamps_the_browsers_figure_down_to_the_packs_ceiling(
        tmp_path, asgi_client):
    """End-to-end §10.4: the pack's ceiling is 1.00, the browser asks for 99."""
    app = cockpit(tmp_path, allow_discover=True)
    async with asgi_client(app) as client:
        response = await client.post(
            "/api/runs", json=launch_body(mode="discover", max_usd=99.0))
    reap_app(app)
    assert response.status_code == 202
    argv = app.state.spawned[0]["argv"]
    assert argv[argv.index("--max-usd") + 1] == "1.0"
    assert "99.0" not in argv


async def test_a_figure_under_the_ceiling_is_not_raised_to_meet_it(
        tmp_path, asgi_client):
    app = cockpit(tmp_path, allow_discover=True)
    async with asgi_client(app) as client:
        response = await client.post(
            "/api/runs", json=launch_body(mode="discover", max_usd=0.25))
    reap_app(app)
    assert response.status_code == 202
    argv = app.state.spawned[0]["argv"]
    assert argv[argv.index("--max-usd") + 1] == "0.25"


async def test_the_launched_run_id_is_the_stem_of_the_artifact_that_appears(
        tmp_path, asgi_client):
    """§10.5, through the real endpoint: the id in the 202 body and the stem of
    the file that later lands are the same string."""
    writer = [sys.executable, "-c",
              "import os, pathlib; "
              "pathlib.Path(os.environ['OUT'], os.environ['EVALYN_RUN_ID'] + '.json')"
              ".write_text('{\"schema_version\": 1, \"probes\": []}')"]
    app = cockpit(tmp_path, child=writer)
    os.environ["OUT"] = str(tmp_path)
    try:
        async with asgi_client(app) as client:
            response = await client.post("/api/runs", json=launch_body())
        reap_app(app)
    finally:
        del os.environ["OUT"]
    run_id = response.json()["run_id"]
    assert (tmp_path / f"{run_id}.json").exists()
    async with asgi_client(app) as client:
        detail = await client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run_id


# -- the live detail, which is the demo's own path -------------------------

async def test_a_launched_run_has_a_detail_before_any_artifact_exists(
        tmp_path, asgi_client):
    """**The demo path.** The launch console navigates to `/runs/<id>` the
    moment the 202 lands, and the artifact does not exist until the run
    finishes. A 404 here makes the SPA render its "could not be read" alarm
    over a healthy live run — and it never recovers, because the query client
    does not retry and the only thing that would invalidate the query lives
    inside the live panel, which never mounts.
    """
    app = cockpit(tmp_path, child=INERT_SLEEPER)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        detail = await client.get(f"/api/runs/{run_id}")
    try:
        assert not (tmp_path / f"{run_id}.json").exists()
        assert detail.status_code == 200
        body = detail.json()
        assert body["run_id"] == run_id
        assert body["status"] == "running"
        assert body["pack_name"] == "example"
        assert body["capabilities"] == {"transcripts": False, "trial_records": False,
                                        "hard_metrics": False}
    finally:
        app.state.launcher.live.process.kill()
        reap_app(app)


async def test_a_run_this_cockpit_never_launched_is_still_a_real_404(
        tmp_path, asgi_client):
    """The discriminator: the pending-detail fallback must not turn every
    unknown id into a 200."""
    async with asgi_client(cockpit(tmp_path)) as client:
        response = await client.get("/api/runs/20260101T000000000000-deadbeef-nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_launched_run_that_died_reads_as_interrupted_not_running(
        tmp_path, asgi_client):
    app = cockpit(tmp_path, child=[sys.executable, "-c", "raise SystemExit(2)"])
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        reap_app(app)
        detail = await client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "interrupted"


# -- control ---------------------------------------------------------------

@pytest.mark.parametrize("action", ["pause", "resume", "cancel"])
async def test_control_answers_202_and_writes_the_file(tmp_path, asgi_client, action):
    app = cockpit(tmp_path, child=INERT_SLEEPER)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        response = await client.post(f"/api/runs/{run_id}/control",
                                     json={"action": action})
    try:
        assert response.status_code == 202
        assert response.json() == {"run_id": run_id, "accepted": True}
        body = json.loads(
            control_path(tmp_path / f"{run_id}.json").read_text(encoding="utf-8"))
        assert body == {"action": action}
    finally:
        app.state.launcher.live.process.kill()
        reap_app(app)


async def test_control_on_an_unknown_run_is_404(tmp_path, asgi_client):
    async with asgi_client(cockpit(tmp_path)) as client:
        response = await client.post(
            "/api/runs/20260101T000000000000-deadbeef-nope/control",
            json={"action": "cancel"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_control_refuses_an_action_that_is_not_in_the_closed_set(
        tmp_path, asgi_client):
    app = cockpit(tmp_path, child=INERT_SLEEPER)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        response = await client.post(f"/api/runs/{run_id}/control",
                                     json={"action": "stop"})
    try:
        assert response.status_code == 422
        assert not control_path(tmp_path / f"{run_id}.json").exists()
    finally:
        app.state.launcher.live.process.kill()
        reap_app(app)


# -- events and stderr -----------------------------------------------------

async def test_events_serves_a_finished_stream_with_the_sse_headers(
        tmp_path, asgi_client):
    """Over a stream that already ends in `run.finished`, so it terminates by
    construction — `httpx.ASGITransport` buffers the whole body before it
    returns, so a non-terminating stream here would deadlock the suite."""
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        reap_app(app)
        (tmp_path / f"{run_id}.events.jsonl").write_text(
            json.dumps({"seq": 1, "type": "run.started", "data": {"mode": "gate"}})
            + "\n"
            + json.dumps({"seq": 2, "type": "run.finished", "data": {"exit_code": 0}})
            + "\n", encoding="utf-8")
        response = await client.get(f"/api/runs/{run_id}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-cache" in response.headers["cache-control"]
    assert response.text.startswith("id: 1\nevent: run.started\n")
    assert "event: run.finished" in response.text


async def test_events_honours_last_event_id(tmp_path, asgi_client):
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        reap_app(app)
        (tmp_path / f"{run_id}.events.jsonl").write_text(
            json.dumps({"seq": 1, "type": "run.started", "data": {}}) + "\n"
            + json.dumps({"seq": 2, "type": "run.finished", "data": {}}) + "\n",
            encoding="utf-8")
        response = await client.get(f"/api/runs/{run_id}/events",
                                    headers={"Last-Event-ID": "1"})
    assert "id: 1" not in response.text
    assert "id: 2" in response.text


async def test_events_for_an_unknown_run_is_404(tmp_path, asgi_client):
    async with asgi_client(cockpit(tmp_path)) as client:
        response = await client.get(
            "/api/runs/20260101T000000000000-deadbeef-nope/events")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_stderr_serves_what_the_child_printed(tmp_path, asgi_client):
    noisy = [sys.executable, "-c",
             "import sys; sys.stderr.write('evalyn gate: setup error: nope\\n')"]
    app = cockpit(tmp_path, child=noisy)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        reap_app(app)
        response = await client.get(f"/api/runs/{run_id}/stderr")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "setup error: nope" in response.text


async def test_stderr_for_a_run_this_cockpit_never_launched_is_404(
        tmp_path, asgi_client):
    async with asgi_client(cockpit(tmp_path)) as client:
        response = await client.get(
            "/api/runs/20260101T000000000000-deadbeef-nope/stderr")
    assert response.status_code == 404


# --------------------------------------------------------------------------
# 13. The stream's WIRING — proved at the endpoint, not only in the generator
# --------------------------------------------------------------------------
#
# Both tests below exist because a mutation survived without them. The stream
# module's own suite proves `scrub=` and `is_disconnected=` behave correctly
# *when passed*; nothing proved the endpoint passes them, so deleting either
# argument from `server.py` left the whole suite green.

async def test_the_events_endpoint_scrubs_through_the_apps_redactor(
        tmp_path, asgi_client):
    """The one `/api` route the chokepoint does not cover.

    `_scrub_response` returns a `StreamingResponse` untouched — "streaming,
    file, or empty: not ours" — so `RedactingRoute` sitting on this route
    protects nothing. If the endpoint forgets to pass the redactor, a token in
    an event payload goes to the projector verbatim.
    """
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        reap_app(app)
        (tmp_path / f"{run_id}.events.jsonl").write_text(
            json.dumps({"seq": 1, "type": "turn.received",
                        "data": {"text": "key AKIAIOSFODNN7EXAMPLE here"}}) + "\n"
            + json.dumps({"seq": 2, "type": "run.finished", "data": {}}) + "\n",
            encoding="utf-8")
        response = await client.get(f"/api/runs/{run_id}/events")
    assert "AKIAIOSFODNN7EXAMPLE" not in response.text
    assert "«redacted:token»" in response.text


async def test_the_events_endpoint_hands_the_stream_a_disconnect_check(
        tmp_path, asgi_client, monkeypatch):
    """Wiring, asserted as wiring.

    The leak this prevents is invisible in a buffered test client: starlette
    only notices a dead client when it next tries to write, and an idle run
    writes nothing, so an abandoned tab survives until the idle timeout. What
    the endpoint owes the stream is the check itself — the behaviour behind it
    is covered in `test_stream.py`.
    """
    from evalyn.ui import server as server_mod

    seen: dict = {}
    real = server_mod.event_stream

    def recording(path, **kwargs):
        seen.update(kwargs)
        return real(path, **kwargs)

    monkeypatch.setattr(server_mod, "event_stream", recording)
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        reap_app(app)
        (tmp_path / f"{run_id}.events.jsonl").write_text(
            json.dumps({"seq": 1, "type": "run.finished", "data": {}}) + "\n",
            encoding="utf-8")
        await client.get(f"/api/runs/{run_id}/events")
    assert callable(seen.get("is_disconnected"))
    assert callable(seen.get("scrub"))
    assert seen.get("idle_timeout") == app.state.sse_idle_timeout


# --------------------------------------------------------------------------
# 14. Control may not rewrite a finished run's verdict (I-1)
# --------------------------------------------------------------------------
#
# `derive_status` puts `control is cancel` ABOVE the artifact, so a control
# file written after a run completes relabels a `passed` run `cancelled` — in
# the detail view, in the run list, and on disk. On stage that means clicking
# Cancel a moment too late silently rewrites a real result.

#: An artifact that validates and passes, written by the inert child so a run
#: can genuinely FINISH inside a test.
PASSING_ARTIFACT = {
    "pack_name": "example", "pack_hash": "0" * 8, "judge_model": "mockllm/model",
    "created_at": "2026-08-11T00:00:00+00:00", "log_path": "logs/none.eval",
    "probes": [{"id": "grounding", "category": "grounding", "kind": "probe",
                "safety_critical": False, "samples": 1, "trials": 1,
                "expected_trials": 1, "pass_at_k": 1.0, "pass_k": 1.0}],
}


def artifact_writing_child() -> list[str]:
    return [sys.executable, "-c",
            "import json, os, pathlib;"
            "pathlib.Path(os.environ['OUT'], os.environ['EVALYN_RUN_ID'] + '.json')"
            ".write_text(os.environ['ART'])"]


async def test_cancelling_a_finished_run_cannot_rewrite_its_verdict(
        tmp_path, asgi_client):
    """The one the reviewer said to fix before the 14th.

    A completed evaluation's result must not be changeable by a UI click. The
    refusal is a 409 — the request conflicts with the resource's state — which
    maps to the frozen `busy` code; the message is what the operator reads.
    """
    app = cockpit(tmp_path, child=artifact_writing_child())
    os.environ["OUT"] = str(tmp_path)
    os.environ["ART"] = json.dumps(PASSING_ARTIFACT)
    try:
        async with asgi_client(app) as client:
            run_id = (await client.post("/api/runs",
                                        json=launch_body())).json()["run_id"]
            reap_app(app)
            before = (await client.get(f"/api/runs/{run_id}")).json()
            assert before["status"] == "passed", before["status"]

            response = await client.post(f"/api/runs/{run_id}/control",
                                         json={"action": "cancel"})
            after = (await client.get(f"/api/runs/{run_id}")).json()
            rows = (await client.get("/api/runs")).json()["items"]
    finally:
        del os.environ["OUT"], os.environ["ART"]

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "busy"
    # The verdict, in all three places the reviewer found it rewritten.
    assert after["status"] == "passed"
    assert after["cancelled"] is False
    assert [row["status"] for row in rows] == ["passed"]
    # And nothing was left on disk to rewrite it later.
    assert not control_path(tmp_path / f"{run_id}.json").exists()


async def test_a_control_action_on_a_run_whose_child_exited_is_refused(
        tmp_path, asgi_client):
    """The second half of the liveness rule: a recorded `exit_code` means the
    child is gone, even when it never wrote an artifact."""
    app = cockpit(tmp_path, child=[sys.executable, "-c", "raise SystemExit(1)"])
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        reap_app(app)
        response = await client.post(f"/api/runs/{run_id}/control",
                                     json={"action": "cancel"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "busy"
    assert not control_path(tmp_path / f"{run_id}.json").exists()


@pytest.mark.parametrize("action", ["pause", "resume", "cancel"])
async def test_a_run_that_is_still_in_flight_still_takes_every_action(
        tmp_path, asgi_client, action):
    """The discriminator. A liveness check that refused everything would
    satisfy the tests above while making the cockpit's controls dead."""
    app = cockpit(tmp_path, child=INERT_SLEEPER)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        response = await client.post(f"/api/runs/{run_id}/control",
                                     json={"action": action})
    try:
        assert response.status_code == 202
        assert json.loads(control_path(tmp_path / f"{run_id}.json")
                          .read_text(encoding="utf-8")) == {"action": action}
    finally:
        app.state.launcher.live.process.kill()
        reap_app(app)


async def test_a_run_launched_elsewhere_with_no_result_yet_still_takes_control(
        tmp_path, asgi_client):
    """A run this cockpit did not launch, with no artifact and no recorded exit
    code, may genuinely be alive in another process — and the control file is
    the only way to reach it. Nothing is at risk: there is no result to
    overwrite. Refusing here would make the guard over-broad."""
    app = cockpit(tmp_path)
    run_id = "20260811T000000000000-deadbeef-example"
    sidecar_dir(tmp_path, run_id).mkdir(parents=True)
    async with asgi_client(app) as client:
        response = await client.post(f"/api/runs/{run_id}/control",
                                     json={"action": "cancel"})
    assert response.status_code == 202
    assert control_path(tmp_path / f"{run_id}.json").exists()


# --------------------------------------------------------------------------
# 15. M-1 — the event NAME reaches the wire too
# --------------------------------------------------------------------------

async def test_the_events_endpoint_scrubs_the_event_name_not_only_the_payload(
        tmp_path, asgi_client):
    """`event: <type>` goes out as literally as `data:` does.

    Scrubbing only the payload left a secret in the event name verbatim on the
    one route that is on screen during a live run. Unreachable from today's
    emit sites, which is why it is a name and not a payload — and exactly why
    it would have gone unnoticed.
    """
    app = cockpit(tmp_path)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        reap_app(app)
        (tmp_path / f"{run_id}.events.jsonl").write_text(
            json.dumps({"seq": 1, "type": "turn.AKIAIOSFODNN7EXAMPLE",
                        "data": {}}) + "\n"
            + json.dumps({"seq": 2, "type": "run.finished", "data": {}}) + "\n",
            encoding="utf-8")
        response = await client.get(f"/api/runs/{run_id}/events")
    assert "AKIAIOSFODNN7EXAMPLE" not in response.text
    assert "«redacted:token»" in response.text
    # The resume cursor is an integer and survives redaction untouched — a
    # scrubbed `id:` would break `Last-Event-ID` resumption for the whole run.
    assert "id: 1\n" in response.text
    assert "id: 2\n" in response.text


# --------------------------------------------------------------------------
# 16. M-2 — containment outranks the pending-detail fallback
# --------------------------------------------------------------------------

async def test_a_symlink_escaping_the_runs_directory_is_still_refused(
        tmp_path, asgi_client):
    """R4-7's braces. `_resolved_artifact` 404s a symlink that resolves outside
    `runs/`, and that arm is a containment control — it must not sit behind a
    convenience fallback that answers for the same id. The run below has a
    sidecar directory, so the pending view would gladly claim it.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    runs = tmp_path / "runs"
    runs.mkdir()
    app = cockpit(runs)
    run_id = "20260811T000000000000-deadbeef-example"
    sidecar_dir(runs, run_id).mkdir(parents=True)
    (outside / "secret.json").write_text(json.dumps(PASSING_ARTIFACT),
                                         encoding="utf-8")
    (runs / f"{run_id}.json").symlink_to(outside / "secret.json")

    async with asgi_client(app) as client:
        response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# The two liveness arms are mutually redundant for a run that finished BEFORE
# the request, so neither of the tests above can tell them apart: remove either
# one alone and they both still pass. These two separate them.

async def test_a_finished_run_never_has_a_control_file_written_at_all(
        tmp_path, asgi_client):
    """Pins the arm BEFORE the write.

    With only the post-write arm, a refused cancel still momentarily writes a
    real cancel file into `runs/` and then deletes it. Nothing should be
    written for a run that is already over — the refusal must happen before the
    filesystem is touched, not be repaired afterwards.
    """
    app = cockpit(tmp_path, child=artifact_writing_child())
    os.environ["OUT"] = str(tmp_path)
    os.environ["ART"] = json.dumps(PASSING_ARTIFACT)
    calls: list = []
    real_control = app.state.launcher.control
    app.state.launcher.control = lambda *a, **k: calls.append(a) or real_control(*a, **k)
    try:
        async with asgi_client(app) as client:
            run_id = (await client.post("/api/runs",
                                        json=launch_body())).json()["run_id"]
            reap_app(app)
            response = await client.post(f"/api/runs/{run_id}/control",
                                         json={"action": "cancel"})
    finally:
        del os.environ["OUT"], os.environ["ART"]
    assert response.status_code == 409
    assert calls == [], "a finished run must not reach the control writer"


async def test_a_run_that_finishes_DURING_the_write_has_its_file_removed(
        tmp_path, asgi_client):
    """Pins the arm AFTER the write — the race the first arm cannot close.

    A run can finish between the liveness check and the write. Here that is
    forced rather than hoped for: the artifact lands *inside* `control()`, so
    the pre-write check sees a live run, the file is written, and only the
    second check can notice that what was just written would now rewrite a
    finished run's verdict.
    """
    app = cockpit(tmp_path, child=INERT_SLEEPER)
    async with asgi_client(app) as client:
        run_id = (await client.post("/api/runs", json=launch_body())).json()["run_id"]
        real_control = app.state.launcher.control

        def control_then_finish(rid, action):
            real_control(rid, action)
            # The run completes in the window: its artifact appears.
            (tmp_path / f"{rid}.json").write_text(json.dumps(PASSING_ARTIFACT),
                                                 encoding="utf-8")

        app.state.launcher.control = control_then_finish
        try:
            response = await client.post(f"/api/runs/{run_id}/control",
                                         json={"action": "cancel"})
            detail = await client.get(f"/api/runs/{run_id}")
        finally:
            app.state.launcher.live.process.kill()
            reap_app(app)

    assert response.status_code == 409
    assert not control_path(tmp_path / f"{run_id}.json").exists(), \
        "the file written inside the race window was left on disk"
    assert detail.json()["status"] == "passed"
    assert detail.json()["cancelled"] is False
