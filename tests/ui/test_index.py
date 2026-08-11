"""`RunIndex` over a hostile `runs/` directory (Plan #4, Task 3).

The thing under test is not "does it list files" — it is **degradation, not
failure**. A `runs/` directory accumulated over a month of development contains
artifacts written by three different schema generations, a blessed
`baseline.json`, an Inspect `logs/` tree, and whatever a half-finished run left
behind. Every one of those must produce a *row*; none of them may produce a
traceback. So most of what follows builds a deliberately hostile directory and
asserts the listing survives it.

Two rules constrain the assertions themselves:

* **R4-6 — never assert a run count.** The real-directory test asserts
  *invariants derived in the test* (rows + skips account for every candidate;
  the degraded set is exactly the set that actually fails the typed loader), so
  it stays green when someone runs another eval.
* **R4-7 — one run-id grammar.** This module imports `is_run_id` from the
  frozen contract, and a source scan below forbids `index.py` from re-spelling
  the pattern, exactly as `test_paths.py` does for Task 2.
"""
from __future__ import annotations

import copy
import inspect
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from evalyn.discovery.replay import ReplayResult
from evalyn.discovery.run import DiscoveryArtifact, Finding, ReplaySkipped
from evalyn.engine.compare import CompareArtifact
from evalyn.engine.gate import GateResult
from evalyn.engine.run import ProbeResult, RunArtifact
from evalyn.ui import index as ix
from evalyn.ui import models as m
from evalyn.ui import paths
from evalyn.ui.index import (
    LoadedArtifact,
    RunIndex,
    RunNotFound,
    SidecarState,
    derive_status,
)
from evalyn.ui.models import ReplayStatus
from evalyn.ui.paths import (
    CONTROL_SUFFIX,
    META_EXIT_CODE_KEY,
    META_FILENAME,
    META_LAUNCHED_KEY,
    SIDECAR_DIR_NAME,
    control_path,
)

pytestmark = pytest.mark.ui

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ui_runs"

GATE_ID = "20260804T081544953468-53e4125b-example"
LEGACY_ID = "20260723T080347-example"
COMPARE_ID = "20260806T091011000000-9f8e7d6c-example-compare"
DISCOVER_ID = "20260805T101112000000-1a2b3c4d-example-discover"
FIXTURE_IDS = {GATE_ID, LEGACY_ID, COMPARE_ID, DISCOVER_ID}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _probe(**kw) -> ProbeResult:
    base = dict(id="p", category="c", kind="regression", safety_critical=False,
                samples=1, trials=1, expected_trials=1, pass_at_k=1.0, pass_k=1.0,
                mean_score=1.0)
    base.update(kw)
    return ProbeResult(**base)


def _gate_artifact(probes: list[ProbeResult] | None = None) -> RunArtifact:
    return RunArtifact(
        pack_name="example", pack_hash="0" * 64, judge_model="mockllm/model",
        created_at="2026-08-04T08:15:44.953115+00:00",
        probes=[_probe()] if probes is None else probes, log_path="logs/x")


def _loaded(typed=None, *, run_id: str = GATE_ID, mode: m.RunMode = m.RunMode.gate,
            error: str | None = None) -> LoadedArtifact:
    return LoadedArtifact(run_id=run_id, mode=mode, path=Path(f"runs/{run_id}.json"),
                          typed=typed, error=error)


def _copy_fixtures(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for src in sorted(FIXTURES.glob("*.json")):
        dest.joinpath(src.name).write_bytes(src.read_bytes())
    return dest


# --------------------------------------------------------------------------
# R4-7: the grammar is imported, never re-spelled
# --------------------------------------------------------------------------

def test_index_module_never_retypes_the_run_id_grammar():
    src = inspect.getsource(ix)
    assert "re.compile" not in src
    assert r"\d{8}T" not in src
    assert r"\d{6}" not in src


def test_index_uses_the_frozen_contracts_predicate_object():
    assert ix.is_run_id is m.is_run_id


# --------------------------------------------------------------------------
# 1. the fixture corpus lists, and raises nothing
# --------------------------------------------------------------------------

def test_list_returns_one_row_per_fixture_and_raises_nothing():
    rows = RunIndex(FIXTURES).list()
    assert {r.run_id for r in rows} == FIXTURE_IDS
    assert len(rows) == len(list(FIXTURES.glob("*.json")))


def test_rows_are_ordered_by_created_at_then_run_id_descending():
    rows = RunIndex(FIXTURES).list()
    keys = [(r.created_at, r.run_id) for r in rows]
    assert keys == sorted(keys, reverse=True)


def test_mode_comes_from_the_filename_suffix():
    rows = {r.run_id: r for r in RunIndex(FIXTURES).list()}
    assert rows[GATE_ID].mode is m.RunMode.gate
    assert rows[LEGACY_ID].mode is m.RunMode.gate
    assert rows[COMPARE_ID].mode is m.RunMode.compare
    assert rows[DISCOVER_ID].mode is m.RunMode.discover


def test_the_three_current_schema_fixtures_load_cleanly():
    rows = {r.run_id: r for r in RunIndex(FIXTURES).list()}
    for rid in (GATE_ID, COMPARE_ID, DISCOVER_ID):
        assert rows[rid].degraded is False, rows[rid].degraded_reason
        assert rows[rid].pack_name == "example"


# --------------------------------------------------------------------------
# 2. degradation, not failure
# --------------------------------------------------------------------------

def test_the_legacy_artifact_degrades_with_a_usable_row():
    """A pre-#2a artifact fails `RunArtifact.from_dict` — and still lists."""
    row = {r.run_id: r for r in RunIndex(FIXTURES).list()}[LEGACY_ID]
    assert row.degraded is True
    assert row.degraded_reason                       # the tooltip is mandatory
    assert row.run_id == LEGACY_ID
    assert row.mode is m.RunMode.gate
    assert row.created_at                            # recovered, one way or another
    assert row.status is m.RunStatus.unreadable
    # null metrics — never 0.0, which would read as a measured zero
    assert row.judge_usd is None
    assert row.verdict_hint is None
    # the salvage layer still recovered the shallow keys
    assert row.pack_name == "example"


def test_invalid_json_yields_a_degraded_row_mentioning_json(tmp_path):
    runs = _copy_fixtures(tmp_path / "runs")
    torn = "20260807T120000000000-deadbeef-example"
    runs.joinpath(f"{torn}.json").write_text("{")

    rows = {r.run_id: r for r in RunIndex(runs).list()}
    assert torn in rows
    row = rows[torn]
    assert row.degraded is True
    assert "json" in row.degraded_reason.lower()
    assert row.status is m.RunStatus.unreadable
    assert row.pack_name is None                     # nothing to salvage
    assert row.created_at == "2026-08-07T12:00:00+00:00"   # from the filename alone


def test_json_that_is_not_an_object_degrades(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    rid = "20260807T120001000000-deadbeef-example"
    runs.joinpath(f"{rid}.json").write_text("[1, 2, 3]")
    (row,) = RunIndex(runs).list()
    assert row.degraded is True and row.run_id == rid


def test_a_directory_named_like_a_run_degrades_rather_than_raising(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    rid = "20260807T120002000000-deadbeef-example"
    runs.joinpath(f"{rid}.json").mkdir()             # a DIRECTORY, not a file
    rows = RunIndex(runs).list()
    assert [r.run_id for r in rows] == [rid]
    assert rows[0].degraded is True and rows[0].degraded_reason


def test_a_broken_symlink_named_like_a_run_degrades(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    rid = "20260807T120003000000-deadbeef-example"
    runs.joinpath(f"{rid}.json").symlink_to(tmp_path / "nowhere.json")
    rows = RunIndex(runs).list()
    assert [r.run_id for r in rows] == [rid]
    assert rows[0].degraded is True


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permissions")
def test_an_unreadable_file_degrades(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    rid = "20260807T120004000000-deadbeef-example"
    p = runs / f"{rid}.json"
    p.write_text("{}")
    p.chmod(0)
    try:
        rows = RunIndex(runs).list()
        assert [r.run_id for r in rows] == [rid]
        assert rows[0].degraded is True
    finally:
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_an_absent_runs_directory_lists_empty_rather_than_raising(tmp_path):
    assert RunIndex(tmp_path / "does-not-exist").list() == []


# --------------------------------------------------------------------------
# 3. what the index refuses to index at all
# --------------------------------------------------------------------------

def test_baseline_and_logs_are_excluded_by_the_run_id_grammar(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    runs.joinpath("baseline.json").write_text("{}")
    runs.joinpath("logs").mkdir()
    runs.joinpath("logs", "20260807T120005000000-deadbeef-example.json").write_text("{}")
    runs.joinpath("notes.txt").write_text("hello")
    runs.joinpath(".evalyn-ui").mkdir()
    rid = "20260807T120006000000-deadbeef-example"
    runs.joinpath(f"{rid}.json").write_text(json.dumps(_gate_artifact().to_dict()))

    assert [r.run_id for r in RunIndex(runs).list()] == [rid]


def test_sidecar_files_are_not_mistaken_for_artifacts(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    rid = "20260807T120007000000-deadbeef-example"
    runs.joinpath(f"{rid}.json").write_text(json.dumps(_gate_artifact().to_dict()))
    runs.joinpath(f"{rid}.events.jsonl").write_text('{"seq": 1}\n')
    runs.joinpath(f"{rid}.control.json").write_text('{"action": "pause"}')

    # `<rid>.control.json` has stem `<rid>.control`, which is NOT a run id
    assert [r.run_id for r in RunIndex(runs).list()] == [rid]


# --------------------------------------------------------------------------
# 4. mode is lexical — proven by making every read fail
# --------------------------------------------------------------------------

def test_mode_is_classified_without_opening_a_single_file(monkeypatch):
    """Nothing in the process can parse JSON, and the modes are still right.

    If mode came from the body, every row here would be `gate` (or the listing
    would raise). The rows are also all `degraded`, which is what stops this
    from passing vacuously on an index that skipped the files entirely.
    """
    def boom(*a, **kw):
        raise ValueError("json parsing is disabled for this test")

    monkeypatch.setattr(json, "loads", boom)
    rows = {r.run_id: r for r in RunIndex(FIXTURES).list()}

    assert set(rows) == FIXTURE_IDS
    assert rows[GATE_ID].mode is m.RunMode.gate
    assert rows[COMPARE_ID].mode is m.RunMode.compare
    assert rows[DISCOVER_ID].mode is m.RunMode.discover
    assert all(r.degraded for r in rows.values())
    assert all(r.created_at for r in rows.values())


def test_list_never_calls_evaluate_gate(monkeypatch):
    """The list carries `verdict_hint`; the real verdict is a lazy endpoint."""
    import evalyn.engine.gate as gate_mod

    def boom(*a, **kw):
        raise AssertionError("the list path called evaluate_gate")

    monkeypatch.setattr(gate_mod, "evaluate_gate", boom)
    monkeypatch.setattr(ix, "evaluate_gate", boom, raising=False)
    assert RunIndex(FIXTURES).list()


# --------------------------------------------------------------------------
# 5. `derive_status` — pure, and table-tested over the nine states
# --------------------------------------------------------------------------

_FAILING = _gate_artifact([_probe(safety_critical=True, pass_k=0.0)])
_NO_PROBES = _gate_artifact([])
_CAPABILITY_ONLY = _gate_artifact([_probe(kind="capability")])
_DISCOVER_ERRORED = DiscoveryArtifact(
    pack_name="example", pack_hash="0" * 64, agent_model="m", judge_model="m",
    rubric_judge_model=None, created_at="2026-08-05T10:11:12+00:00", findings=[],
    error_count=1, sessions_total=0, confirmed_count=0, live_spend_usd=0.0,
    reconciled_spend_usd=0.0, budget_exhausted=False, partial=False, objectives=[],
    log_path="logs/x", eval_status="error")

STATUS_TABLE = [
    ("clean gate artifact",
     _loaded(_gate_artifact()), SidecarState(), None, m.RunStatus.passed),
    ("a safety probe that is not reliably passing",
     _loaded(_FAILING), SidecarState(), None, m.RunStatus.gate_failed),
    ("the real gate verdict outranks the hint",
     _loaded(_gate_artifact()), SidecarState(),
     GateResult(exit_code=1, failures=["x"], quarantined=[], report_md=""),
     m.RunStatus.gate_failed),
    ("a gate artifact with no probes measured nothing",
     _loaded(_NO_PROBES), SidecarState(), None, m.RunStatus.invalid),
    # R4-17: a capability-only run measured exactly what it set out to measure,
    # and `evaluate_gate` returns 0 for it. `invalid` would be a false claim.
    ("a capability-only run gated nothing, which is not the same as invalid",
     _loaded(_CAPABILITY_ONLY), SidecarState(), None, m.RunStatus.passed),
    ("a real gate verdict is consulted BEFORE the hint is ever inspected",
     _loaded(_CAPABILITY_ONLY), SidecarState(),
     GateResult(exit_code=1, failures=["x"], quarantined=[], report_md=""),
     m.RunStatus.gate_failed),
    ("a discover run whose eval itself failed",
     _loaded(_DISCOVER_ERRORED, run_id=DISCOVER_ID, mode=m.RunMode.discover),
     SidecarState(), None, m.RunStatus.invalid),
    ("an artifact this build cannot parse",
     _loaded(None, error="boom"), SidecarState(), None, m.RunStatus.unreadable),
    ("a live run that has not written its artifact",
     None, SidecarState(present=True, exit_code=None), None, m.RunStatus.running),
    ("a live run the operator paused",
     None, SidecarState(present=True, control=m.ControlAction.pause),
     None, m.RunStatus.paused),
    ("a run the operator cancelled",
     None, SidecarState(present=True, control=m.ControlAction.cancel, exit_code=1),
     None, m.RunStatus.cancelled),
    ("a process that vanished without writing an artifact",
     None, SidecarState(present=True, exit_code=1, events=True),
     None, m.RunStatus.interrupted),
    # a meta.json this build cannot read is NOT evidence of life — claiming
    # `running` would leave a dead run spinning in the table forever
    ("a process record this build cannot read is not evidence of life",
     None, SidecarState(present=True, schema_unrecognised=True),
     None, m.RunStatus.interrupted),
    ("a child that never started",
     None, SidecarState(present=True, launched=False), None,
     m.RunStatus.failed_to_start),
]


@pytest.mark.parametrize(
    "why,artifact,sidecar,gate_result,expected",
    STATUS_TABLE, ids=[row[0] for row in STATUS_TABLE])
def test_derive_status_table(why, artifact, sidecar, gate_result, expected):
    assert derive_status(artifact, sidecar, gate_result) is expected


def test_derive_status_covers_every_member_of_the_enum():
    """A tenth status may not be added without a row that produces it."""
    produced = {row[4] for row in STATUS_TABLE}
    assert produced == set(m.RunStatus)


def test_derive_status_is_pure():
    art = _loaded(_gate_artifact())
    side = SidecarState(present=True)
    before = copy.deepcopy((art, side))
    assert derive_status(art, side, None) is derive_status(art, side, None)
    assert (art, side) == before


def test_a_capability_only_run_keeps_its_unknown_hint_while_passing(tmp_path):
    """R4-17: `passed` costs no information — `unknown` still says nothing gated.

    The pair matters. `invalid` is defined by this module as "parsed, but the
    numbers mean nothing", which is a false claim about a run that measured
    exactly what it set out to. That nothing was *gated* is carried losslessly
    by `verdict_hint`, so the row can say both things at once.
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    rid = "20260807T170000000000-deadbeef-example"
    runs.joinpath(f"{rid}.json").write_text(
        json.dumps(_CAPABILITY_ONLY.to_dict()))

    (row,) = RunIndex(runs).list()
    assert row.status is m.RunStatus.passed
    assert row.verdict_hint is m.VerdictHint.unknown
    assert row.degraded is False


def test_invalid_is_reserved_for_an_artifact_that_measured_nothing():
    assert derive_status(_loaded(_NO_PROBES)) is m.RunStatus.invalid
    assert derive_status(_loaded(_CAPABILITY_ONLY)) is not m.RunStatus.invalid


def test_a_cancelled_run_that_did_write_an_artifact_is_still_cancelled():
    assert derive_status(
        _loaded(_gate_artifact()),
        SidecarState(present=True, control=m.ControlAction.cancel, exit_code=0),
        None) is m.RunStatus.cancelled


# --------------------------------------------------------------------------
# 5b. the launcher's process record — read through `ui.paths`, never guessed
# --------------------------------------------------------------------------

def _planted(tmp_path: Path, meta: str | None) -> tuple[RunIndex, str, Path]:
    """A `runs/` with a sidecar directory for one run, and no artifact."""
    runs = tmp_path / "runs"
    rid = "20260807T180000000000-deadbeef-example"
    meta_dir = runs / SIDECAR_DIR_NAME / rid
    meta_dir.mkdir(parents=True)
    if meta is not None:
        meta_dir.joinpath(META_FILENAME).write_text(meta)
    return RunIndex(runs), rid, runs / f"{rid}.json"


def test_a_readable_process_record_is_understood(tmp_path):
    idx, rid, artifact = _planted(
        tmp_path, json.dumps({META_LAUNCHED_KEY: True, META_EXIT_CODE_KEY: 0}))
    state = idx._sidecar(rid, artifact)
    assert state.present is True and state.launched is True
    assert state.exit_code == 0 and state.schema_unrecognised is False
    assert derive_status(None, state) is m.RunStatus.interrupted   # dead, no artifact


def test_a_live_process_record_reads_as_running(tmp_path):
    idx, rid, artifact = _planted(tmp_path, json.dumps({META_EXIT_CODE_KEY: None}))
    state = idx._sidecar(rid, artifact)
    assert state.schema_unrecognised is False and state.exit_code is None
    assert derive_status(None, state) is m.RunStatus.running


def test_a_child_that_never_started_reads_as_failed_to_start(tmp_path):
    idx, rid, artifact = _planted(tmp_path, json.dumps({META_LAUNCHED_KEY: False}))
    assert derive_status(None, idx._sidecar(rid, artifact)) \
        is m.RunStatus.failed_to_start


@pytest.mark.parametrize("meta,why", [
    (None, "the launcher never wrote the file"),
    ("{", "the file is torn"),
    ("[]", "the file is not an object"),
    ('{"pid": 42, "argv": []}', "the file carries neither key this build knows"),
])
def test_an_unreadable_process_record_never_reads_as_running(tmp_path, meta, why):
    """The defect this flag exists to prevent: a dead run spinning forever.

    `exit_code` absent is indistinguishable from `exit_code` unreadable unless
    the reader records which one it was — and `list()` may not raise, so
    failing loudly is not available as a defence.
    """
    idx, rid, artifact = _planted(tmp_path, meta)
    state = idx._sidecar(rid, artifact)
    assert state.present is True, why
    assert state.schema_unrecognised is True, why
    assert derive_status(None, state) is m.RunStatus.interrupted, why


def test_an_explicit_pause_survives_an_unreadable_process_record(tmp_path):
    """The control file is a second, readable source of positive evidence."""
    idx, rid, artifact = _planted(tmp_path, "{")
    control_path(artifact).write_text(json.dumps({"action": "pause"}))
    assert derive_status(None, idx._sidecar(rid, artifact)) is m.RunStatus.paused


def test_a_runs_dir_this_cockpit_never_launched_into_reports_no_process_facts():
    idx = RunIndex(FIXTURES)
    assert idx._sidecar(GATE_ID, FIXTURES / f"{GATE_ID}.json") == SidecarState()


def test_the_meta_schema_is_named_in_ui_paths_not_retyped_here():
    """R4-7's medicine, applied to the launcher's record (F4).

    Task 19 writes this file and this module reads it. A hardcoded literal on
    either side is how the two silently disagree — and the failure mode is not
    a crash, it is a dead run reported as `running`.
    """
    src = inspect.getsource(ix)
    for literal in ('"meta.json"', '"launched"', '"exit_code"'):
        assert literal not in src, f"{literal} must come from evalyn.ui.paths"
    assert "META_FILENAME" in inspect.getsource(paths)
    assert paths.meta_path(Path("runs"), GATE_ID) == \
        Path("runs") / SIDECAR_DIR_NAME / GATE_ID / META_FILENAME


# --------------------------------------------------------------------------
# 5c. the CLI's import graph — the half of the guard nobody was asserting
# --------------------------------------------------------------------------

def test_importing_the_cli_loads_no_web_framework():
    """`import evalyn.cli` must stay free of fastapi/starlette/uvicorn (F5).

    `test_ui_package_init_is_docstring_only` covers `evalyn/ui/__init__.py`,
    and `test_models_module_does_not_import_fastapi` AST-scans `models.py` —
    but nothing asserted the property that actually matters, which is about the
    **CLI's** import graph. It is live now: `evalyn.ui.index` imports
    `evalyn.engine.run`, which pulls `inspect_ai`, which pulls `starlette`. The
    CLI is safe only because it reaches into `evalyn.ui` lazily, and one eager
    `import evalyn.ui.index` in `cli.py` would end that silently. A subprocess,
    because this interpreter has already imported everything.
    """
    probe = ("import evalyn.cli, sys, json;"
             "print(json.dumps(sorted({name.split('.')[0] for name in sys.modules}"
             " & {'fastapi', 'starlette', 'uvicorn'})))")
    done = subprocess.run([sys.executable, "-c", probe], check=True,
                          capture_output=True, text=True)
    assert json.loads(done.stdout) == [], done.stdout


# --------------------------------------------------------------------------
# 6. filters, cursor pagination, limit
# --------------------------------------------------------------------------

def test_mode_filter_is_applied_before_any_file_is_opened(monkeypatch):
    """A lexical filter must not cost reads on the runs it excludes."""
    real, parsed = json.loads, []

    def counting(text, *a, **k):
        parsed.append(text)
        return real(text, *a, **k)

    monkeypatch.setattr(json, "loads", counting)
    rows = RunIndex(FIXTURES).list(mode=m.RunMode.compare)
    assert [r.run_id for r in rows] == [COMPARE_ID]
    assert len(parsed) == 1, "the mode filter opened files of other modes"


def test_pack_filter_matches_salvaged_pack_names_too():
    """A degraded row that salvaged its pack still belongs under that pack."""
    idx = RunIndex(FIXTURES)
    assert {r.run_id for r in idx.list(pack="example")} == FIXTURE_IDS
    assert idx.list(pack="nope") == []


def test_status_filter():
    idx = RunIndex(FIXTURES)
    assert [r.run_id for r in idx.list(status=m.RunStatus.unreadable)] == [LEGACY_ID]
    assert {r.run_id for r in idx.list(status=m.RunStatus.passed)} == \
        FIXTURE_IDS - {LEGACY_ID}


def test_limit_truncates_from_the_top_of_the_ordering():
    rows = RunIndex(FIXTURES).list(limit=2)
    assert [r.run_id for r in rows] == [COMPARE_ID, DISCOVER_ID]


def test_before_cursor_pages_without_repeating_or_dropping():
    idx = RunIndex(FIXTURES)
    everything = idx.list()
    seen, cursor = [], None
    for _ in range(len(everything)):
        page = idx.list(limit=1, before=cursor)
        assert len(page) == 1
        seen.append(page[0].run_id)
        cursor = m.make_cursor(page[0].created_at, page[0].run_id)
    assert seen == [r.run_id for r in everything]
    assert idx.list(limit=1, before=cursor) == []


def test_cursor_comparison_uses_the_parsed_tuple_not_the_joined_string(tmp_path):
    """`|` (0x7C) sorts after `.` (0x2E) — comparing joined cursors inverts."""
    runs = tmp_path / "runs"
    runs.mkdir()
    short = "20260807T130000000000-aaaaaaaa-example"
    long = "20260807T130001000000-bbbbbbbb-example"
    for rid, created in ((short, "2026-08-07T13:00:44+00:00"),
                         (long, "2026-08-07T13:00:44.5+00:00")):
        art = _gate_artifact()
        art.created_at = created
        runs.joinpath(f"{rid}.json").write_text(json.dumps(art.to_dict()))

    idx = RunIndex(runs)
    # descending by (created_at, run_id): "…:44.5+00:00" > "…:44+00:00"
    assert [r.run_id for r in idx.list()] == [long, short]
    cursor = m.make_cursor("2026-08-07T13:00:44.5+00:00", long)
    assert [r.run_id for r in idx.list(before=cursor)] == [short]


def test_a_bare_timestamp_cursor_is_rejected():
    with pytest.raises(ValueError):
        RunIndex(FIXTURES).list(before="2026-08-06T09:10:11+00:00")


# --------------------------------------------------------------------------
# 7. `.get()` / `.artifact_path()`
# --------------------------------------------------------------------------

def test_get_returns_a_detail_that_is_a_superset_of_the_row():
    idx = RunIndex(FIXTURES)
    row = {r.run_id: r for r in idx.list()}[GATE_ID]
    detail = idx.get(GATE_ID)
    assert isinstance(detail, m.RunDetail)
    assert detail.run_id == row.run_id and detail.status is row.status
    assert detail.probes and detail.probes[0].checks
    assert detail.judge_model == "mockllm/model"
    assert detail.capabilities.trial_records is True


def test_get_on_a_degraded_artifact_still_returns_a_detail():
    detail = RunIndex(FIXTURES).get(LEGACY_ID)
    assert detail.degraded is True and detail.probes == []


def test_get_populates_the_compare_scoreboard_and_the_discovery_summary():
    idx = RunIndex(FIXTURES)
    comp = idx.get(COMPARE_ID)
    assert comp.compare is not None and comp.discovery is None
    assert comp.compare.label_a and comp.compare.label_b
    assert all(isinstance(v, m.CategoryTally) for v in comp.compare.categories.values())
    assert all(isinstance(v, m.HardMetrics) for v in comp.compare.hard_metrics.values())

    disc = idx.get(DISCOVER_ID)
    assert disc.discovery is not None and disc.compare is None
    assert disc.discovery.eval_status == "success"
    assert disc.discovery.findings
    row = disc.discovery.findings[0]
    assert row.run_id == DISCOVER_ID
    assert row.probe_id == Path(row.probe_path).stem     # never the full path
    assert row.replay_status is not None


@pytest.mark.parametrize("replay,expected", [
    (ReplayResult(reproduced=True, trials=3, pass_k=0.0), ReplayStatus.reproduced),
    (ReplayResult(reproduced=False, trials=3, pass_k=1.0), ReplayStatus.not_reproduced),
    (ReplaySkipped(reason="out of budget", budget=True), ReplayStatus.skipped_budget),
    (ReplaySkipped(reason="--no-replay", budget=False), ReplayStatus.skipped_disabled),
])
def test_replay_status_flattens_both_replay_shapes(replay, expected):
    """A budget skip and `--no-replay` are different claims; so is a replay that
    ran and did not reproduce."""
    finding = Finding(objective_id="o", confirmed=True,
                      probe_path="packs/example/discovered/p.yaml", replay=replay)
    assert ix._finding_row(finding, DISCOVER_ID, "x").replay_status is expected


def test_get_refuses_an_id_that_is_not_a_run_id():
    idx = RunIndex(FIXTURES)
    for hostile in ("../../etc/passwd", f"{GATE_ID}.json", "baseline", "",
                    f"{GATE_ID}\n"):
        with pytest.raises(RunNotFound):
            idx.get(hostile)


def test_get_on_a_missing_run_raises_run_not_found():
    with pytest.raises(RunNotFound):
        RunIndex(FIXTURES).get("20260807T140000000000-cafebabe-example")


def test_artifact_path_resolves_only_real_files():
    idx = RunIndex(FIXTURES)
    assert idx.artifact_path(GATE_ID) == FIXTURES / f"{GATE_ID}.json"
    assert idx.artifact_path("20260807T140001000000-cafebabe-example") is None
    assert idx.artifact_path("../../etc/passwd") is None


# --------------------------------------------------------------------------
# 8. the cache is keyed on (path, mtime_ns, size)
# --------------------------------------------------------------------------

def test_a_reread_is_served_from_cache_until_the_file_changes(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    rid = "20260807T150000000000-deadbeef-example"
    p = runs / f"{rid}.json"
    art = _gate_artifact()
    p.write_text(json.dumps(art.to_dict()))

    idx = RunIndex(runs)
    first = idx._load(p, rid, m.RunMode.gate)
    assert idx._load(p, rid, m.RunMode.gate) is first

    art.pack_name = "other"
    st = p.stat()
    p.write_text(json.dumps(art.to_dict()))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    second = idx._load(p, rid, m.RunMode.gate)
    assert second is not first
    assert idx.list()[0].pack_name == "other"


def _write_gate_runs(runs: Path, count: int) -> list[str]:
    runs.mkdir(parents=True, exist_ok=True)
    ids = []
    for n in range(count):
        rid = f"20260807T{n:06d}000000-deadbeef-example"
        runs.joinpath(f"{rid}.json").write_text(
            json.dumps(_gate_artifact().to_dict()))
        ids.append(rid)
    return ids


def test_the_artifact_cache_is_bounded(tmp_path):
    """F8. The cache retained every artifact it had ever loaded — *including*
    `probes[].trial_records`, i.e. the transcripts.

    That is unbounded growth keyed on "files this server has looked at", in a
    process an operator leaves running all afternoon over a directory that
    grows all afternoon. One full listing of a big `runs/` was enough to pin
    every transcript in it into memory for the life of the server.
    """
    runs = tmp_path / "runs"
    _write_gate_runs(runs, ix.CACHE_MAX_ENTRIES + 25)

    idx = RunIndex(runs)
    idx.list(limit=10_000)
    assert len(idx._cache) <= ix.CACHE_MAX_ENTRIES


def test_the_cache_evicts_least_recently_used_not_first_inserted(tmp_path):
    """Eviction ORDER is the whole difference between a bound and a bug.

    The detail page an operator is sitting on is re-read every poll while the
    listing sweeps past it. Under a FIFO bound that entry is evicted on
    schedule regardless, and re-parsed — transcripts and all — every time.

    So the test touches the entry FIFO would evict next and then forces exactly
    one eviction: under LRU the touched entry survives and its neighbour goes,
    under FIFO the reverse. Anything less specific passes under both.
    """
    runs = tmp_path / "runs"
    # `list()` walks candidates newest-id first, so the HIGHEST id is inserted
    # first and is therefore FIFO's next victim.
    ids = _write_gate_runs(runs, ix.CACHE_MAX_ENTRIES)
    idx = RunIndex(runs)
    idx.list(limit=10_000)
    assert len(idx._cache) == ix.CACHE_MAX_ENTRIES, "the cache must start full"

    watched = runs / f"{ids[-1]}.json"                  # inserted first
    neighbour = runs / f"{ids[-2]}.json"                # inserted second
    idx._load(watched, ids[-1], m.RunMode.gate)         # ...and re-read now

    newcomer_id = "20260807T999999000000-deadbeef-example"
    newcomer = runs / f"{newcomer_id}.json"
    newcomer.write_text(json.dumps(_gate_artifact().to_dict()))
    idx._load(newcomer, newcomer_id, m.RunMode.gate)    # exactly one eviction

    assert str(watched) in idx._cache, "the entry being watched was evicted"
    assert str(neighbour) not in idx._cache, "the least-recently-used one stayed"


def test_a_refreshed_entry_is_the_most_recent_not_the_next_victim(tmp_path):
    """The MISS path needs the same treatment, and it is the one that matters.

    The test above only exercises a cache *hit*. Re-assigning an existing key
    keeps its original position in a dict, so an artifact that was re-read
    because it changed on disk stayed exactly where it was and was evicted
    next — having just been parsed. Immutable artifacts never take this path;
    a **running** run's artifact is the one that changes, and it is the one an
    operator is watching while it does.
    """
    runs = tmp_path / "runs"
    ids = _write_gate_runs(runs, ix.CACHE_MAX_ENTRIES)
    idx = RunIndex(runs)
    idx.list(limit=10_000)

    refreshed = runs / f"{ids[-1]}.json"                # inserted first
    neighbour = runs / f"{ids[-2]}.json"                # inserted second
    st = refreshed.stat()
    refreshed.write_text(json.dumps(_gate_artifact().to_dict()))
    os.utime(refreshed, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    idx._load(refreshed, ids[-1], m.RunMode.gate)       # a MISS, then a re-parse

    newcomer_id = "20260807T999998000000-deadbeef-example"
    newcomer = runs / f"{newcomer_id}.json"
    newcomer.write_text(json.dumps(_gate_artifact().to_dict()))
    idx._load(newcomer, newcomer_id, m.RunMode.gate)    # exactly one eviction

    assert str(refreshed) in idx._cache, "evicted the artifact it had just parsed"
    assert str(neighbour) not in idx._cache


# --------------------------------------------------------------------------
# 8b. `.get()` degrades on VALUE-level surprises too, not just shape (F10)
# --------------------------------------------------------------------------

def test_a_check_with_an_unknown_tier_degrades_the_detail_rather_than_500ing(
        tmp_path):
    """F10. `_read_artifact` catches everything the *loader* can throw, but the
    wire models are validated later, in `.get()` — so an artifact that loads
    fine and then carries `tier: 0` raised `ValidationError` straight out of
    `.get()` and became a 500.

    A 500 is the one answer this module may not give: the run happened, the
    file is on disk, and "degradation, not failure" is the contract. The row
    greys out with a reason (the wire's `unreadable_artifact`), exactly as a
    shape-level surprise already did.
    """
    runs = _copy_fixtures(tmp_path / "runs")
    path = runs / f"{GATE_ID}.json"
    raw = json.loads(path.read_text())
    # `tier` is a closed enum on the wire and a bare int in the artifact; 0 is
    # the shape a future scoring tier would take.
    raw["probes"][0]["checks"][0]["tier"] = 0
    path.write_text(json.dumps(raw))

    detail = RunIndex(runs).get(GATE_ID)

    assert detail.degraded is True
    assert detail.degraded_reason
    assert detail.probes == []
    # the row is still identifiable — a greyed detail page, not a blank one
    assert detail.run_id == GATE_ID
    assert detail.pack_name == "example"


def test_a_readable_artifact_is_still_not_degraded(tmp_path):
    """The other half of the pair: the guard above must not swallow good runs."""
    detail = RunIndex(_copy_fixtures(tmp_path / "runs")).get(GATE_ID)
    assert detail.degraded is False
    assert detail.probes


# --------------------------------------------------------------------------
# 9. the real `runs/` directory — invariants, never a tally (R4-6)
# --------------------------------------------------------------------------

REAL_RUNS = Path(__file__).resolve().parents[2] / "runs"


def _assert_index_invariants(runs_dir: Path) -> list:
    """Every number computed from the directory as it stands — never a literal.

    The candidate set **mirrors `_candidates`' two documented exclusions**: the
    control sidecar is dropped by name (its stem `<run_id>.control` *passes* the
    run-id grammar, because `.` is a legal slug character), and `is_file()` is
    deliberately not applied (a directory or broken symlink named like a run is
    still meant to produce a degraded row). Getting either wrong makes this test
    red for a reason that has nothing to do with the index — and Task 20 writes
    control files into `runs/`, so that is not hypothetical.
    """
    candidates = sorted(runs_dir.glob("*.json"))
    indexable = [p for p in candidates
                 if not p.name.endswith(CONTROL_SUFFIX) and m.is_run_id(p.stem)]
    skipped = [p for p in candidates if p not in indexable]
    assert len(indexable) + len(skipped) == len(candidates)

    rows = RunIndex(runs_dir).list(limit=len(candidates) + 1)
    assert {r.run_id for r in rows} == {p.stem for p in indexable}

    # the degraded set is exactly the set that really fails the typed loader —
    # computed here, independently of the implementation under test
    expected_degraded = set()
    for p in indexable:
        try:
            _typed_loader_for(p.stem)(json.loads(p.read_text()))
        except Exception:
            expected_degraded.add(p.stem)
    assert {r.run_id for r in rows if r.degraded} == expected_degraded

    for row in rows:
        assert row.run_id and row.created_at and row.mode is not None
        if row.degraded:
            assert row.degraded_reason
            assert row.judge_usd is None and row.verdict_hint is None
    return rows


def test_the_invariants_hold_over_a_directory_with_task_20s_sidecars(tmp_path):
    """The same invariants, over a directory planted with everything hostile.

    This is the guard on the helper itself: Task 20 writes `.control.json` into
    `runs/`, and before this test the candidate set did not exclude it, so the
    real-directory test below would have gone red mid-plan for the wrong reason.
    """
    runs = _copy_fixtures(tmp_path / "runs")
    live = "20260807T190000000000-deadbeef-example"
    torn = "20260807T190001000000-deadbeef-example"
    runs.joinpath(f"{live}.json").write_text(json.dumps(_gate_artifact().to_dict()))
    runs.joinpath(f"{live}{CONTROL_SUFFIX}").write_text('{"action": "pause"}')
    runs.joinpath(f"{live}.events.jsonl").write_text('{"seq": 1}\n')
    runs.joinpath(f"{torn}.json").write_text("{")
    runs.joinpath("baseline.json").write_text("{}")
    runs.joinpath("logs").mkdir()

    ids = {r.run_id for r in _assert_index_invariants(runs)}
    assert {live, torn} <= ids
    assert f"{live}.control" not in ids
    assert "baseline" not in ids


@pytest.mark.skipif(not REAL_RUNS.is_dir(),
                    reason="runs/ is gitignored; CI has no such directory")
def test_the_real_runs_directory_indexes_without_raising():
    """The test that would have caught the minefield — as an INVARIANT (R4-6).

    Nothing is silently dropped, and everything that degrades still says who it
    is and why. Running another eval cannot red it.
    """
    rows = _assert_index_invariants(REAL_RUNS)
    assert rows, "runs/ exists but indexed nothing"


def _typed_loader_for(run_id: str):
    if run_id.endswith("-compare"):
        return CompareArtifact.from_dict
    if run_id.endswith("-discover"):
        return DiscoveryArtifact.from_dict
    return RunArtifact.from_dict
