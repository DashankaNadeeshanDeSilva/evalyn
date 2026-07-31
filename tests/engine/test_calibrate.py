from __future__ import annotations

import asyncio
import json

import pytest

from evalyn.engine.calibrate import (
    AGREEMENT_THRESHOLD,
    Anchor,
    is_stale,
    load_anchors,
    load_record,
    run_calibration,
    write_record,
)
from evalyn.scoring.rubrics import _hash_text
from evalyn.scoring.tier3 import RubricScore
from evalyn.targets.loader import Pack, PackError
from evalyn.targets.schema import Check, Probe, TargetSpec

PERSONA = """# Persona

## voice
First person, in character.

## warmth
Friendly, never dismissive.
"""

TONE = "# Tone\nCalm and professional.\n"


def _pack(tmp_path, *, rubric_check: str | None = None) -> Pack:
    (tmp_path / "rubrics").mkdir(exist_ok=True)
    (tmp_path / "rubrics" / "persona.md").write_text(PERSONA)
    (tmp_path / "rubrics" / "tone.md").write_text(TONE)
    probes = []
    if rubric_check is not None:
        probes = [Probe(id="p1", category="c", turns=["hi"],
                        checks=[Check(type="rubric", rubric=rubric_check, required=True)])]
    spec = TargetSpec(name="t", sessions={}, allowlist=[])
    return Pack(spec=spec, probes=probes, root=tmp_path)


def _anchor_yaml(tmp_path, name: str, *, rubric: str = "persona",
                 transcript: str = "User: hi\nAssistant: hello",
                 scores: dict | None = None, body: str | None = None) -> None:
    d = tmp_path / "anchors"
    d.mkdir(exist_ok=True)
    if body is not None:
        (d / f"{name}.yaml").write_text(body)
        return
    lines = [f"rubric: {rubric}", "transcript: |"]
    lines += [f"  {ln}" for ln in transcript.splitlines()]
    lines.append("scores:")
    lines += [f"  {k}: {v}" for k, v in (scores or {}).items()]
    (d / f"{name}.yaml").write_text("\n".join(lines) + "\n")


def _rubric_score(medians: dict[str, int] | None, *, unsure: bool = False,
                  reason: str | None = None,
                  criterion_medians: dict[str, int] | None = None,
                  criterion_spreads: dict[str, int] | None = None) -> RubricScore:
    # mirrors production: a clean result's criterion_medians == medians; an
    # unsure result carries only explicitly-provided per-criterion data
    if criterion_medians is None:
        criterion_medians = dict(medians) if medians else {}
    return RubricScore(medians=medians, samples=[], steps=["s"],
                       rubric_hash="h", unsure=unsure,
                       reason=(reason if reason is not None
                               else ("stubbed disagreement" if unsure else "")),
                       criterion_medians=criterion_medians,
                       criterion_spreads=criterion_spreads or {})


def _stub_scores(monkeypatch, by_anchor_transcript: dict[str, RubricScore]):
    """Stub the tier3 score_transcript seam: no live model calls (note 4)."""
    from evalyn.engine import calibrate as cal
    calls = []

    async def fake(rubric_text, rubric_hash, transcript, judge_model, k=3,
                   cache_dir=None, context=None, steps=None):
        calls.append(transcript.strip())
        return by_anchor_transcript[transcript.strip()]

    monkeypatch.setattr(cal, "score_transcript", fake)
    return calls


def _stub_steps(monkeypatch):
    """Stub grading_steps in the calibrate module; count calls."""
    from evalyn.engine import calibrate as cal
    calls = {"n": 0}

    async def fake(rubric_text, rubric_hash, judge_model, cache_dir):
        calls["n"] += 1
        return ["step"]

    monkeypatch.setattr(cal, "grading_steps", fake)
    return calls


# ----------------------------------------------- frozen steps (2026-07-31)


async def test_run_calibration_uses_frozen_steps_without_generation(
        monkeypatch, tmp_path):
    # a committed rubrics/<rid>.steps.json disables the pre-warm generation
    # call for that rubric and is handed to score_transcript verbatim
    pack = _pack(tmp_path)
    (tmp_path / "rubrics" / "persona.steps.json").write_text(
        '["frozen persona step"]')
    _anchor_yaml(tmp_path, "a1", transcript="T1",
                 scores={"voice": 4, "warmth": 4})
    steps_calls = _stub_steps(monkeypatch)
    from evalyn.engine import calibrate as cal
    seen_steps = []

    async def fake(rubric_text, rubric_hash, transcript, judge_model, k=3,
                   cache_dir=None, context=None, steps=None):
        seen_steps.append(steps)
        return _rubric_score({"voice": 4, "warmth": 4})

    monkeypatch.setattr(cal, "score_transcript", fake)
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert steps_calls["n"] == 0                    # no generation pre-warm
    assert seen_steps == [["frozen persona step"]]  # frozen steps passed through
    assert result.overall == 1.0


async def test_run_calibration_still_generates_steps_without_frozen_file(
        monkeypatch, tmp_path):
    # no steps file -> the pre-warm generation path runs exactly as before
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1",
                 scores={"voice": 4, "warmth": 4})
    steps_calls = _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {"T1": _rubric_score({"voice": 4, "warmth": 4})})
    await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert steps_calls["n"] == 1


# ------------------------------------------------------------- load_anchors


def test_load_anchors_non_dict_scores_is_packerror(tmp_path):
    # `scores: high` (a scalar) must be a clear PackError, not a raw
    # ValueError/TypeError from dict()
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "bad",
                 body="rubric: persona\ntranscript: t\nscores: high\n")
    with pytest.raises(PackError, match=r"scores.*mapping"):
        load_anchors(pack)


def test_load_anchors_missing_key_message_does_not_demand_scores(tmp_path):
    # only `rubric` and `transcript` are required; a missing `scores` block is
    # handled downstream as a skipped anchor — the error must not claim otherwise
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "norubric", body="transcript: t\n")
    with pytest.raises(PackError, match=r"need `rubric` and `transcript`") as ei:
        load_anchors(pack)
    assert "scores" not in str(ei.value)


def test_load_anchors_missing_scores_key_is_loaded_not_error(tmp_path):
    # no `scores` at all -> anchor loads with {} labels (skipped later, not fatal)
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "nolabels", body="rubric: persona\ntranscript: t\n")
    [a] = load_anchors(pack)
    assert a.scores == {}


async def test_run_calibration_reports_unmatched_criterion_labels(monkeypatch, tmp_path):
    # reviewer Important: a human label whose criterion name matches no rubric
    # heading must be REPORTED, never silently dropped from the denominator
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1",
                 scores={"voice": 4, "Warmth": 4})  # "Warmth" typo vs heading "warmth"
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {"T1": _rubric_score({"voice": 4, "warmth": 4})})
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.unmatched == {"a1": ["Warmth"]}
    # the matched pair is still scored on unchanged math
    assert result.per_criterion == {"persona:voice": 1.0}
    assert result.overall == 1.0 and result.anchors == 1


async def test_run_calibration_reports_unmatched_labels_on_unsure_anchor(monkeypatch, tmp_path):
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "ghost": 2})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {"T1": _rubric_score(None, unsure=True)})
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.unmatched == {"a1": ["ghost"]}
    assert result.unsure == ["a1"]
    assert result.overall == 0.0  # matched "voice" pair counted as a fail-closed miss


# --------------------------------------------------------------- load_anchors


def test_load_anchors_reads_yaml_with_id_defaulting_to_stem(tmp_path):
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", scores={"voice": 4, "warmth": 5})
    _anchor_yaml(tmp_path, "zz", body=(
        "id: explicit\nrubric: tone\ntranscript: 'User: hi'\nscores:\n  Tone: 2\n"))
    anchors = load_anchors(pack)
    assert [a.id for a in anchors] == ["a1", "explicit"]
    a1 = anchors[0]
    assert a1.rubric == "persona"
    assert a1.scores == {"voice": 4, "warmth": 5}
    assert "Assistant: hello" in a1.transcript


def test_load_anchors_missing_dir_returns_empty(tmp_path):
    assert load_anchors(_pack(tmp_path)) == []


def test_load_anchors_missing_required_key_raises_packerror(tmp_path):
    # Task 12: malformed anchors surface as PackError (clean CLI exit 2),
    # never a raw KeyError
    from evalyn.targets.loader import PackError

    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "bad", body="scores:\n  Tone: 4\n")
    with pytest.raises(PackError, match="bad.yaml.*'rubric'"):
        load_anchors(pack)


# ------------------------------------------------------------ run_calibration


async def test_run_calibration_per_criterion_and_overall(monkeypatch, tmp_path):
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "warmth": 5})
    _anchor_yaml(tmp_path, "a2", transcript="T2", scores={"voice": 1, "warmth": 3})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {
        "T1": _rubric_score({"voice": 4, "warmth": 4}),   # both within +/-1
        "T2": _rubric_score({"voice": 4, "warmth": 3}),   # voice off by 3
    })
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.overall == 0.75
    assert result.per_criterion == {"persona:voice": 0.5, "persona:warmth": 1.0}
    assert result.anchors == 2
    assert result.skipped == [] and result.unsure == []


# ---------- per-criterion unsure accounting (2026-07-31, run #4 remediation)
# RETIRED SEAM: anchor-wide voiding (one torn criterion counted EVERY
# criterion of the anchor as a miss). Now only a criterion WITHOUT a clean
# k-draw median is the fail-closed miss; a sibling with a clean median is
# compared normally. Denominators never shrink: torn pairs stay counted.


async def test_run_calibration_torn_criterion_missed_clean_sibling_counted(
        monkeypatch, tmp_path):
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "warmth": 4})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {"T1": _rubric_score(
        None, unsure=True,
        reason="judge disagreement (spread >= 2) on ['warmth']",
        criterion_medians={"voice": 4},
        criterion_spreads={"voice": 0, "warmth": 3})})
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    # clean sibling compared normally (hit); torn criterion fail-closed miss
    assert result.per_criterion == {"persona:voice": 1.0, "persona:warmth": 0.0}
    # denominator preserved: the torn pair stays IN the totals
    assert result.per_criterion_counts == {"persona:voice": (1, 1),
                                           "persona:warmth": (0, 1)}
    assert result.overall == 0.5
    assert result.unsure == ["a1"]  # the anchor is still reported judge-unsure
    assert result.per_anchor["a1"]["criteria"]["voice"] == {
        "judge": 4, "human": 4, "within": True}
    assert result.per_anchor["a1"]["criteria"]["warmth"] == {
        "judge": None, "human": 4, "within": False,
        "unsure_reason": "spread 3 >= 2"}


async def test_run_calibration_clean_sibling_of_torn_criterion_can_still_miss(
        monkeypatch, tmp_path):
    # counting the clean sibling normally is not a free hit: judge 1 vs
    # human 4 is a genuine miss
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "warmth": 4})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {"T1": _rubric_score(
        None, unsure=True,
        criterion_medians={"voice": 1},
        criterion_spreads={"voice": 1, "warmth": 2})})
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.per_criterion == {"persona:voice": 0.0, "persona:warmth": 0.0}
    assert result.per_anchor["a1"]["criteria"]["voice"] == {
        "judge": 1, "human": 4, "within": False}


async def test_run_calibration_all_criteria_torn_all_miss(monkeypatch, tmp_path):
    # spread >= 2 on BOTH criteria: both stay fail-closed misses (a torn
    # criterion is never a hit and never leaves the denominator)
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "warmth": 4})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {"T1": _rubric_score(
        None, unsure=True,
        criterion_medians={},
        criterion_spreads={"voice": 2, "warmth": 4})})
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.overall == 0.0
    assert result.per_criterion_counts == {"persona:voice": (0, 1),
                                           "persona:warmth": (0, 1)}
    assert result.per_anchor["a1"]["criteria"]["voice"]["unsure_reason"] == \
        "spread 2 >= 2"
    assert result.per_anchor["a1"]["criteria"]["warmth"]["unsure_reason"] == \
        "spread 4 >= 2"


async def test_run_calibration_unsure_judge_counts_as_disagreement(monkeypatch, tmp_path):
    # fail-closed: an unsure anchor with NO clean per-criterion medians (e.g.
    # unparseable draws) misses every pair, never dropped
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "warmth": 4})
    _anchor_yaml(tmp_path, "a2", transcript="T2", scores={"voice": 4, "warmth": 4})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {
        "T1": _rubric_score({"voice": 4, "warmth": 4}),
        "T2": _rubric_score(None, unsure=True),
    })
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.overall == 0.5
    assert result.unsure == ["a2"]


async def test_run_calibration_skips_anchors_without_human_scores(monkeypatch, tmp_path):
    # human labels only (note 3): blank/missing scores are skipped and reported,
    # never invented
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "good", transcript="T1", scores={"voice": 4, "warmth": 4})
    _anchor_yaml(tmp_path, "blank", body="rubric: persona\ntranscript: 'User: hi'\n")
    _anchor_yaml(tmp_path, "nonint", body=(
        "rubric: persona\ntranscript: 'User: hi'\nscores:\n  voice:\n"))
    _stub_steps(monkeypatch)
    calls = _stub_scores(monkeypatch, {"T1": _rubric_score({"voice": 4, "warmth": 4})})
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.skipped == ["blank", "nonint"]
    assert result.anchors == 1 and result.overall == 1.0
    assert calls == ["T1"]  # skipped anchors are never scored


async def test_run_calibration_prewarms_steps_cache_once_per_rubric(monkeypatch, tmp_path):
    # note 5: pre-warm the grading-steps cache once per rubric before concurrent
    # scoring so first-time samples cannot race to divergent steps
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "warmth": 4})
    _anchor_yaml(tmp_path, "a2", transcript="T2", scores={"voice": 4, "warmth": 4})
    _anchor_yaml(tmp_path, "a3", body=(
        "rubric: tone\ntranscript: T3\nscores:\n  Tone: 4\n"))
    steps_calls = _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {
        "T1": _rubric_score({"voice": 4, "warmth": 4}),
        "T2": _rubric_score({"voice": 4, "warmth": 4}),
        "T3": _rubric_score({"Tone": 4}),
    })
    await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert steps_calls["n"] == 2  # once per distinct rubric, not per anchor


def _stub_scores_tracking_in_flight(monkeypatch):
    """Stub score_transcript with an in-flight counter (deterministic: only
    event-loop yields via sleep(0), no wall-clock timing)."""
    from evalyn.engine import calibrate as cal
    state = {"in_flight": 0, "max_in_flight": 0}

    async def fake(rubric_text, rubric_hash, transcript, judge_model, k=3,
                   cache_dir=None, context=None, steps=None):
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        # Yield twice so every unbounded sibling coroutine would enter before
        # this one exits — an unbounded gather makes max_in_flight == n anchors.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        state["in_flight"] -= 1
        return _rubric_score({"voice": 4})

    monkeypatch.setattr(cal, "score_transcript", fake)
    return state


async def test_run_calibration_honors_max_concurrency_cap(monkeypatch, tmp_path):
    pack = _pack(tmp_path)
    for i in range(8):
        _anchor_yaml(tmp_path, f"a{i}", transcript=f"T{i}", scores={"voice": 4})
    _stub_steps(monkeypatch)
    state = _stub_scores_tracking_in_flight(monkeypatch)
    result = await run_calibration(pack, "mockllm/model", cache_dir=None,
                                   max_concurrency=2)
    assert result.anchors == 8 and result.overall == 1.0  # behavior unchanged
    assert 1 <= state["max_in_flight"] <= 2  # never more than the cap in flight


async def test_run_calibration_default_cap_is_four(monkeypatch, tmp_path):
    pack = _pack(tmp_path)
    for i in range(8):
        _anchor_yaml(tmp_path, f"a{i}", transcript=f"T{i}", scores={"voice": 4})
    _stub_steps(monkeypatch)
    state = _stub_scores_tracking_in_flight(monkeypatch)
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.anchors == 8
    assert 1 <= state["max_in_flight"] <= 4  # unbounded would reach 8


async def test_run_calibration_rejects_nonpositive_max_concurrency(monkeypatch, tmp_path):
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {"T1": _rubric_score({"voice": 4})})
    for bad in (0, -1):
        with pytest.raises(ValueError, match="max_concurrency"):
            await run_calibration(pack, "mockllm/model", cache_dir=None,
                                  max_concurrency=bad)


async def test_run_calibration_threads_facts_context_to_judge(monkeypatch, tmp_path):
    # Plan #2b Task 2: run_calibration passes each rubric's fact sheet (or
    # None) into score_transcript, mirroring the gate's tier3_scorer
    pack = _pack(tmp_path)
    (tmp_path / "rubrics" / "persona.facts.md").write_text("FACT: nine years of Python")
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "warmth": 4})
    _anchor_yaml(tmp_path, "a2", rubric="tone", transcript="T2", scores={"Tone": 4})
    _stub_steps(monkeypatch)
    from evalyn.engine import calibrate as cal
    seen: dict[str, str | None] = {}

    async def fake(rubric_text, rubric_hash, transcript, judge_model, k=3,
                   cache_dir=None, context=None, steps=None):
        seen[transcript.strip()] = context
        return _rubric_score({"voice": 4, "warmth": 4} if "voice" in rubric_text
                             else {"Tone": 4})

    monkeypatch.setattr(cal, "score_transcript", fake)
    await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert seen["T1"] == "FACT: nine years of Python"  # persona has a facts sheet
    assert seen["T2"] is None                          # tone has none


async def test_run_calibration_reports_per_anchor_detail(monkeypatch, tmp_path):
    # 2026-07-30 calibrate failure: nothing persisted or printed could say
    # WHICH anchors disagreed or why an anchor was unsure — the result must
    # carry judge-vs-human per matched criterion plus the unsure reason
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "warmth": 5})
    _anchor_yaml(tmp_path, "a2", transcript="T2", scores={"voice": 4})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {
        "T1": _rubric_score({"voice": 4, "warmth": 3}),   # voice hit, warmth miss
        "T2": _rubric_score(None, unsure=True),
    })
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.per_anchor["a1"] == {
        "rubric": "persona", "unsure_reason": None,
        "criteria": {"voice": {"judge": 4, "human": 4, "within": True},
                     "warmth": {"judge": 3, "human": 5, "within": False}}}
    assert result.per_anchor["a2"] == {
        "rubric": "persona", "unsure_reason": "stubbed disagreement",
        "criteria": {"voice": {"judge": None, "human": 4, "within": False}}}


async def test_run_calibration_per_anchor_excludes_unmatched_labels(monkeypatch, tmp_path):
    # per-anchor detail covers only pairs in the agreement denominator; labels
    # matching no rubric criterion stay in `unmatched`, not `per_anchor`
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "ghost": 2})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {"T1": _rubric_score({"voice": 4, "warmth": 4})})
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.per_anchor["a1"]["criteria"] == {
        "voice": {"judge": 4, "human": 4, "within": True}}


async def test_run_calibration_no_usable_anchors(monkeypatch, tmp_path):
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "blank", body="rubric: persona\ntranscript: 'User: hi'\n")
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {})
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.anchors == 0 and result.overall == 0.0
    assert result.skipped == ["blank"]


# --------------------------------------------------------- record read/write


def test_write_record_and_load_record_roundtrip(tmp_path):
    pack = _pack(tmp_path, rubric_check="tone")
    _anchor_yaml(tmp_path, "a1", scores={"voice": 4, "warmth": 4})
    path = write_record(pack, 0.9, {"persona:voice": 0.9}, "anthropic/claude-x")
    assert path == tmp_path / "calibration.json"
    rec = load_record(pack)
    assert rec is not None
    assert rec["judge_model"] == "anthropic/claude-x"
    assert rec["agreement"] == 0.9
    assert rec["per_criterion"] == {"persona:voice": 0.9}
    # PR #4 fix #3: hashes cover ONLY rubrics with scored anchor pairs (the
    # per_criterion keys) — never pack rubrics that were never calibrated
    # ("tone" here has a pack rubric check AND an anchors dir, but no scored
    # pairs, so blessing its hash would let is_stale call it covered)
    assert rec["rubric_hashes"] == {"persona": _hash_text(PERSONA)}
    assert "created_at" in rec
    json.loads(path.read_text())  # committed record is plain JSON


def test_load_record_missing_returns_none(tmp_path):
    assert load_record(_pack(tmp_path)) is None


# ------------------------------------------------------------------- is_stale


def test_is_stale_missing_record(tmp_path):
    pack = _pack(tmp_path, rubric_check="tone")
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale and "no calibration record" in why


def test_is_stale_judge_model_change(tmp_path):
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, 0.9, {}, "anthropic/claude-x")
    stale, why = is_stale(pack, "anthropic/claude-y")
    assert stale and "judge model" in why


def test_is_stale_rubric_hash_change(tmp_path):
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, 0.9, {"tone:Calm": 0.9}, "anthropic/claude-x")
    (tmp_path / "rubrics" / "tone.md").write_text("# Tone\nEdited since calibration.\n")
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale and "tone" in why and "changed" in why


def test_is_stale_when_facts_sheet_edited_after_calibration(tmp_path):
    # Plan #2b Task 2: load_rubric's hash covers a sibling `<rid>.facts.md`,
    # so a facts edit stales the record with ZERO changes to this module's
    # staleness logic
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, 0.9, {"tone:Calm": 0.9}, "anthropic/claude-x")
    stale, _ = is_stale(pack, "anthropic/claude-x")
    assert stale is False
    (tmp_path / "rubrics" / "tone.facts.md").write_text("FACT: added after calibration")
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale and "tone" in why and "changed" in why


def test_is_stale_rubric_without_anchor_coverage(tmp_path):
    # locked staleness rule + PR #4 fix #3: a pack rubric check whose rubric
    # was never scored against anchors is stale ("no anchor coverage"), not
    # silently trusted — even when anchors exist for OTHER rubrics
    pack = _pack(tmp_path, rubric_check="tone")
    _anchor_yaml(tmp_path, "a1", scores={"voice": 4})  # anchors only cover persona
    write_record(pack, 0.9, {"persona:voice": 0.9}, "anthropic/claude-x")
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale and "tone" in why and "no anchor coverage" in why


def test_is_stale_rubric_file_missing(tmp_path):
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, 0.9, {"tone:Calm": 0.9}, "anthropic/claude-x")
    (tmp_path / "rubrics" / "tone.md").unlink()
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale and "tone" in why and "missing" in why


def test_is_stale_agreement_below_threshold(tmp_path):
    # note 1 pin: a failing calibrate run's record must NEVER be accepted by
    # the gate — sub-threshold agreement is stale/invalid
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, AGREEMENT_THRESHOLD - 0.01, {"tone:Calm": 0.9},
                 "anthropic/claude-x")
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale and "agreement" in why


def test_is_stale_agreement_exactly_at_threshold_is_not_stale(tmp_path):
    # boundary lock: >= threshold passes calibrate AND satisfies is_stale
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, AGREEMENT_THRESHOLD, {"tone:Calm": AGREEMENT_THRESHOLD},
                 "anthropic/claude-x")
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale is False and why == "calibrated"


def test_is_stale_fresh_record_is_not_stale(tmp_path):
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, 0.9, {"tone:Calm": 0.9}, "anthropic/claude-x")
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale is False and why == "calibrated"


# ------------------------------------- PR #4 fix #4: PER-RUBRIC fail-closed


def test_is_stale_flags_weak_rubric_despite_strong_overall(tmp_path):
    # user ruling: a strong OVERALL mean must not hide a weak rubric — each
    # pack rubric's own agreement (mean of its per-criterion values) gates too
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, 0.95, {"tone:Calm": 0.8, "tone:Firm": 0.8},
                 "anthropic/claude-x")
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale
    assert "tone" in why and "80%" in why  # names the weak rubric and its value


def test_per_rubric_agreement_pools_each_rubrics_criteria():
    from evalyn.engine.calibrate import per_rubric_agreement

    assert per_rubric_agreement(
        {"a:x": 1.0, "a:y": 0.5, "b:z": 0.9}) == {"a": 0.75, "b": 0.9}
    assert per_rubric_agreement({}) == {}


# -------------- round-2 N8: pooled per-rubric agreement from raw counts


async def test_run_calibration_captures_per_criterion_counts(monkeypatch, tmp_path):
    # divergent pair counts: a1 labels both criteria, a2 labels voice only
    pack = _pack(tmp_path)
    _anchor_yaml(tmp_path, "a1", transcript="T1", scores={"voice": 4, "warmth": 5})
    _anchor_yaml(tmp_path, "a2", transcript="T2", scores={"voice": 1})
    _stub_steps(monkeypatch)
    _stub_scores(monkeypatch, {
        "T1": _rubric_score({"voice": 4, "warmth": 4}),   # both within +/-1
        "T2": _rubric_score({"voice": 4, "warmth": 3}),   # voice off by 3
    })
    result = await run_calibration(pack, "mockllm/model", cache_dir=None)
    assert result.per_criterion_counts == {
        "persona:voice": (1, 2), "persona:warmth": (1, 1)}


def test_pooled_rubric_agreement_pools_counts_not_fractions():
    from evalyn.engine.calibrate import pooled_rubric_agreement

    # mean-of-fractions would say (0.5 + 1.0)/2 = 0.75; pooling the raw pairs
    # gives 2/3 — the unenforced equal-pair-count precondition erred fail-OPEN
    counts = {"persona:voice": (1, 2), "persona:warmth": (1, 1)}
    assert pooled_rubric_agreement(counts) == {"persona": 2 / 3}
    assert pooled_rubric_agreement({}) == {}


def test_write_record_with_counts_stores_pooled_per_rubric_agreement(tmp_path):
    pack = _pack(tmp_path)
    write_record(pack, 0.9, {"persona:voice": 1.0, "persona:warmth": 0.8},
                 "anthropic/claude-x",
                 per_criterion_counts={"persona:voice": (1, 1),
                                       "persona:warmth": (8, 10)})
    rec = load_record(pack)
    # additive, backward-compatible fields only
    assert rec["per_rubric_agreement"] == {"persona": 9 / 11}
    assert rec["per_criterion_counts"] == {"persona:voice": [1, 1],
                                           "persona:warmth": [8, 10]}
    assert rec["per_criterion"] == {"persona:voice": 1.0, "persona:warmth": 0.8}


def test_is_stale_prefers_recorded_pooled_agreement(tmp_path):
    # divergent counts: mean-of-fractions (1.0 + 0.8)/2 = 0.9 clears 85%, but
    # the pooled truth 9/11 = 81.8% does not — the record must be STALE
    pack = _pack(tmp_path, rubric_check="persona")
    write_record(pack, 0.9, {"persona:voice": 1.0, "persona:warmth": 0.8},
                 "anthropic/claude-x",
                 per_criterion_counts={"persona:voice": (1, 1),
                                       "persona:warmth": (8, 10)})
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale is True
    assert "persona" in why and "82%" in why


def test_is_stale_falls_back_to_mean_of_fractions_for_old_records(tmp_path):
    # pre-N8 records (e.g. the committed packs/twincore/calibration.json) have
    # no pooled field — is_stale must still evaluate them via per_criterion
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, 0.9, {"tone:Calm": 0.9}, "anthropic/claude-x")
    rec = load_record(pack)
    assert "per_rubric_agreement" not in rec  # old-format shape preserved
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale is False and why == "calibrated"


def test_is_stale_per_rubric_check_ignores_non_pack_rubrics(tmp_path):
    # a weak rubric that NO pack probe references must not stale the record
    pack = _pack(tmp_path, rubric_check="tone")
    write_record(pack, 0.9, {"tone:Calm": 0.9, "persona:voice": 0.2},
                 "anthropic/claude-x")
    stale, why = is_stale(pack, "anthropic/claude-x")
    assert stale is False and why == "calibrated"


def test_anchor_dataclass_fields():
    a = Anchor(id="a", rubric="persona", transcript="t", scores={"voice": 3})
    assert (a.id, a.rubric, a.transcript, a.scores) == ("a", "persona", "t", {"voice": 3})
