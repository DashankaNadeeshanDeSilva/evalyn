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
import types
import typing

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
# the list endpoints are ENVELOPES, not bare arrays (R4-28), and the packs /
# launch-ack models the cockpit needs
# --------------------------------------------------------------------------

def _pack_row(**over):
    return m.PackRow(**{"id": "pack-0", "name": "example",
                        "path": "~/Drive/Projects/evalyn/packs/example"} | over)


@pytest.mark.parametrize("page", ["PackListPage", "DiscoveryListPage"])
def test_the_other_two_list_endpoints_are_enveloped_like_run_list_page(page):
    """A bare top-level array can never gain a field. Both lists get the same
    `{items, next_cursor}` shape, and the same tie-safe cursor validator."""
    cls = getattr(m, page)
    assert cls().items == [] and cls().next_cursor is None
    cursor = m.make_cursor("2026-08-05T10:11:12+00:00",
                           "20260805T101112000000-1a2b3c4d-example-discover")
    assert cls(next_cursor=cursor).next_cursor == cursor
    with pytest.raises(ValidationError, match="cursor"):
        cls(next_cursor="2026-08-05T10:11:12+00:00")


def test_pack_row_carries_an_allowlist_index_and_a_display_safe_label():
    row = _pack_row()
    assert row.version is None and row.probe_count == 0
    assert row.has_calibration is False
    # `id` is the index into the `--target` allowlist; the *name* is what
    # `LaunchRequest.confirm` must echo, and the two are not interchangeable.
    assert m.LaunchRequest(mode="gate", pack_id=row.id, confirm=row.name).confirm \
        == "example"


def test_pack_list_page_items_are_pack_rows():
    page = m.PackListPage(items=[_pack_row()])
    assert page.items[0].name == "example"
    with pytest.raises(ValidationError):
        m.PackListPage(items=[{"id": "pack-0"}])          # name/path missing


def test_validation_report_echoes_the_pack_id_the_engine_dataclass_lacks():
    """Deliberately NOT a mirror of `engine.validate.ValidationReport`: the SPA
    validates from a list and must attribute the response to its request."""
    report = m.ValidationReport(pack_id="pack-0", ok=False, errors=["boom"])
    assert report.pack_id == "pack-0" and report.warnings == []
    with pytest.raises(ValidationError, match="pack_id"):
        m.ValidationReport(ok=True)


def test_pack_axes_budget_ceiling_is_a_plain_float_never_null():
    """`TargetSpec.budget.max_usd_per_run` has a default and no null form —
    `0` disables the check, which is not the same as "unknown"."""
    assert m.PackAxes(pack_id="pack-0").max_usd_per_run == 5.0
    assert m.PackAxes(pack_id="pack-0", max_usd_per_run=0).max_usd_per_run == 0
    with pytest.raises(ValidationError):
        m.PackAxes(pack_id="pack-0", max_usd_per_run=None)


def test_launch_and_control_responses_carry_the_run_id_grammar():
    """The launch `run_id` is the stem of the artifact that later appears, so it
    must satisfy the same grammar as the id on that artifact's row."""
    run_id = "20260804T081544953468-53e4125b-example"
    assert m.LaunchResponse(run_id=run_id).run_id == run_id
    assert m.ControlResponse(run_id=run_id, accepted=True).accepted is True
    for bad in ("../etc/passwd", f"{run_id}.json"):
        with pytest.raises(ValidationError):
            m.LaunchResponse(run_id=bad)
        with pytest.raises(ValidationError):
            m.ControlResponse(run_id=bad, accepted=True)


def test_control_response_is_not_the_acknowledgement():
    """`accepted=True` says the request was well-formed, nothing more — the
    `control.*` SSE event is the ack. Pinned so the docstring cannot rot."""
    assert "not the acknowledgement" in m.ControlResponse.__doc__
    assert m.EventName.control_paused.value.startswith("control.")


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
# C1 / R4-14 — /api/meta is redaction-EXEMPT, so it must be safe by itself
# --------------------------------------------------------------------------

def test_display_path_collapses_the_current_home_directory(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/alice")
    assert m.display_path("/Users/alice/Drive/x/runs") == "~/Drive/x/runs"
    assert m.display_path("/Users/alice") == "~"
    assert m.display_path("/Users/alice/") == "~/"


def test_display_path_is_not_hardcoded_to_macos(monkeypatch):
    monkeypatch.setenv("HOME", "/home/bob")
    assert m.display_path("/home/bob/evalyn/runs") == "~/evalyn/runs"
    assert m.display_path("/Users/alice/Drive/x") == "/Users/alice/Drive/x"


@pytest.mark.parametrize("path", [
    "/Users",                       # a bare /Users prefix is NOT the home dir
    "/Users/",
    "/Users/alicia/Drive/x",        # a different user whose name starts the same
    "/Users/alice2/runs",           # prefix without a separator boundary
    "/opt/evalyn/runs",             # not under home at all
    "/",
    "runs",                         # relative — nothing to collapse
    "~/Drive/x",                    # already collapsed; idempotent
    "",
])
def test_display_path_leaves_everything_else_alone(monkeypatch, path):
    """R4-14: the helper must be correct when the path is not under the home
    directory, and must not collapse a `/Users` prefix that isn't this user."""
    monkeypatch.setenv("HOME", "/Users/alice")
    assert m.display_path(path) == path


def test_display_path_is_idempotent(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/alice")
    once = m.display_path("/Users/alice/Drive/x/runs")
    assert m.display_path(once) == once


def test_meta_response_never_ships_an_absolute_home_path(monkeypatch):
    """C1: `GET /api/meta` is one of exactly two routes exempt from redaction,
    and `runs_dir` is the single field most likely to hold `/Users/<name>/…`.
    The SPA renders it, on a shared screen. R4-14: keep the field, fix the
    value — and `packs` leaks identically, so it gets the same treatment."""
    monkeypatch.setenv("HOME", "/Users/alice")
    meta = m.MetaResponse(
        version="0.2.0",
        runs_dir="/Users/alice/Drive/Projects/Evalyn_eval_agent/runs",
        packs=["/Users/alice/Drive/Projects/Evalyn_eval_agent/packs/example",
               "/opt/shared/packs/prod"],
    )
    assert meta.runs_dir == "~/Drive/Projects/Evalyn_eval_agent/runs"
    assert meta.packs == ["~/Drive/Projects/Evalyn_eval_agent/packs/example",
                          "/opt/shared/packs/prod"]
    blob = meta.model_dump_json()
    assert "/Users/alice" not in blob
    assert "alice" not in blob


def test_meta_response_collapses_on_revalidation_too(monkeypatch):
    """The SPA round-trips the body; a re-parsed MetaResponse must not be a
    second chance to smuggle the absolute path back in."""
    monkeypatch.setenv("HOME", "/Users/alice")
    reloaded = m.MetaResponse.model_validate(
        {"version": "0.2.0", "runs_dir": "/Users/alice/runs",
         "packs": ["/Users/alice/packs/example"]})
    assert reloaded.runs_dir == "~/runs"
    assert reloaded.packs == ["~/packs/example"]


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


# --------------------------------------------------------------------------
# I4 / R4-15 — the freeze, ENFORCED: every model's exact structure
#
# Everything above pins *behaviour* — an enum's members, a validator, a
# rejected key. None of it noticed a **renamed or deleted field**: nine models
# had no structural assertion at all, so `ProbeRow.pass_k -> passk` was a
# silent, green change to a module whose entire purpose is that such a change
# cannot be silent. The dict below is the freeze itself. Editing it is the
# deliberate act of re-cutting the contract, and every edit must land in
# `ui/src/api/types.ts` in the same commit.
#
# R4-15: the model list is derived from `__all__`, never hand-listed, so a
# model added later is covered the moment it is exported rather than joining
# the unpinned nine.
# --------------------------------------------------------------------------

def _type_name(tp) -> str:
    """Render an annotation the way a reader would have written it."""
    if tp is type(None):
        return "None"
    if hasattr(tp, "__metadata__"):                  # Annotated[X, ...] -> X
        return _type_name(tp.__origin__)
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(_type_name(a) for a in typing.get_args(tp))
    if origin is not None:
        args = ", ".join(_type_name(a) for a in typing.get_args(tp))
        return f"{getattr(origin, '__name__', str(origin))}[{args}]"
    return getattr(tp, "__name__", str(tp))


def _structure(model) -> dict[str, tuple[str, bool]]:
    """`{field: (annotation, is_required)}` — the whole shape of one model."""
    return {name: (_type_name(field.annotation), field.is_required())
            for name, field in model.model_fields.items()}


#: Named separately because `RunDetail` is a strict **superset** of the row —
#: the SPA renders the detail page from a warm cache entry, which only works
#: while that stays true. Same for `FindingDetail` over `FindingRow`.
_RUN_SUMMARY = {
    "run_id": ("str", True),
    "mode": ("RunMode", True),
    "pack_name": ("str | None", False),
    "created_at": ("str", True),
    "status": ("RunStatus", True),
    "degraded": ("bool", False),
    "degraded_reason": ("str | None", False),
    "capabilities": ("Capabilities", True),
    "judge_usd": ("float | None", False),
    "verdict_hint": ("VerdictHint | None", False),
}

_FINDING_ROW = {
    "probe_id": ("str", True),
    "run_id": ("str | None", False),
    "objective_id": ("str", True),
    "confirmed": ("bool", True),
    "probe_path": ("str", True),
    "category": ("str | None", False),
    "safety_critical": ("bool", False),
    "persona_id": ("str", False),
    "playbook_id": ("str", False),
    "duplicate_of": ("str | None", False),
    "duplicate_reason": ("str | None", False),
    "replay_status": ("ReplayStatus | None", False),
    "created_at": ("str | None", False),
    "redacted": ("bool", False),
}

EXPECTED_STRUCTURE: dict[str, dict[str, tuple[str, bool]]] = {
    "ApiError": {
        "code": ("ErrorCode", True),
        "message": ("str", True),
        "detail": ("str | None", False),
    },
    "ErrorEnvelope": {"error": ("ApiError", True)},
    "Capabilities": {
        "transcripts": ("bool", True),
        "trial_records": ("bool", True),
        "hard_metrics": ("bool", True),
    },
    "CheckView": {
        "check": ("str", True),
        "tier": ("VerdictTier", True),
        "required": ("bool", True),
        "weight": ("float", True),
        "passed": ("bool | None", False),
        "score": ("float | None", False),
        "turn": ("int | None", False),
        "evidence": ("str", False),
        "unsure": ("bool", False),
        "redacted": ("bool", False),
    },
    "TranscriptTurn": {
        "role": ("TurnRole", True),
        "text": ("str", True),
        "redacted": ("bool", False),
    },
    "ProbeRow": {
        "id": ("str", True),
        "category": ("str", True),
        "kind": ("str", True),
        "safety_critical": ("bool", True),
        "samples": ("int", True),
        "trials": ("int", True),
        "expected_trials": ("int", False),
        "pass_at_k": ("float | None", False),
        "pass_k": ("float | None", False),
        "mean_score": ("float | None", False),
        "unsure_trials": ("int", False),
        "checks": ("list[CheckView]", False),
        "trial_epochs": ("list[int]", False),
    },
    "RunSummary": _RUN_SUMMARY,
    "RunDetail": {
        **_RUN_SUMMARY,
        "pack_hash": ("str | None", False),
        "judge_model": ("str | None", False),
        "log_path": ("str | None", False),
        "rubric_scores_untrusted": ("bool", False),
        "total_unsure_trials": ("int | None", False),
        "cancelled": ("bool", False),
        "probes": ("list[ProbeRow]", False),
        "redacted": ("bool", False),
        "compare": ("Scoreboard | None", False),
        "discovery": ("DiscoverySummary | None", False),
    },
    "DiscoverySummary": {
        "agent_model": ("str | None", False),
        "rubric_judge_model": ("str | None", False),
        "eval_status": ("str", False),
        "error_count": ("int", False),
        "sessions_total": ("int", False),
        "confirmed_count": ("int", False),
        "live_spend_usd": ("float | None", False),
        "reconciled_spend_usd": ("float | None", False),
        "effective_spend_usd": ("float | None", False),
        "budget_exhausted": ("bool", False),
        "partial": ("bool", False),
        "objectives": ("list[str]", False),
        "findings": ("list[FindingRow]", False),
    },
    "RunListPage": {
        "items": ("list[RunSummary]", False),
        "next_cursor": ("str | None", False),
    },
    "TrialView": {
        "run_id": ("str", True),
        "probe_id": ("str", True),
        "epoch": ("int", True),
        "turns": ("list[TranscriptTurn]", False),
        "session_seconds": ("float | None", False),
        "invariant_failures": ("int", False),
        "checks": ("list[CheckView]", False),
        "redacted": ("bool", False),
    },
    "GateVerdict": {
        "run_id": ("str", True),
        "exit_code": ("int", True),
        "failures": ("list[str]", False),
        "quarantined": ("list[str]", False),
        "report_md": ("str", False),
        "baseline_run_id": ("str | None", False),
        "redacted": ("bool", False),
    },
    "ReplayView": {
        "status": ("ReplayStatus", True),
        "reproduced": ("bool | None", False),
        "trials": ("int | None", False),
        "pass_k": ("float | None", False),
        "pass_at_k": ("float | None", False),
        "expected_trials": ("int | None", False),
        "checks": ("list[CheckView]", False),
        "reason": ("str", False),
    },
    "FindingRow": _FINDING_ROW,
    "FindingDetail": {
        **_FINDING_ROW,
        "probe_yaml": ("str", False),
        "provenance": ("dict[str, str]", False),
        "checks": ("list[CheckView]", False),
        "turns": ("list[TranscriptTurn]", False),
        "replay": ("ReplayView | None", False),
    },
    "DiscoveryListPage": {
        "items": ("list[FindingRow]", False),
        "next_cursor": ("str | None", False),
    },
    "CategoryTally": {
        "wins_a": ("int", False),
        "wins_b": ("int", False),
        "ties": ("int", False),
        "unsure": ("int", False),
        "flips": ("int", False),
        "criteria_judged": ("int", False),
        "flip_rate": ("float", False),
    },
    "HardMetrics": {
        "latency_mean_a": ("float | None", False),
        "latency_mean_b": ("float | None", False),
        "latency_p95_a": ("float | None", False),
        "latency_p95_b": ("float | None", False),
        "invariant_failures_a": ("int", False),
        "invariant_failures_b": ("int", False),
        "trials_a": ("int", False),
        "trials_b": ("int", False),
    },
    "Scoreboard": {
        "run_id": ("str", True),
        "pack_name": ("str | None", False),
        "created_at": ("str", True),
        "label_a": ("str", True),
        "label_b": ("str", True),
        "source_a": ("str | None", False),
        "source_b": ("str | None", False),
        "created_at_a": ("str | None", False),
        "created_at_b": ("str | None", False),
        "categories": ("dict[str, CategoryTally]", False),
        "hard_metrics": ("dict[str, HardMetrics]", False),
        "excluded_pairs": ("int", False),
        "judge_usd": ("float | None", False),
        "rubric_scores_untrusted": ("bool", False),
        "redacted": ("bool", False),
    },
    "TrendPoint": {
        "run_id": ("str", True),
        "created_at": ("str", True),
        "value": ("float", True),
    },
    "TrendSeries": {
        "pack_name": ("str", True),
        "probe_id": ("str", True),
        "metric": ("TrendMetric", True),
        "points": ("list[TrendPoint]", False),
    },
    "CriterionCounts": {"hits": ("int", True), "total": ("int", True)},
    "TrustReport": {
        "pack_name": ("str", True),
        "judge_model": ("str | None", False),
        "agreement": ("float | None", False),
        "per_rubric_agreement": ("dict[str, float]", False),
        "per_criterion_agreement": ("dict[str, float]", False),
        "per_criterion_counts": ("dict[str, CriterionCounts]", False),
        "unmatched": ("list[str]", False),
        "stale": ("bool", False),
        "stale_reason": ("str | None", False),
        "calibrated_at": ("str | None", False),
        "threshold": ("float | None", False),
    },
    "PackRow": {
        "id": ("str", True),
        "name": ("str", True),
        "path": ("str", True),
        "version": ("str | None", False),
        "probe_count": ("int", False),
        "has_calibration": ("bool", False),
    },
    "PackListPage": {
        "items": ("list[PackRow]", False),
        "next_cursor": ("str | None", False),
    },
    "ValidationReport": {
        "pack_id": ("str", True),
        "ok": ("bool", True),
        "errors": ("list[str]", False),
        "warnings": ("list[str]", False),
    },
    "PackAxes": {
        "pack_id": ("str", True),
        "objectives": ("list[str]", False),
        "personas": ("list[str]", False),
        "playbooks": ("list[str]", False),
        # Not `float | None` — `TargetSpec.budget.max_usd_per_run` is a plain
        # float with a default, and `0` (not null) is how it is disabled.
        "max_usd_per_run": ("float", False),
    },
    "LaunchRequest": {
        "mode": ("RunMode", True),
        "pack_id": ("str", True),
        "confirm": ("str", True),
        "baseline_run_id": ("str | None", False),
        "run_id_a": ("str | None", False),
        "run_id_b": ("str | None", False),
        "max_usd": ("float | None", False),
        "objectives": ("list[str]", False),
        "allow_uncalibrated": ("bool", False),
    },
    "LaunchResponse": {"run_id": ("str", True)},
    "ControlRequest": {"action": ("ControlAction", True)},
    "ControlResponse": {"run_id": ("str", True), "accepted": ("bool", True)},
    "RedactionMeta": {
        "enabled": ("bool", False),
        "marker": ("str", False),
        "reveal_required": ("bool", False),
    },
    "MetaResponse": {
        "version": ("str", True),
        "runs_dir": ("str", True),
        "packs": ("list[str]", False),
        "allow_discover": ("bool", False),
        "redaction": ("RedactionMeta", False),
        "heartbeat_seconds": ("float", False),
    },
    "HealthResponse": {"ok": ("bool", False), "version": ("str", True)},
}

#: R4-15's "skip non-model exports **explicitly**". Listing them by hand is the
#: point: a new export lands in neither set and the classification test reds,
#: so nobody can add a model and quietly leave it unpinned.
NON_MODEL_EXPORTS = {
    "RUN_ID_PATTERN", "RUN_ID_RE", "RunId", "is_run_id",
    "REDACTION_MARKER_RE", "redaction_marker", "HEARTBEAT_SECONDS",
    "CURSOR_SEPARATOR", "make_cursor", "parse_cursor", "display_path",
    "RunMode", "RunStatus", "ErrorCode", "VerdictTier", "VerdictHint",
    "ControlAction", "ReplayStatus", "TurnRole", "TrendMetric", "EventName",
}


def test_every_export_is_classified_as_a_model_or_not():
    """R4-15: coverage grows with the module instead of rotting."""
    exported_models = {c.__name__ for c in _all_models()}
    assert not exported_models & NON_MODEL_EXPORTS
    assert exported_models | NON_MODEL_EXPORTS == set(m.__all__), (
        "a new export must be pinned in EXPECTED_STRUCTURE or declared in "
        "NON_MODEL_EXPORTS — leaving it unclassified is what I4 caught")


def test_the_structural_pin_covers_every_exported_model():
    """The list is derived, never hand-maintained — this is what makes it so."""
    assert set(EXPECTED_STRUCTURE) == {c.__name__ for c in _all_models()}


@pytest.mark.parametrize("name", sorted(EXPECTED_STRUCTURE))
def test_model_structure_is_frozen(name):
    """Rename, retype, add, drop or make-optional any field and this reds."""
    assert _structure(getattr(m, name)) == EXPECTED_STRUCTURE[name]


def test_the_detail_models_stay_supersets_of_their_rows():
    """Not an accident of the dict above — the SPA renders the detail page
    from a warm list-cache entry, which requires the row's shape to survive."""
    detail = _structure(m.RunDetail)
    assert all(detail[k] == v for k, v in _structure(m.RunSummary).items())
    finding = _structure(m.FindingDetail)
    assert all(finding[k] == v for k, v in _structure(m.FindingRow).items())


# --------------------------------------------------------------------------
# and the one thing `(annotation, is_required)` cannot see: `RunId` erases to
# `str`, so the pin above would not notice a path parameter losing its grammar
# --------------------------------------------------------------------------

#: `{model: {fields typed RunId or RunId | None}}`. Widening one of these to a
#: bare `str` reopens the traversal hole the grammar closes by construction.
RUN_ID_TYPED_FIELDS = {
    "RunSummary": {"run_id"},
    "RunDetail": {"run_id"},
    "GateVerdict": {"run_id"},
    "TrialView": {"run_id"},
    "Scoreboard": {"run_id"},
    "TrendPoint": {"run_id"},
    "FindingRow": {"run_id"},
    "FindingDetail": {"run_id"},
    "LaunchRequest": {"baseline_run_id", "run_id_a", "run_id_b"},
    "LaunchResponse": {"run_id"},
    "ControlResponse": {"run_id"},
}


def _carries_run_id_grammar(fragment) -> bool:
    if isinstance(fragment, dict):
        if fragment.get("pattern") == m.RUN_ID_PATTERN:
            return True
        return any(_carries_run_id_grammar(v) for v in fragment.values())
    if isinstance(fragment, list):
        return any(_carries_run_id_grammar(v) for v in fragment)
    return False


@pytest.mark.parametrize("name", sorted(EXPECTED_STRUCTURE))
def test_exactly_the_declared_fields_are_typed_with_the_run_id_grammar(name):
    schema = getattr(m, name).model_json_schema()
    typed = {field for field, frag in schema.get("properties", {}).items()
             if _carries_run_id_grammar(frag)}
    assert typed == RUN_ID_TYPED_FIELDS.get(name, set())


def test_ui_package_init_is_docstring_only():
    """`import evalyn.ui` must stay free of fastapi/uvicorn — the CLI touches it."""
    import ast

    import evalyn.ui
    tree = ast.parse(pathlib.Path(evalyn.ui.__file__).read_text())
    assert all(isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
               for node in tree.body), ast.dump(tree)
