"""Starting a run from the browser, and the control file (Plan #4, Task 20).

This module is the one place in Evalyn that **starts something that spends
money**, so almost everything here is about refusing to.

## The shape of a launch

`POST /api/runs` carries a `pack_id` and nothing else that names a pack —
`LaunchRequest` has no path field and `extra="forbid"` rejects a body that
invents one, so a browser can only ever name a pack the operator put on the
command line with `--target`. `confirm` must echo that pack's name, which is
what stops a drive-by `curl` from starting spend.

## `sys.executable -m evalyn`, not `evalyn`

The console script is only on `PATH` when the venv's scripts directory is, which
is true for an operator who activated it and false for a server started by an
IDE or a supervisor. `sys.executable` is by definition the interpreter already
running this server. See `evalyn/__main__.py`.

## Cancelling never signals the child (R4-11)

Writing the control file is the **only** mechanism. Signalling was implemented,
measured and retracted: `SIGTERM` leaves a partial log at `status='started'`
that `run.py:388-389` rejects, **and strands a completed, already-paid-for
sample inside Inspect's buffer, outside the log** — money spent, evidence gone.
`SIGINT` is no better: `inspect_eval` then returns zero logs and `run.py:387`'s
`logs[0]` raises. An action the run never acknowledges is left as an honest
`interrupted` run that names its pid, and killing a run stays something a person
does deliberately in their own terminal.

## One run at a time, and why the lock cannot go stale

PRODUCT.md fixes one run at a time per `runs/` directory. That guard lives
**in memory**, in `RunLauncher.live`, and deliberately not on disk:

* a killed server takes the lock with it, so a crash can never wedge the cockpit
  into refusing every future launch — which, on a stage, would be unrecoverable;
* within a process, `reap()` runs on the way into every launch, so a child that
  has exited releases the slot before anyone can be told the server is busy.

The cost is that the on-disk `running` status is **advisory**: a run started
from a terminal, or by a previous server, does not block a launch here. That is
the deliberate trade — an over-strict guard's failure mode (a demo that cannot
start) is far worse than this one's (two runs the operator chose to start).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalyn.cli import RUN_ID_ENV, _MODE_SUFFIX
from evalyn.engine.run import new_run_id
from evalyn.targets.loader import Pack
from evalyn.ui.models import (
    ControlAction,
    LaunchRequest,
    PackAxes,
    PackRow,
    RunMode,
)
from evalyn.ui.paths import (
    META_EXIT_CODE_KEY,
    META_LAUNCHED_KEY,
    control_path,
    meta_path,
    sidecar_dir,
)

__all__ = ["build_argv", "clamp_max_usd", "refusal_for", "pack_id_for",
           "pack_rows", "pack_axes", "RunLauncher", "Busy", "LaunchRefused",
           "LiveRun", "spawn_child", "STDERR_FILENAME"]

#: The child's stderr, inside `runs/.evalyn-ui/<run_id>/`. Served by
#: `GET /api/runs/{id}/stderr` — for a run that died before writing an
#: artifact, it is the only place the reason exists.
STDERR_FILENAME = "stderr.log"


class Busy(Exception):
    """A run is already in flight in this `runs/` directory."""


class LaunchRefused(Exception):
    """Well-formed, and this server will not start it."""


@dataclass
class LiveRun:
    """The one child this server is currently supervising."""

    #: The **artifact stem**, mode suffix included. Everything the cockpit
    #: keys by — the sidecar directory, the URL, the SSE subscription — uses
    #: this, because it is the only spelling that round-trips to a file.
    run_id: str
    #: The engine's own id, **without** the suffix. This is what goes into the
    #: child's `EVALYN_RUN_ID`; the engine appends the suffix itself when it
    #: composes `out_dir/<run_id><suffix>.json`.
    engine_run_id: str
    mode: RunMode
    #: The pack's own name, so the detail view of a run with no artifact yet
    #: can still say what is running without re-reading the allowlist.
    pack_name: str
    pid: int
    process: subprocess.Popen
    stderr_handle: Any


# --------------------------------------------------------------------------
# Packs — the start-time allowlist, addressed by an id that is never a path
# --------------------------------------------------------------------------

def pack_id_for(name: str) -> str:
    """A stable, opaque id for the pack called *name*.

    **Why a digest of the name rather than the allowlist position.** The
    contract calls `PackRow.id` "an index into that allowlist, never a path"
    (`models.py:849-853`), and `pack-0` would satisfy that reading. It is the
    weaker choice: a position is stable only while the command line is, so
    adding one `--target` silently renumbers every pack, and an id a browser
    still holds then names a *different* pack than it did a minute ago.

    Deriving it from the pack's own name instead makes it stable across a
    restart, across `--target` being reordered or extended, across the
    operator's cwd changing, and across the pack directory being moved — none
    of which change which pack the operator means. It is not reversible to a
    path, and it is `[a-z0-9-]` so it needs no escaping as a path parameter.

    Two allowlisted packs sharing a name would collide, but they already cannot
    be told apart by `confirm`, which is the pack's name — so that ambiguity
    belongs to the contract, not to this scheme.
    """
    return "pack-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]


def pack_rows(packs: dict[str, tuple[Pack, Path]]) -> list[PackRow]:
    """`GET /api/packs` — the allowlist as the launch screen reads it.

    `version` is `None` because `TargetSpec` has no version field; inventing
    one from the directory name would be a number nobody set. `path` goes
    through `PackRow`'s own `display_path` validator, so what reaches the
    browser is a `~`-collapsed label and not a usable filesystem path.
    """
    rows = []
    for pack_id, (pack, path) in packs.items():
        rows.append(PackRow(
            id=pack_id,
            name=pack.spec.name,
            path=str(path),
            probe_count=len(pack.probes),
            has_calibration=(Path(pack.root) / "calibration.json").is_file(),
        ))
    return rows


def pack_axes(pack_id: str, pack: Pack) -> PackAxes:
    """`GET /api/packs/{pack_id}/axes` — what a `discover` launch may select.

    The three axes do not come from one place, which is easy to get wrong:
    **objectives are a global registry** (`discovery/objectives.py`), while
    personas and playbooks are markdown files under the pack root, falling back
    to one built-in each when the directories are absent.
    """
    from evalyn.discovery.objectives import OBJECTIVES
    from evalyn.discovery.personas import load_personas, load_playbooks

    return PackAxes(
        pack_id=pack_id,
        objectives=list(OBJECTIVES),
        personas=sorted(load_personas(pack)),
        playbooks=sorted(load_playbooks(pack)),
        max_usd_per_run=pack.spec.budget.max_usd_per_run,
    )


# --------------------------------------------------------------------------
# The two pure policy decisions
# --------------------------------------------------------------------------

def clamp_max_usd(requested: float | None, cap: float) -> float | None:
    """`min(requested, cap)` — with the one case that is not that.

    **`cap == 0` means the pack disabled its ceiling, not that it set one of
    zero** (`targets/schema.py:112-124`: "0 disables the check"). The CLI flag
    means the opposite at the same value: `--max-usd 0` is "spend nothing", and
    `cli.py:576-586` refuses it outright with exit 2 rather than ship that
    ambiguity. So a naive `min(request, 0)` would take the pack that asked for
    *no* limit and turn every launch against it into a child that exits 2
    before it starts. An uncapped pack therefore clamps against nothing and the
    request passes through.

    `None` stays `None`: the browser did not ask for a ceiling, so the CLI
    resolves the pack's own — raising it to `cap` here would spend up to the
    pack maximum on a request that named no figure at all.
    """
    if requested is None:
        return None
    if cap <= 0:
        return requested
    return min(requested, cap)


def refusal_for(request: LaunchRequest, *, pack: Pack | None,
                allow_discover: bool) -> str | None:
    """The sentence to refuse this launch with, or `None` to allow it.

    Pure, and it returns prose rather than a code because every one of these
    lands on a screen in front of an audience: the operator has to be able to
    read what went wrong and fix it without leaving the page. All of them map
    to `launch_refused`.
    """
    if pack is None:
        return ("no such pack: that id is not in the allowlist this server was "
                "started with (see `evalyn ui --target`)")
    if request.confirm != pack.spec.name:
        return (f"confirm must echo the pack's name exactly to start a run that "
                f"spends money — expected {pack.spec.name!r}")
    if request.mode is RunMode.discover:
        if not allow_discover:
            return ("discover spends real money on an agent as well as a judge, "
                    "and this server was not started with --allow-discover")
        if request.max_usd is not None and request.max_usd <= 0:
            return ("a max_usd of 0 would refuse every hunt before it starts; "
                    "leave it unset to use the pack's own ceiling")
    if request.mode is RunMode.compare and not (request.run_id_a and request.run_id_b):
        return "compare needs two finished gate runs: run_id_a and run_id_b"
    return None


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------

def build_argv(request: LaunchRequest, *, pack_path: Path, runs_dir: Path,
               max_usd: float | None = None,
               judge_model: str | None = None) -> list[str]:
    """The child's argv. Pure — no filesystem, no process, no clock.

    *max_usd* is the **already-clamped** ceiling and is passed in rather than
    read off *request*, so the clamp cannot be skipped by a caller who forgot
    it: this function has no way to reach the browser's raw figure.

    *judge_model* is the operator's `evalyn ui --judge-model`, and it is
    likewise passed in rather than read off *request*: the browser has no say
    in which judge a run bills against.

    **`None` must stay silent.** Omitting the flag is not the same as passing
    an empty one — the child's own default is `mockllm/model`, which costs
    nothing and scores `classifier` checks UNSURE, and that free path is how
    this cockpit is exercised end to end without spending. Only `gate` and
    `discover` accept `--judge-model`; `compare` does not, so handing it one
    would kill the child with a usage error rather than configure a judge.

    `--events` is not optional. Without it `_open_sink` constructs no sink and
    writes no file (`cli.py:52-78`), and the cockpit's live panel would tail
    something that never appears — a run that looks frozen while it is in fact
    running perfectly.

    `--control` is not optional either, and for the harsher version of the same
    reason. It defaults to `False` on all three modes, and off means the child
    never opens the control file: `_open_control` returns `(None, run_id)` and
    every poll point is skipped. `RunLauncher.control` would still write the
    file and the endpoint would still answer `202 accepted: True`, because the
    202 only claims the file was written — so the operator gets an
    acknowledgement for an action nothing on the other end can perform. That
    was measured, not reasoned about: a cancel at t+0.44s left the child alive
    through all 12 trials, with zero `control.*` events in the stream. The flag
    is unconditional here because it is the *cockpit's* channel; a run started
    from a terminal still defaults to off, which is what keeps a stale file
    from steering a run nobody is supervising (`cli.py:_open_control`).
    """
    mode = RunMode(request.mode).value
    argv = [sys.executable, "-m", "evalyn", mode,
            "--target", str(pack_path),
            "--out-dir", str(runs_dir),
            "--events", "--control"]
    if request.allow_uncalibrated:
        argv.append("--allow-uncalibrated")

    if mode == RunMode.gate.value:
        if judge_model:
            argv += ["--judge-model", judge_model]
        # Omitted rather than passed empty: the CLI's own default is
        # `runs/baseline.json`, and `--baseline ""` would defeat it.
        if request.baseline_run_id:
            argv += ["--baseline", str(Path(runs_dir) / f"{request.baseline_run_id}.json")]
    elif mode == RunMode.compare.value:
        argv += ["--a", str(Path(runs_dir) / f"{request.run_id_a}.json"),
                 "--b", str(Path(runs_dir) / f"{request.run_id_b}.json")]
    elif mode == RunMode.discover.value:
        if judge_model:
            argv += ["--judge-model", judge_model]
        # One flag per objective: `--objective` is `list[str]` on the CLI, so a
        # comma-joined value would be read as one objective named "a,b" and
        # refused by `DiscoveryConfig`'s known-objective check.
        for objective in request.objectives:
            argv += ["--objective", objective]
        if max_usd is not None:
            argv += ["--max-usd", str(max_usd)]
    return argv


def spawn_child(argv: list[str], *, env: dict, stderr, cwd=None) -> subprocess.Popen:
    """Start the child. The production default behind `RunLauncher(spawn=...)`.

    `start_new_session=True` puts it in its own process group, so a `Ctrl-C` in
    the terminal running `evalyn ui` — which delivers `SIGINT` to the whole
    foreground group — cannot reach a paid run in flight.

    `stdout` is discarded and `stderr` is kept: the CLI prints its human report
    to stdout, which the artifact already carries losslessly, while every setup
    error and warning goes to stderr through `typer.echo(..., err=True)`. That
    is what `GET /api/runs/{id}/stderr` exists to show, and for a run that died
    before writing an artifact it is the only surviving explanation.

    `stdin` is closed so a child that somehow prompts fails instead of hanging
    a run forever on a terminal nobody is watching.
    """
    return subprocess.Popen(
        argv, env=env, stderr=stderr,
        stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        cwd=cwd, start_new_session=True, close_fds=True)


# --------------------------------------------------------------------------
# The launcher
# --------------------------------------------------------------------------

class RunLauncher:
    """Owns the single child process this server may have running."""

    def __init__(self, runs_dir: Path, *, spawn=spawn_child,
                 judge_model: str | None = None) -> None:
        self.runs_dir = Path(runs_dir)
        self._spawn = spawn
        #: The operator's `evalyn ui --judge-model`, or `None` for the child's
        #: own free `mockllm/model`. Start-time, never request-time: a browser
        #: cannot choose what a run bills against.
        self.judge_model = judge_model
        #: `None` when nothing is in flight. See the module docstring for why
        #: this is in memory and not on disk.
        self.live: LiveRun | None = None

    # -- launch ------------------------------------------------------------

    def launch(self, request: LaunchRequest, *, pack: Pack,
               pack_path: Path) -> str:
        """Start a run and return the id the artifact will later be written at.

        The id is minted **before** the process exists, which is what lets the
        SPA subscribe to `/events` off the 202 instead of polling `runs/` for a
        file to appear (`models.py:967-975`). `new_run_id` is the engine's own
        minting, reused rather than reimplemented, so the id carries the same
        microsecond stamp and uuid that make two runs unable to clobber one
        another.
        """
        self.reap()
        if self.live is not None:
            raise Busy(
                f"a run is already in flight in this runs directory "
                f"(pid {self.live.pid}); one run at a time")

        engine_run_id = new_run_id(pack.spec.name)
        run_id = engine_run_id + _MODE_SUFFIX[RunMode(request.mode).value]
        max_usd = clamp_max_usd(request.max_usd, pack.spec.budget.max_usd_per_run)
        argv = build_argv(request, pack_path=pack_path, runs_dir=self.runs_dir,
                          max_usd=max_usd, judge_model=self.judge_model)

        directory = sidecar_dir(self.runs_dir, run_id)
        directory.mkdir(parents=True, exist_ok=True)
        # Written BEFORE the spawn, saying the child has not started. If the
        # spawn raises, that is what stays on disk and `derive_status` reports
        # `failed_to_start` — the one state that distinguishes "never ran" from
        # "ran and vanished". Rewritten to `launched: True` only once there is
        # actually a process.
        self._write_meta(run_id, launched=False, exit_code=None)

        env = {**os.environ, RUN_ID_ENV: engine_run_id}
        handle = (directory / STDERR_FILENAME).open("ab")
        try:
            process = self._spawn(argv, env=env, stderr=handle, cwd=None)
        except BaseException:
            # The slot is never taken, so a launch that failed to start cannot
            # wedge the cockpit into reporting `busy` forever.
            handle.close()
            raise

        self._write_meta(run_id, launched=True, exit_code=None)
        self.live = LiveRun(run_id=run_id, engine_run_id=engine_run_id,
                            mode=RunMode(request.mode), pack_name=pack.spec.name,
                            pid=process.pid, process=process,
                            stderr_handle=handle)
        return run_id

    # -- control -----------------------------------------------------------

    def control(self, run_id: str, action: ControlAction) -> None:
        """Write `{"action": ...}` where the engine looks for it.

        Exactly the shape `index.py:571-577` parses back into a `ControlAction`
        — the reader is already shipped, so this side has no latitude.

        Written atomically. A half-written control file would be read as no
        control file at all, and the action would be silently dropped: the
        operator would press Cancel, see the 202, and watch the run continue.

        **No signal is sent, at any delay.** See the module docstring (R4-11).
        """
        path = control_path(self.runs_dir / f"{run_id}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_json(path, {"action": ControlAction(action).value})

    # -- reap --------------------------------------------------------------

    def reap(self) -> LiveRun | None:
        """Record a finished child's exit code and release the slot.

        Called on the way into every launch and from every read of live state.
        The exit code is the load-bearing part: `index.py:198-200` says it
        outright — a run whose child exited but whose exit code was never
        recorded is indistinguishable from a live one, and spins in the table
        forever.

        Returns the still-live run, or `None`.
        """
        live = self.live
        if live is None:
            return None
        code = live.process.poll()
        if code is None:
            return live
        self._write_meta(live.run_id, launched=True, exit_code=int(code))
        try:
            live.stderr_handle.close()
        except OSError:
            pass
        self.live = None
        return None

    # -- files -------------------------------------------------------------

    def _write_meta(self, run_id: str, *, launched: bool,
                    exit_code: int | None) -> None:
        """`runs/.evalyn-ui/<run_id>/meta.json`, atomically.

        The two keys are imported from `ui.paths`, never retyped, because the
        reader imports the same two constants — the drift this pair exists to
        prevent is a writer spelling `exitcode` and a reader looking for
        `exit_code`, which fails soft and leaves a dead run reading as alive.
        """
        self._atomic_json(meta_path(self.runs_dir, run_id),
                          {META_LAUNCHED_KEY: launched,
                           META_EXIT_CODE_KEY: exit_code})

    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        """Temp-then-rename, so no reader ever sees a half-written file.

        `RunIndex._sidecar` reads these files from inside `list()`, which must
        never raise; a torn read there degrades a run to `interrupted`. Writing
        atomically means that degradation only ever reports something real.
        """
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
