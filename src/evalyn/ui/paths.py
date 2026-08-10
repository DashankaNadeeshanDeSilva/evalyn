"""Where a run's files live (Plan #4, Task 2) — one layout, derived not guessed.

The cockpit has to correlate four things that belong to a single run: the
artifact, its event stream, its control file, and the server's own bookkeeping.
It does that by **derivation from the artifact path**, never by scanning for the
newest file — a heuristic that races the moment two runs overlap.

The layout::

    runs/<run_id><suffix>.json           the artifact          (engine writes)
    runs/<run_id><suffix>.events.jsonl   the event stream      (engine writes)
    runs/<run_id><suffix>.control.json   pause/resume/cancel   (server writes)
    runs/.evalyn-ui/<run_id>/            meta.json, stderr.log (server writes)

**Siblings, not a per-run directory.** Every filename assertion already in the
suite globs `*.json` (`tests/engine/test_run.py`, `test_budget.py`,
`tests/test_cli.py`, `tests/discovery/test_run.py`) and `*.json` does not match
`.events.jsonl`, so the sidecars are invisible to code that only wants
artifacts. A per-run directory would instead force changes to `--baseline`
resolution, compare's `--a/--b`, the artifacts already on disk and the docs; that
migration stays a deferred register item rather than being smuggled in here. The
server's bookkeeping *is* a per-run directory, but dot-prefixed so it too is
hidden from the glob.

An events file with no artifact is not an error — it is the evidence that a run
died, and the UI renders it as `interrupted`.

**One grammar (ruling R4-7).** `RUN_ID_RE` below is re-exported from
`evalyn.ui.models`, the frozen contract — the same compiled object, not a copy.
A second spelling of that pattern is exactly the drift the contract exists to
prevent, and `tests/ui/test_paths.py` asserts the identity.
"""
from __future__ import annotations

from pathlib import Path

from evalyn.ui.models import RUN_ID_RE, is_run_id

__all__ = ["RUN_ID_RE", "is_run_id", "events_path", "control_path", "sidecar_dir",
           "meta_path", "SIDECAR_DIR_NAME", "EVENTS_SUFFIX", "CONTROL_SUFFIX",
           "META_FILENAME", "META_LAUNCHED_KEY", "META_EXIT_CODE_KEY"]

#: Dot-prefixed so `runs/*.json` and a user's `ls` both ignore it.
SIDECAR_DIR_NAME = ".evalyn-ui"
EVENTS_SUFFIX = ".events.jsonl"
CONTROL_SUFFIX = ".control.json"

# --------------------------------------------------------------------------
# The launcher's own bookkeeping — named HERE so the writer and the reader
# cannot drift (the same medicine R4-7 applied to the run-id grammar).
#
# The launcher (Task 19) writes this file; `ui.index` reads it to decide
# whether a run with no artifact is `running`, `interrupted` or
# `failed_to_start`. Those two sides being separated by two tasks and a hard-
# coded string literal is precisely how a dead run ends up spinning in the
# table forever: the reader looks for `exit_code`, the writer spelled it
# `exitcode`, the read fails soft, and "no exit code recorded" is
# indistinguishable from "still alive". **Import these names; do not retype
# them.** Anything else in the file is the writer's business — the reader
# ignores keys it does not know.
# --------------------------------------------------------------------------

#: Lives at `runs/.evalyn-ui/<run_id>/meta.json`.
META_FILENAME = "meta.json"
#: `bool` — did the child process actually start? `False` is `failed_to_start`.
META_LAUNCHED_KEY = "launched"
#: `int | None` — the child's exit status; absent/None means "still running".
META_EXIT_CODE_KEY = "exit_code"


def _stem_of(artifact: Path) -> str:
    """The artifact's `<run_id><suffix>`, refusing anything that is not one.

    `.stem` rather than `with_suffix("")`: a pack slug may legally contain `.`
    (`…-example.v2.json`), and only the final `.json` may come off.

    The `.json` check is not ceremony — it makes the derivation non-idempotent
    on purpose. `events_path(events_path(p))` would otherwise quietly yield
    `….events.events.jsonl` and the server would tail a file nothing writes.
    """
    if artifact.suffix != ".json":
        raise ValueError(
            f"not a run artifact path: {artifact.name!r} — the sidecar layout is "
            f"derived from `<run_id><suffix>.json`")
    return artifact.stem


def events_path(artifact: Path) -> Path:
    """`runs/<run_id><suffix>.events.jsonl` — sibling of *artifact*."""
    return artifact.with_name(_stem_of(artifact) + EVENTS_SUFFIX)


def control_path(artifact: Path) -> Path:
    """`runs/<run_id><suffix>.control.json` — sibling of *artifact*.

    Written by the server, read by the engine. Named `.control.json` and not
    `.control` so a human editing it gets JSON tooling.
    """
    return artifact.with_name(_stem_of(artifact) + CONTROL_SUFFIX)


def sidecar_dir(runs_dir: Path, run_id: str) -> Path:
    """`runs/.evalyn-ui/<run_id>/` — the server's own per-run bookkeeping.

    A **locator only**: it creates nothing, so callers can ask where a run's
    `meta.json` / `stderr.log` would be without materialising a directory for a
    run that never started.

    *run_id* is validated with the frozen contract's `is_run_id` before it is
    joined. Traversal is excluded by construction — the grammar admits no `/` —
    but validating here rather than trusting the caller means a hostile id from
    a URL path parameter can never reach the filesystem at all.
    """
    if not is_run_id(run_id):
        raise ValueError(f"not a run_id: {run_id!r}")
    return Path(runs_dir) / SIDECAR_DIR_NAME / run_id


def meta_path(runs_dir: Path, run_id: str) -> Path:
    """`runs/.evalyn-ui/<run_id>/meta.json` — the launcher's process record.

    A locator, like `sidecar_dir`, and validated the same way. One function so
    the writer and the reader cannot disagree about where the file is any more
    than they can disagree about what it is called.
    """
    return sidecar_dir(runs_dir, run_id) / META_FILENAME
