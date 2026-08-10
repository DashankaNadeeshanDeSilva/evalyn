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
from pathlib import Path

import pytest

from evalyn.discovery.run import DiscoveryArtifact
from evalyn.engine.compare import CompareArtifact
from evalyn.engine.gate import GateResult
from evalyn.engine.run import ProbeResult, RunArtifact
from evalyn.ui import index as ix
from evalyn.ui import models as m
from evalyn.ui.index import (
    LoadedArtifact,
    RunIndex,
    RunNotFound,
    SidecarState,
    derive_status,
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


def test_a_cancelled_run_that_did_write_an_artifact_is_still_cancelled():
    assert derive_status(
        _loaded(_gate_artifact()),
        SidecarState(present=True, control=m.ControlAction.cancel, exit_code=0),
        None) is m.RunStatus.cancelled


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
    disc = idx.get(DISCOVER_ID)
    assert disc.discovery is not None and disc.compare is None
    assert disc.discovery.eval_status == "success"
    assert disc.discovery.findings


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


# --------------------------------------------------------------------------
# 9. the real `runs/` directory — invariants, never a tally (R4-6)
# --------------------------------------------------------------------------

REAL_RUNS = Path(__file__).resolve().parents[2] / "runs"


@pytest.mark.skipif(not REAL_RUNS.is_dir(),
                    reason="runs/ is gitignored; CI has no such directory")
def test_the_real_runs_directory_indexes_without_raising():
    """The test that would have caught the minefield — as an INVARIANT.

    Every number here is computed from the directory as it stands, so running
    another eval cannot red this test (R4-6). What is asserted is the
    *relationship*: nothing is silently dropped, and everything that degrades
    still says who it is and why.
    """
    candidates = sorted(p for p in REAL_RUNS.glob("*.json") if p.is_file())
    indexable = [p for p in candidates if m.is_run_id(p.stem)]
    skipped = [p for p in candidates if not m.is_run_id(p.stem)]
    assert len(indexable) + len(skipped) == len(candidates)

    rows = RunIndex(REAL_RUNS).list(limit=len(candidates) + 1)
    assert {r.run_id for r in rows} == {p.stem for p in indexable}

    # the degraded set is exactly the set that really fails the typed loader —
    # computed here, independently of the implementation under test
    expected_degraded = set()
    for p in indexable:
        try:
            raw = json.loads(p.read_text())
            _typed_loader_for(p.stem)(raw)
        except Exception:
            expected_degraded.add(p.stem)
    assert {r.run_id for r in rows if r.degraded} == expected_degraded

    for row in rows:
        assert row.run_id and row.created_at and row.mode is not None
        if row.degraded:
            assert row.degraded_reason
            assert row.judge_usd is None and row.verdict_hint is None


def _typed_loader_for(run_id: str):
    if run_id.endswith("-compare"):
        return CompareArtifact.from_dict
    if run_id.endswith("-discover"):
        return DiscoveryArtifact.from_dict
    return RunArtifact.from_dict
