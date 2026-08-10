"""The frozen API contract (Plan #4 Task 1).

These tests are deliberately *exact*, not "contains": the whole point of the
contract is that a later task cannot widen an enum or add a response field
without a red here and a matching edit to `ui/src/api/types.ts`. An assertion
like `"passed" in RunStatus` would pass under a wrong implementation that added
`errored` too — so every enum is asserted as a **set equality**, and every model
is asserted `extra="forbid"`.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import BaseModel, ValidationError

from evalyn.engine.compare import CompareArtifact
from evalyn.engine.run import RunArtifact
from evalyn.discovery.run import DiscoveryArtifact
from evalyn.ui import models as m

pytestmark = pytest.mark.ui

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "ui_runs"

GATE_FIXTURE = FIXTURES / "20260804T081544953468-53e4125b-example.json"
LEGACY_FIXTURE = FIXTURES / "20260723T080347-example.json"
DISCOVER_FIXTURE = FIXTURES / "20260805T101112000000-1a2b3c4d-example-discover.json"
COMPARE_FIXTURE = FIXTURES / "20260806T091011000000-9f8e7d6c-example-compare.json"


# --------------------------------------------------------------------------
# the fixture corpus — every later task's test data
# --------------------------------------------------------------------------

def test_fixture_corpus_has_exactly_four_artifacts():
    names = sorted(p.name for p in FIXTURES.glob("*.json"))
    assert names == [
        "20260723T080347-example.json",
        "20260804T081544953468-53e4125b-example.json",
        "20260805T101112000000-1a2b3c4d-example-discover.json",
        "20260806T091011000000-9f8e7d6c-example-compare.json",
    ]


def test_gate_fixture_loads_and_carries_trial_records():
    art = RunArtifact.from_dict(json.loads(GATE_FIXTURE.read_text()))
    assert sum(len(p.trial_records) for p in art.probes) == 12
    rec = art.probes[0].trial_records[0]
    assert set(rec) == {"epoch", "transcript", "session_seconds", "invariant_failures"}


def test_legacy_fixture_fails_from_dict():
    """Task 3's degraded path is built against exactly this raise."""
    with pytest.raises(ValueError, match="does not match|predates"):
        RunArtifact.from_dict(json.loads(LEGACY_FIXTURE.read_text()))


def test_discover_fixture_round_trips():
    art = DiscoveryArtifact.from_dict(json.loads(DISCOVER_FIXTURE.read_text()))
    assert len(art.findings) == 2
    assert art.confirmed_count == 2


def test_compare_fixture_round_trips():
    """R4-4: the compare fixture is synthesised, so this IS its acceptance."""
    art = CompareArtifact.from_dict(json.loads(COMPARE_FIXTURE.read_text()))
    assert sorted(art.categories) == ["grounding", "injection"]
    assert sorted(art.hard_metrics) == ["grounding", "injection"]


def test_fixtures_carry_no_real_identifiers():
    """R4-3: committed to a public repo."""
    blob = "\n".join(p.read_text() for p in FIXTURES.glob("*.json"))
    for forbidden in ("/Users/", "@gmail.com", "twincore", "dashanka"):
        assert forbidden.lower() not in blob.lower(), forbidden


# --------------------------------------------------------------------------
# enums — asserted as EXACT member sets (spec §7 item 2)
# --------------------------------------------------------------------------

def test_run_mode_members_exact():
    assert {e.value for e in m.RunMode} == {"gate", "compare", "discover"}


def test_run_status_members_exact():
    assert {e.value for e in m.RunStatus} == {
        "passed", "gate_failed", "invalid", "running", "paused", "cancelled",
        "interrupted", "failed_to_start", "unreadable",
    }


def test_error_code_members_exact():
    assert {e.value for e in m.ErrorCode} == {
        "not_found", "unreadable_artifact", "pack_error", "launch_refused", "busy",
    }


def test_verdict_tier_members_exact():
    assert {e.value for e in m.VerdictTier} == {"1", "2", "3", "abstained"}


def test_verdict_hint_members_exact():
    assert {e.value for e in m.VerdictHint} == {"passed", "failed", "unknown"}


def test_control_action_members_exact():
    assert {e.value for e in m.ControlAction} == {"pause", "resume", "cancel"}


def test_replay_status_members_exact():
    assert {e.value for e in m.ReplayStatus} == {
        "reproduced", "not_reproduced", "skipped_budget", "skipped_disabled",
    }


def test_turn_role_members_exact():
    assert {e.value for e in m.TurnRole} == {"user", "assistant"}


def test_trend_metric_members_exact():
    assert {e.value for e in m.TrendMetric} == {
        "mean_score", "pass_k", "pass_at_k", "judge_usd",
    }


def test_event_name_members_exact():
    """Spec §7 item 8 — the SSE name set is part of the contract."""
    assert {e.value for e in m.EventName} == {
        "run.started", "spend.updated", "artifact.written", "run.finished",
        "trial.started", "turn.sent", "turn.received", "trial.finished",
        "probe.scored", "pair.judged", "agent.step", "agent.reply",
        "confirm.result", "finding.staged", "replay.result",
        "control.paused", "control.resumed", "control.cancelled", "heartbeat",
    }


def test_enums_are_str_valued():
    """`str` mixin so `json.dumps` and the TS union agree without a coercion."""
    for enum in (m.RunMode, m.RunStatus, m.ErrorCode, m.VerdictTier, m.VerdictHint,
                 m.ControlAction, m.ReplayStatus, m.TurnRole, m.TrendMetric, m.EventName):
        for member in enum:
            assert isinstance(member, str), f"{enum.__name__}.{member.name}"


# --------------------------------------------------------------------------
# extra="forbid" on EVERY model (R4-5)
# --------------------------------------------------------------------------

def _all_models() -> list[type[BaseModel]]:
    return [obj for name in m.__all__
            if isinstance(obj := getattr(m, name), type)
            and issubclass(obj, BaseModel)]


def test_every_exported_model_forbids_extra():
    found = _all_models()
    assert len(found) >= 20, f"only {len(found)} models exported"
    for model in found:
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_extra_key_is_rejected():
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        m.Capabilities(transcripts=True, trial_records=True, hard_metrics=False,
                       screenshots=True)


def test_run_summary_rejects_an_unknown_key():
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        m.RunSummary(
            run_id="20260804T081544953468-53e4125b-example",
            mode=m.RunMode.gate,
            pack_name="example",
            created_at="2026-08-04T08:15:44.953115+00:00",
            status=m.RunStatus.passed,
            capabilities=m.Capabilities(transcripts=True, trial_records=True,
                                        hard_metrics=True),
            exit_code=0,   # not in the contract
        )


# --------------------------------------------------------------------------
# `run_id` grammar (spec §7 item 1) — a path SEGMENT, never a path
# --------------------------------------------------------------------------

@pytest.mark.parametrize("run_id", [
    "20260804T081544953468-53e4125b-example",
    "20260806T091011000000-9f8e7d6c-example-compare",
    "20260723T080347-example",              # the legacy relaxation
])
def test_run_id_grammar_accepts(run_id):
    assert _summary(run_id=run_id).run_id == run_id


@pytest.mark.parametrize("run_id", [
    "../etc/passwd",
    "runs/20260804T081544953468-53e4125b-example",
    "20260804T081544953468-53e4125b-example/..",
    "20260804T081544953468-53e4125b-example.json",   # a filename, not an id
    "baseline",
    "",
])
def test_run_id_grammar_rejects(run_id):
    with pytest.raises(ValidationError):
        _summary(run_id=run_id)


#: Every shape the two run-id authorities are ever asked about. `is_run_id`
#: (used by `RunIndex` to filter a directory listing) and the pydantic `RunId`
#: type (used to validate a path parameter) must NEVER disagree about one of
#: these: a value the filter admits and the type then rejects crashes row
#: construction, which breaks "degradation, not failure".
RUN_ID_CANDIDATES = [
    "20260804T081544953468-53e4125b-example",
    "20260806T091011000000-9f8e7d6c-example-compare",
    "20260723T080347-example",
    "20260723T080347-example\n",          # `$` matches before a trailing \n
    "20260804T081544953468-53e4125b-example\n",
    "\n20260723T080347-example",
    "20260723T080347-example\nrm -rf /",
    "20260804T081544953468-53e4125b-example.json",
    "20260804T081544953468-53e4125b-example.json\n",
    "../etc/passwd",
    "runs/20260723T080347-example",
    "baseline",
    "baseline.json",
    "",
    " 20260723T080347-example",
    "20260723T080347-example ",
]


@pytest.mark.parametrize("value", RUN_ID_CANDIDATES)
def test_is_run_id_and_the_RunId_type_never_disagree(value):
    """I3: `RUN_ID_RE.match()` let `"…-example\\n"` through because Python's `$`
    matches before a trailing newline; pydantic validates the same pattern with
    the Rust engine, which has no such tolerance. The filter said yes, the type
    said no, and the row blew up. Both authorities must answer identically."""
    predicate = m.is_run_id(value)
    try:
        _summary(run_id=value)
        typed = True
    except ValidationError:
        typed = False
    assert predicate is typed, f"is_run_id={predicate} but RunId={typed} for {value!r}"


@pytest.mark.parametrize("value", [
    "20260723T080347-example\n",
    "20260804T081544953468-53e4125b-example\n",
    "20260723T080347-example\nrm -rf /",
])
def test_a_trailing_newline_is_not_a_run_id(value):
    assert m.is_run_id(value) is False


def _summary(**over):
    kwargs = dict(
        run_id="20260804T081544953468-53e4125b-example",
        mode=m.RunMode.gate,
        pack_name="example",
        created_at="2026-08-04T08:15:44.953115+00:00",
        status=m.RunStatus.passed,
        capabilities=m.Capabilities(transcripts=True, trial_records=True,
                                    hard_metrics=True),
    )
    kwargs.update(over)
    return m.RunSummary(**kwargs)


# --------------------------------------------------------------------------
# RunSummary over each of the four fixtures
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path,mode,degraded", [
    (GATE_FIXTURE, m.RunMode.gate, False),
    (LEGACY_FIXTURE, m.RunMode.gate, True),
    (DISCOVER_FIXTURE, m.RunMode.discover, False),
    (COMPARE_FIXTURE, m.RunMode.compare, False),
])
def test_run_summary_round_trips_each_fixture(path, mode, degraded):
    raw = json.loads(path.read_text())
    summary = m.RunSummary(
        run_id=path.stem,
        mode=mode,
        pack_name=raw["pack_name"],
        created_at=raw["created_at"],
        status=m.RunStatus.unreadable if degraded else m.RunStatus.passed,
        degraded=degraded,
        degraded_reason="pre-Plan-#2a schema" if degraded else None,
        capabilities=m.Capabilities(transcripts=not degraded,
                                    trial_records=not degraded,
                                    hard_metrics=mode is m.RunMode.compare),
        judge_usd=None if degraded else raw.get("judge_usd"),
        verdict_hint=m.VerdictHint.unknown if degraded else m.VerdictHint.passed,
    )
    reloaded = m.RunSummary.model_validate(json.loads(summary.model_dump_json()))
    assert reloaded == summary
    assert reloaded.run_id == path.stem


def test_degraded_row_validates_with_null_metrics_and_a_real_run_id():
    """Spec §7 item 4 — degradation, not failure."""
    row = m.RunSummary(
        run_id="20260723T080347-example",
        mode=m.RunMode.gate,
        pack_name=None,
        created_at="2026-07-23T08:03:47+00:00",
        status=m.RunStatus.unreadable,
        degraded=True,
        degraded_reason="artifact predates the Plan #2a schema",
        capabilities=m.Capabilities(transcripts=False, trial_records=False,
                                    hard_metrics=False),
        judge_usd=None,
        verdict_hint=None,
    )
    assert row.degraded is True
    assert row.judge_usd is None and row.verdict_hint is None
    assert row.run_id and row.created_at and row.mode is m.RunMode.gate


def test_run_summary_defaults_are_the_non_degraded_ones():
    row = _summary()
    assert row.degraded is False
    assert row.degraded_reason is None
    assert row.judge_usd is None
    assert row.verdict_hint is None


def test_degraded_reason_is_required_when_degraded():
    """A greyed row with no tooltip is the failure this guards."""
    with pytest.raises(ValidationError, match="degraded_reason"):
        _summary(degraded=True, degraded_reason=None)


# --------------------------------------------------------------------------
# error envelope (spec §7 item 3) — never a bare FastAPI {"detail": …}
# --------------------------------------------------------------------------

def test_error_envelope_shape():
    env = m.ErrorEnvelope(error=m.ApiError(code=m.ErrorCode.not_found,
                                           message="no such run"))
    assert json.loads(env.model_dump_json()) == {
        "error": {"code": "not_found", "message": "no such run", "detail": None}}


def test_the_contract_records_the_422_wrapping_obligation():
    """I6: the framework generates non-2xx responses this module never sees.
    FastAPI answers a malformed body with its own `RequestValidationError` →
    422 `{"detail": [...]}`, which is not `ErrorEnvelope`. Task 6 owns the
    handlers, and has no way to discover the obligation unless the frozen
    contract carries it — so the requirement lives in the docstrings, where a
    reader of the module cannot miss it."""
    module_doc = m.__doc__ or ""
    for token in ("422", "RequestValidationError", "ErrorEnvelope",
                  "exception handler"):
        assert token in module_doc, f"module docstring must name {token!r}"

    envelope_doc = m.ErrorEnvelope.__doc__ or ""
    for token in ("422", "RequestValidationError", "HTTPException"):
        assert token in envelope_doc, f"ErrorEnvelope docstring must name {token!r}"


def test_the_422_error_code_mapping_is_expressible_in_the_closed_set():
    """The set is closed, so the wrapped 422 must map onto a member that
    already exists — the docstring names which, and this proves it is real."""
    assert m.ErrorCode.launch_refused in m.ErrorCode
    body = m.ErrorEnvelope(error=m.ApiError(code=m.ErrorCode.launch_refused,
                                            message="invalid request body",
                                            detail="mode: input not a RunMode"))
    assert json.loads(body.model_dump_json())["error"]["code"] == "launch_refused"


def test_error_code_must_come_from_the_closed_enum():
    with pytest.raises(ValidationError):
        m.ApiError(code="teapot", message="nope")


# --------------------------------------------------------------------------
# the remaining response models
# --------------------------------------------------------------------------

def test_run_detail_extends_run_summary():
    assert issubclass(m.RunDetail, m.RunSummary)
    detail = m.RunDetail(**_summary().model_dump(), pack_hash="0" * 64,
                         judge_model="mockllm/model")
    assert detail.probes == [] and detail.compare is None and detail.discovery is None


#: Every model whose body can carry free text the redactor rewrites. The
#: chokepoint must be able to *say* it ran, and `extra="forbid"` means the
#: field cannot be bolted on by middleware later — it has to be here.
REDACTABLE_MODELS = ["RunDetail", "GateVerdict", "Scoreboard", "TrialView",
                     "CheckView", "TranscriptTurn", "FindingRow", "FindingDetail"]


@pytest.mark.parametrize("name", REDACTABLE_MODELS)
def test_redactable_models_can_record_that_redaction_ran(name):
    """I2: `RunDetail`, `GateVerdict` and `Scoreboard` had nowhere to record it.
    `report_md`, `evidence` and the label fields all pass through the redactor,
    so a view that was scrubbed was indistinguishable from one that was not —
    and the `RedactedChip` had nothing to bind to."""
    field = getattr(m, name).model_fields.get("redacted")
    assert field is not None, f"{name} has no `redacted` flag"
    assert field.annotation is bool
    assert field.default is False, "un-redacted is the default, never None"


@pytest.mark.parametrize("name", REDACTABLE_MODELS)
def test_the_redaction_flag_cannot_be_added_by_middleware_later(name):
    """Why the field is structural and not cosmetic: `extra="forbid"` means a
    later task literally cannot inject the key into the response dict."""
    model = getattr(m, name)
    assert model.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        model.model_validate({"was_redacted": True})


def test_gate_verdict_and_scoreboard_default_to_not_redacted():
    verdict = m.GateVerdict(run_id="20260723T080347-example", exit_code=0)
    assert verdict.redacted is False
    board = m.Scoreboard(run_id="20260723T080347-example",
                         created_at="2026-07-23T08:03:47+00:00",
                         label_a="a", label_b="b", redacted=True)
    assert board.redacted is True
    detail = m.RunDetail(**_summary().model_dump(), redacted=True)
    assert detail.redacted is True


def test_check_view_tier_is_typed_with_the_verdict_tier_enum():
    """I1: `VerdictTier` was exported and asserted but typed on nothing, so
    Task 9's `VerdictBadge` had no field to read. `tier: int` also let a
    fourth tier onto the wire silently."""
    assert m.CheckView.model_fields["tier"].annotation is m.VerdictTier


def test_check_view_accepts_the_int_tier_the_artifacts_store():
    """The artifact check dicts carry `tier` as an int — the mapping layer must
    not have to stringify it, and `abstained` is not tier 0."""
    view = m.CheckView(check="grounded", tier=2, required=True, weight=1.0)
    assert view.tier is m.VerdictTier.tier_2
    assert m.CheckView(check="x", tier="3", required=False, weight=0.0).tier \
        is m.VerdictTier.tier_3
    assert m.CheckView(check="x", tier="abstained", required=False, weight=0.0).tier \
        is m.VerdictTier.abstained
    # the wire value is the string the TS union uses, never the int
    assert json.loads(view.model_dump_json())["tier"] == "2"


@pytest.mark.parametrize("tier", [0, 4, "4", "tier_1", "", None, 1.5, True, False])
def test_check_view_rejects_a_tier_outside_the_closed_set(tier):
    with pytest.raises(ValidationError):
        m.CheckView(check="x", tier=tier, required=True, weight=1.0)


def test_trial_view_carries_ordered_turns_and_a_redaction_flag():
    view = m.TrialView(
        run_id="20260804T081544953468-53e4125b-example",
        probe_id="grounding-work-history", epoch=1,
        turns=[m.TranscriptTurn(role=m.TurnRole.user, text="hi"),
               m.TranscriptTurn(role=m.TurnRole.assistant, text="hello")],
        session_seconds=0.028, invariant_failures=0)
    assert [t.role.value for t in view.turns] == ["user", "assistant"]
    assert view.redacted is False


def test_scoreboard_keeps_hard_metrics_beside_verdicts():
    raw = json.loads(COMPARE_FIXTURE.read_text())
    board = m.Scoreboard(
        run_id=COMPARE_FIXTURE.stem, pack_name=raw["pack_name"],
        created_at=raw["created_at"], label_a=raw["label_a"], label_b=raw["label_b"],
        created_at_a=raw["created_at_a"], created_at_b=raw["created_at_b"],
        categories={k: m.CategoryTally(**v) for k, v in raw["categories"].items()},
        hard_metrics={k: m.HardMetrics(**v) for k, v in raw["hard_metrics"].items()},
        excluded_pairs=raw["excluded_pairs"], judge_usd=raw["judge_usd"],
        rubric_scores_untrusted=raw["rubric_scores_untrusted"])
    assert board.categories["grounding"].wins_b == 4
    assert board.hard_metrics["injection"].invariant_failures_a == 1
    assert "winner" not in board.model_dump(), "compare is advisory — no combined winner"


def test_finding_row_and_detail():
    raw = json.loads(DISCOVER_FIXTURE.read_text())
    f0, f1 = raw["findings"]
    row = m.FindingRow(probe_id="discovered-hallucination-abcd1234",
                       run_id=DISCOVER_FIXTURE.stem,
                       objective_id=f0["objective_id"], confirmed=f0["confirmed"],
                       probe_path=f0["probe_path"], persona_id=f0["persona_id"],
                       playbook_id=f0["playbook_id"],
                       replay_status=m.ReplayStatus.reproduced)
    assert row.duplicate_of is None and row.redacted is False
    skipped = m.FindingRow(probe_id="discovered-injection-ef567890",
                           run_id=DISCOVER_FIXTURE.stem,
                           objective_id=f1["objective_id"], confirmed=f1["confirmed"],
                           probe_path=f1["probe_path"],
                           duplicate_of=f1["duplicate_of"],
                           replay_status=m.ReplayStatus.skipped_budget)
    assert skipped.replay_status is m.ReplayStatus.skipped_budget
    detail = m.FindingDetail(**row.model_dump(), probe_yaml="id: x\n",
                             provenance={"objective": "hallucination"})
    assert detail.provenance["objective"] == "hallucination"
    assert detail.replay is None


def test_trend_series_points_are_run_correlated():
    series = m.TrendSeries(
        pack_name="example", probe_id="grounding-work-history",
        metric=m.TrendMetric.mean_score,
        points=[m.TrendPoint(run_id="20260723T080347-example",
                             created_at="2026-07-23T08:03:47+00:00", value=1.0)])
    assert series.points[0].run_id == "20260723T080347-example"


def test_trust_report_never_calibrated_state():
    """Task 14 (c): a pack with no calibration.json is a legitimate 200."""
    report = m.TrustReport(pack_name="example", judge_model=None, agreement=None,
                           stale=True, stale_reason="never calibrated")
    assert report.agreement is None
    assert report.per_rubric_agreement == {} and report.per_criterion_counts == {}
    assert not hasattr(report, "kappa"), "±1 agreement as shipped — never named kappa"


def test_launch_request_cannot_carry_a_pack_path():
    """Safety guard 1: the server never accepts a pack PATH from a body."""
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        m.LaunchRequest(mode=m.RunMode.gate, pack_id="example", confirm="example",
                        pack_path="/Users/someone/packs/prod")
    req = m.LaunchRequest(mode=m.RunMode.discover, pack_id="example",
                          confirm="example", max_usd=2.5)
    assert req.max_usd == 2.5 and req.objectives == []


def test_control_request_action_is_closed():
    assert m.ControlRequest(action="pause").action is m.ControlAction.pause
    with pytest.raises(ValidationError):
        m.ControlRequest(action="kill")


def test_run_list_page_is_cursor_paginated():
    """Spec §7 item 9 — cursor by `(created_at, run_id)` descending."""
    cursor = m.make_cursor("2026-08-04T08:15:44+00:00",
                           "20260804T081544953468-53e4125b-example")
    page = m.RunListPage(items=[_summary()], next_cursor=cursor)
    assert page.next_cursor == cursor
    assert m.RunListPage(items=[]).next_cursor is None


def test_cursor_is_an_opaque_composite_of_created_at_and_run_id():
    """I5: keyed on `created_at` alone the cursor is neither unique nor stable."""
    cursor = m.make_cursor("2026-08-04T08:15:44+00:00",
                           "20260804T081544953468-53e4125b-example")
    assert cursor == ("2026-08-04T08:15:44+00:00"
                      "|20260804T081544953468-53e4125b-example")
    assert m.parse_cursor(cursor) == ("2026-08-04T08:15:44+00:00",
                                      "20260804T081544953468-53e4125b-example")


def test_cursor_is_tie_safe_when_two_runs_share_a_timestamp():
    """The bug: two artifacts written in the same second collapse to one cursor,
    so the next page either repeats a row or drops one. `run_id` breaks the tie
    and gives `(created_at, run_id)` a total order."""
    same = "2026-08-04T08:15:44+00:00"
    lo = m.make_cursor(same, "20260804T081544953468-53e4125b-example")
    hi = m.make_cursor(same, "20260804T081544953468-aaaaaaaa-example")
    assert lo != hi, "a tie must still produce two distinct cursors"
    assert m.parse_cursor(hi) > m.parse_cursor(lo)
    # descending — newest first, ties broken by run_id descending
    assert sorted([lo, hi], key=m.parse_cursor, reverse=True) == [hi, lo]


def test_a_bare_timestamp_is_rejected_as_a_cursor():
    """The tie-unsafe form must not be constructible — Task 7 cannot ship it."""
    with pytest.raises(ValidationError, match="cursor"):
        m.RunListPage(items=[_summary()], next_cursor="2026-08-04T08:15:44+00:00")
    with pytest.raises(ValueError, match="cursor"):
        m.parse_cursor("2026-08-04T08:15:44+00:00")


def test_make_cursor_refuses_a_run_id_that_would_break_parsing():
    with pytest.raises(ValueError, match="run_id"):
        m.make_cursor("2026-08-04T08:15:44+00:00", "not|a|run|id")


# --------------------------------------------------------------------------
# redaction marker (spec §7 item 6) — ONE format, no second
# --------------------------------------------------------------------------

def test_redaction_marker_has_exactly_one_format():
    assert m.redaction_marker("email") == "«redacted:email»"
    assert m.REDACTION_MARKER_RE.fullmatch("«redacted:home_path»")
    assert not m.REDACTION_MARKER_RE.fullmatch("[redacted]")
    assert not m.REDACTION_MARKER_RE.fullmatch("«redacted»")


def test_heartbeat_interval_is_pinned():
    assert m.HEARTBEAT_SECONDS == 15.0


# --------------------------------------------------------------------------
# isolation — models.py is imported by the CLI-adjacent package
# --------------------------------------------------------------------------

def test_models_module_does_not_import_fastapi():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(m))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"fastapi", "starlette", "uvicorn"}, imported


def test_ui_package_init_is_docstring_only():
    """`import evalyn.ui` must stay free of fastapi/uvicorn — the CLI touches it."""
    import ast

    import evalyn.ui
    tree = ast.parse(pathlib.Path(evalyn.ui.__file__).read_text())
    assert all(isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
               for node in tree.body), ast.dump(tree)
