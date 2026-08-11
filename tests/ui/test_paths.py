"""The sidecar path layout (Plan #4, Task 2).

Two things are under test and only one of them is arithmetic on strings:

* **the layout itself** — events and control files are *siblings* of the
  artifact on the same stem (`runs/<run_id><suffix>.events.jsonl`), never a
  per-run directory, because every existing filename assertion in the suite
  globs `*.json` and `*.json` does not match `.events.jsonl`;
* **the single grammar** (ruling R4-7) — `paths.RUN_ID_RE` must *be*
  `models.RUN_ID_RE`, the same compiled object. A second spelling of that
  pattern is precisely the drift the frozen contract exists to prevent, so it
  is asserted by identity and by reading this module's own source.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from evalyn.ui import models as m
from evalyn.ui import paths

pytestmark = pytest.mark.ui

GATE = pathlib.Path("runs/20260804T081544953468-53e4125b-example.json")
COMPARE = pathlib.Path("runs/20260806T091011000000-9f8e7d6c-example-compare.json")
DISCOVER = pathlib.Path("runs/20260805T101112000000-1a2b3c4d-example-discover.json")
LEGACY = pathlib.Path("runs/20260723T080347-example.json")


# --------------------------------------------------------------------------
# R4-7: ONE grammar, imported — never a second spelling
# --------------------------------------------------------------------------

def test_run_id_re_is_the_frozen_contract_object_not_a_copy():
    assert paths.RUN_ID_RE is m.RUN_ID_RE
    assert paths.RUN_ID_RE.pattern == m.RUN_ID_PATTERN


def test_paths_module_never_retypes_the_run_id_grammar():
    """A regex literal here would be the drift R4-7 forbids."""
    src = inspect.getsource(paths)
    assert "RUN_ID_PATTERN" not in src.replace("m.RUN_ID_PATTERN", "")
    assert r"\d{8}T" not in src
    assert "re.compile" not in src


def test_run_id_grammar_rejects_baseline_and_accepts_the_legacy_form():
    # `runs/baseline.json` is a real file in this repo and is NOT a run
    assert not m.is_run_id("baseline")
    assert not m.is_run_id("baseline.json")
    # the pre-microsecond, no-uuid form still indexes
    assert m.is_run_id("20260723T080347-example")
    assert m.is_run_id("20260804T081544953468-53e4125b-example")
    assert m.is_run_id("20260806T091011000000-9f8e7d6c-example-compare")


# --------------------------------------------------------------------------
# siblings on the same stem
# --------------------------------------------------------------------------

@pytest.mark.parametrize("artifact", [GATE, COMPARE, DISCOVER, LEGACY])
def test_events_and_control_are_siblings_on_the_same_stem(artifact):
    events, control = paths.events_path(artifact), paths.control_path(artifact)
    assert events.parent == artifact.parent
    assert control.parent == artifact.parent
    assert events.name == artifact.stem + ".events.jsonl"
    assert control.name == artifact.stem + ".control.json"
    # the load-bearing property: the legacy `*.json` globs must not see them
    assert not pathlib.PurePath(events.name).match("*.json")


def test_a_dotted_pack_slug_keeps_its_dots():
    """`.` is legal in a slug — only the `.json` suffix may be stripped."""
    art = pathlib.Path("runs/20260807T101112000000-deadbeef-example.v2.json")
    assert paths.events_path(art).name == "20260807T101112000000-deadbeef-example.v2.events.jsonl"


def test_sidecar_paths_refuse_anything_that_is_not_an_artifact():
    """Idempotence traps: deriving from an events path must not silently work."""
    with pytest.raises(ValueError):
        paths.events_path(paths.events_path(GATE))
    with pytest.raises(ValueError):
        paths.control_path(pathlib.Path("runs/20260804T081544953468-53e4125b-example"))


# --------------------------------------------------------------------------
# the server's hidden per-run directory
# --------------------------------------------------------------------------

def test_sidecar_dir_is_dot_prefixed_and_hidden_from_the_artifact_glob(tmp_path):
    d = paths.sidecar_dir(tmp_path, "20260804T081544953468-53e4125b-example")
    assert d == tmp_path / ".evalyn-ui" / "20260804T081544953468-53e4125b-example"
    assert not d.exists()          # locator only — it never creates anything
    assert not list(tmp_path.glob("*.json"))


@pytest.mark.parametrize("hostile", [
    "../../etc/passwd",
    "..",
    "/etc/passwd",
    "20260804T081544953468-53e4125b-example/../../escape",
    "20260804T081544953468-53e4125b-example.json",   # a filename, not an id
    "baseline",
    "",
    "20260804T081544953468-53e4125b-example\n",      # `$` vs fullmatch
])
def test_sidecar_dir_refuses_a_run_id_that_is_not_one(tmp_path, hostile):
    with pytest.raises(ValueError):
        paths.sidecar_dir(tmp_path, hostile)


def test_sidecar_dir_stays_inside_the_runs_dir(tmp_path):
    d = paths.sidecar_dir(tmp_path, "20260723T080347-example")
    assert tmp_path.resolve() in d.resolve().parents
