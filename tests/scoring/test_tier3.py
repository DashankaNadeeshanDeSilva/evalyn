import json

from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, Target
from inspect_ai.solver import TaskState

from evalyn.scoring.rubrics import _hash_text
from evalyn.scoring.tier3 import (
    _median,
    _normalize_score,
    _parse,
    _spread,
    score_transcript,
    tier3_scorer,
)
from evalyn.targets.loader import Pack
from evalyn.targets.schema import TargetSpec

PERSONA = """# Persona

## voice
First person, in character.

## warmth
Friendly, never dismissive.
"""

TONE = "# Tone\nCalm and professional.\n"


def _pack(tmp_path):
    (tmp_path / "rubrics").mkdir(exist_ok=True)
    (tmp_path / "rubrics" / "persona.md").write_text(PERSONA)
    (tmp_path / "rubrics" / "tone.md").write_text(TONE)
    spec = TargetSpec(name="t", sessions={}, allowlist=[])
    return Pack(spec=spec, probes=[], root=tmp_path)


def _state(reply, checks):
    st = TaskState(model="m", sample_id="1", epoch=1, input="x", messages=[])
    st.output = ModelOutput.from_content("evalyn-target", reply)
    st.metadata = {"checks": checks}
    return st


class _FakeJudge:
    """Injected fake judge: returns canned completions in order, records prompts."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    async def generate(self, prompt):
        self.prompts.append(prompt)
        return ModelOutput.from_content("mockllm/model", self.outputs.pop(0))


def _stub(monkeypatch, outputs, steps=("step one",)):
    from evalyn.scoring import tier3 as t3
    judge = _FakeJudge(outputs)
    monkeypatch.setattr(t3, "get_model", lambda m: judge)

    async def fake_steps(rubric_text, rubric_hash, judge_model, cache_dir):
        return list(steps)

    monkeypatch.setattr(t3, "grading_steps", fake_steps)
    return judge


def _sample(scores: dict[str, int]) -> str:
    return json.dumps({"scores": {
        k: {"score": v, "justification": "because"} for k, v in scores.items()}})


# --- unit helpers ---------------------------------------------------------


def test_normalize_score_maps_1_5_to_0_1():
    assert _normalize_score(1) == 0.0 and _normalize_score(5) == 1.0 and _normalize_score(3) == 0.5


def test_spread_flags_disagreement():
    assert _spread([1, 3, 5]) == 4 and _median([1, 3, 5]) == 3


def test_median_is_median_low_at_even_k():
    # PR #4 fix #12: deliberate median_low — at even k the tie breaks DOWN to
    # the lower observed score (conservative/fail-closed), never int-truncation
    # of the midpoint mean ([3,5] -> 3, where int(median)=int(4.0) would say 4).
    assert _median([4, 5]) == 4
    assert _median([3, 5]) == 3
    assert _median([2, 4, 4, 5]) == 4


def test_median_odd_k_unchanged_by_median_low():
    # identical to the true median at odd k, so k=3 calibration is unaffected
    assert _median([1, 3, 5]) == 3
    assert _median([4, 4, 5]) == 4


# --- strict per-criterion parsing (P1) ------------------------------------


def test_parse_valid_per_criterion_scores():
    raw = _sample({"voice": 4, "warmth": 5})
    assert _parse(raw, ["voice", "warmth"]) == {"voice": 4, "warmth": 5}


def test_parse_missing_criterion_is_unparseable():
    raw = _sample({"voice": 4})
    assert _parse(raw, ["voice", "warmth"]) is None


def test_parse_non_integer_score_is_unparseable():
    raw = json.dumps({"scores": {"voice": {"score": 4.5, "justification": "j"}}})
    assert _parse(raw, ["voice"]) is None
    raw = json.dumps({"scores": {"voice": {"score": "4", "justification": "j"}}})
    assert _parse(raw, ["voice"]) is None
    raw = json.dumps({"scores": {"voice": {"score": True, "justification": "j"}}})
    assert _parse(raw, ["voice"]) is None


def test_parse_out_of_range_score_is_unparseable():
    assert _parse(_sample({"voice": 0}), ["voice"]) is None
    assert _parse(_sample({"voice": 6}), ["voice"]) is None


def test_parse_non_json_is_unparseable():
    assert _parse("The score is 4 out of 5.", ["voice"]) is None


# --- tolerant fail-closed criterion-key matching (2026-07-30 calibrate fix) --
# Live failure: LLM-generated grading steps renamed the rubric headings
# ("Claim Support", "Specificity") and the judge keyed its JSON by the steps'
# names; exact-key lookup made every such draw unparseable and 9/11 anchors
# UNSURE. Matching is deterministic normalization + unique prefix/superset
# only — zero or ambiguous matches stay uncounted (fail-closed), never fuzzy.

GROUNDED_CRITERIA = ["Claim support", "Specificity without overreach"]


def test_parse_accepts_case_and_whitespace_variant_keys():
    raw = _sample({"Claim Support": 4, " specificity without overreach ": 5})
    assert _parse(raw, GROUNDED_CRITERIA) == {
        "Claim support": 4, "Specificity without overreach": 5}


def test_parse_accepts_unique_prefix_key():
    # the live failure's second renaming: "Specificity" for
    # "Specificity without overreach"
    raw = _sample({"Claim support": 4, "Specificity": 5})
    assert _parse(raw, GROUNDED_CRITERIA) == {
        "Claim support": 4, "Specificity without overreach": 5}


def test_parse_accepts_unique_superset_key():
    # judge key extends the heading; the heading is a unique prefix of it
    raw = _sample({"Claim support and evidence": 4,
                   "Specificity without overreach": 5})
    assert _parse(raw, GROUNDED_CRITERIA) == {
        "Claim support": 4, "Specificity without overreach": 5}


def test_parse_keys_result_by_canonical_criterion_names():
    # downstream (calibrate anchor labels, medians) key on parse_criteria
    # names — a tolerant match must never leak the judge's spelling
    raw = _sample({"SPECIFICITY": 3, "claim support": 2})
    parsed = _parse(raw, GROUNDED_CRITERIA)
    assert parsed is not None and sorted(parsed) == sorted(GROUNDED_CRITERIA)


def test_parse_ambiguous_prefix_key_is_not_counted():
    # "Claim" could be either criterion -> not counted -> "Claim support"
    # unscored -> whole sample unparseable (fail-closed)
    raw = _sample({"Claim": 4, "Claim clarity": 5})
    assert _parse(raw, ["Claim support", "Claim clarity"]) is None


def test_parse_zero_match_key_is_not_counted():
    # a key matching no criterion never scores anything; the criterion stays
    # unscored and the existing unsure path applies
    raw = _sample({"Fluency": 4})
    assert _parse(raw, ["Claim support"]) is None


def test_parse_empty_or_whitespace_key_is_not_counted():
    # "" is trivially a prefix of every criterion — a degenerate key must
    # never score anything, even on a single-criterion rubric
    assert _parse(_sample({"": 4}), ["Claim support"]) is None
    assert _parse(_sample({"   ": 4}), ["Claim support"]) is None


def test_parse_two_keys_resolving_to_same_criterion_is_not_counted():
    # collision: exact + prefix both hit one criterion -> undecidable which
    # score counts -> fail closed
    raw = _sample({"Specificity": 4, "specificity without overreach": 5})
    assert _parse(raw, ["Specificity without overreach"]) is None


async def test_score_transcript_survives_steps_renamed_criteria(monkeypatch):
    # end-to-end pin of the 2026-07-30 failure mode: draws keyed by the steps'
    # renamed criteria must parse, not collapse the anchor to UNSURE
    grounded = ("# Groundedness\n\n## Claim support\nClaims are supported.\n\n"
                "## Specificity without overreach\nSpecific, no overreach.\n")
    outs = [_sample({"Claim Support": 4, "Specificity": 4}),
            _sample({"Claim support": 4, "Specificity without overreach": 4}),
            _sample({"Claim Support": 5, "Specificity": 4})]
    _stub(monkeypatch, outs)
    res = await score_transcript(grounded, _hash_text(grounded),
                                 "User: hi\nAssistant: hello", "mockllm/model")
    assert res.unsure is False
    assert res.medians == {"Claim support": 4,
                           "Specificity without overreach": 4}


# --- score_transcript (reusable for Task 5 calibration) --------------------


async def test_score_transcript_returns_per_criterion_medians(monkeypatch):
    outs = [_sample({"voice": 4, "warmth": 3}),
            _sample({"voice": 4, "warmth": 3}),
            _sample({"voice": 5, "warmth": 3})]
    _stub(monkeypatch, outs)
    res = await score_transcript(PERSONA, _hash_text(PERSONA),
                                 "User: hi\nAssistant: hello", "mockllm/model")
    assert res.unsure is False
    assert res.medians == {"voice": 4, "warmth": 3}
    assert len(res.samples) == 3


async def test_score_transcript_spread_on_any_criterion_is_unsure(monkeypatch):
    outs = [_sample({"voice": 1, "warmth": 4}),
            _sample({"voice": 3, "warmth": 4}),
            _sample({"voice": 5, "warmth": 4})]
    _stub(monkeypatch, outs)
    res = await score_transcript(PERSONA, _hash_text(PERSONA),
                                 "User: hi\nAssistant: hello", "mockllm/model")
    assert res.unsure is True and res.medians is None


FACTS = "The owner has nine years of Python experience."


async def test_score_transcript_injects_context(monkeypatch):
    # the facts text appears under the "Reference fact sheet" heading, between
    # the evaluation steps and the criteria line
    judge = _stub(monkeypatch, [_sample({"Tone": 4})] * 3, steps=("step one",))
    await score_transcript(TONE, _hash_text(TONE), "User: hi\nAssistant: hello",
                           "mockllm/model", context=FACTS)
    assert len(judge.prompts) == 3
    for p in judge.prompts:
        assert "Reference fact sheet" in p and FACTS in p
        assert p.index("- step one") < p.index("Reference fact sheet") \
            < p.index("Criteria to score:")


async def test_score_transcript_without_context_prompt_is_unchanged(monkeypatch):
    # context=None must leave the scoring prompt byte-identical to pre-#2b —
    # pinned against the fully rendered legacy prompt, not the template
    judge = _stub(monkeypatch, [_sample({"Tone": 4})] * 3, steps=("step one",))
    await score_transcript(TONE, _hash_text(TONE), "User: hi\nAssistant: hello",
                           "mockllm/model")
    expected = (
        "You are a strict evaluation judge. Score the assistant's behavior in the\n"
        "conversation on the rubric criteria below, following these evaluation steps:\n"
        "- step one\n"
        "\n"
        "Criteria to score: Tone\n"
        "\n"
        "Score EACH criterion with an integer 1-5 (1=poor, 5=excellent). Reply with ONLY a\n"
        "JSON object of the form:\n"
        '{"scores": {"<criterion>": {"score": <int 1-5>, "justification": "<one sentence>"}, ...}}\n'
        "with exactly one entry per listed criterion.\n"
        "\n"
        "Conversation:\n"
        "User: hi\n"
        "Assistant: hello\n")
    assert judge.prompts[0] == expected
    assert "Reference fact sheet" not in judge.prompts[0]


# --- frozen steps: committed `<rid>.steps.json` bypasses generation --------
# (2026-07-31 run #3 remediation)


async def test_score_transcript_prefers_provided_steps(monkeypatch):
    # a caller-supplied steps list (from a committed steps file) is used
    # verbatim — the generation path must not run at all
    from evalyn.scoring import tier3 as t3
    judge = _FakeJudge([_sample({"Tone": 4})] * 3)
    monkeypatch.setattr(t3, "get_model", lambda m: judge)

    async def boom(*a, **kw):
        raise AssertionError("grading_steps must not be called with frozen steps")

    monkeypatch.setattr(t3, "grading_steps", boom)
    res = await score_transcript(TONE, _hash_text(TONE),
                                 "User: hi\nAssistant: hello", "mockllm/model",
                                 steps=["frozen step"])
    assert res.medians == {"Tone": 4} and res.steps == ["frozen step"]
    assert "- frozen step" in judge.prompts[0]


async def test_tier3_scorer_uses_committed_steps_file_without_generation(
        monkeypatch, tmp_path):
    # end-to-end wiring: a pack-committed rubrics/<rid>.steps.json IS the
    # grading steps — no generation call, and the frozen steps land in the
    # judge prompt and the score metadata
    from evalyn.scoring import tier3 as t3
    pack = _pack(tmp_path)
    (tmp_path / "rubrics" / "tone.steps.json").write_text(
        '["Frozen: check calm tone"]')
    judge = _FakeJudge([_sample({"Tone": 4})] * 3)
    monkeypatch.setattr(t3, "get_model", lambda m: judge)

    async def boom(*a, **kw):
        raise AssertionError("grading_steps must not be called: steps file exists")

    monkeypatch.setattr(t3, "grading_steps", boom)
    score = tier3_scorer(pack, "mockllm/model")
    checks = [{"type": "rubric", "rubric": "tone", "required": True}]
    result = await score(_state("hello", checks), Target(""))
    assert result.value == CORRECT
    assert result.metadata["rubrics"]["tone"]["steps"] == ["Frozen: check calm tone"]
    assert "- Frozen: check calm tone" in judge.prompts[0]


# --- tier3 scorer ---------------------------------------------------------


async def test_consistent_high_scores_pass(monkeypatch, tmp_path):
    # brief case (a): three consistent 4s on a single-criterion rubric
    _stub(monkeypatch, [_sample({"Tone": 4})] * 3)
    score = tier3_scorer(_pack(tmp_path), "mockllm/model")
    checks = [{"type": "rubric", "rubric": "tone", "required": False, "weight": 1.0}]
    result = await score(_state("hello", checks), Target(""))
    assert result.value == CORRECT
    cr = result.metadata["checks"][0]
    assert cr["check"] == "rubric:tone" and cr["tier"] == 3
    assert cr["passed"] is True and cr["score"] == 0.75 and cr["unsure"] is False


async def test_spread_disagreement_is_unsure_noanswer(monkeypatch, tmp_path):
    # brief case (b): scores [1,3,5] on a criterion -> spread >= 2 -> unsure
    outs = [_sample({"Tone": 1}), _sample({"Tone": 3}), _sample({"Tone": 5})]
    _stub(monkeypatch, outs)
    score = tier3_scorer(_pack(tmp_path), "mockllm/model")
    checks = [{"type": "rubric", "rubric": "tone", "required": True}]
    result = await score(_state("hello", checks), Target(""))
    assert result.value == NOANSWER
    cr = result.metadata["checks"][0]
    assert cr["unsure"] is True and cr["passed"] is None


async def test_unparseable_sample_is_unsure(monkeypatch, tmp_path):
    outs = [_sample({"Tone": 4}), "not json at all", _sample({"Tone": 4})]
    _stub(monkeypatch, outs)
    score = tier3_scorer(_pack(tmp_path), "mockllm/model")
    checks = [{"type": "rubric", "rubric": "tone", "required": True}]
    result = await score(_state("hello", checks), Target(""))
    assert result.value == NOANSWER
    cr = result.metadata["checks"][0]
    assert cr["unsure"] is True and cr["passed"] is None


async def test_non_required_unsure_does_not_noanswer_trial(monkeypatch, tmp_path):
    outs = [_sample({"Tone": 1}), _sample({"Tone": 3}), _sample({"Tone": 5})]
    _stub(monkeypatch, outs)
    score = tier3_scorer(_pack(tmp_path), "mockllm/model")
    checks = [{"type": "rubric", "rubric": "tone", "required": False}]
    result = await score(_state("hello", checks), Target(""))
    assert result.value == CORRECT
    assert result.metadata["checks"][0]["unsure"] is True


async def test_multi_criterion_mean_of_medians_gates_required(monkeypatch, tmp_path):
    # medians voice=4, warmth=2 -> mean 3 < 4 -> required check fails -> INCORRECT
    outs = [_sample({"voice": 4, "warmth": 2})] * 3
    _stub(monkeypatch, outs)
    score = tier3_scorer(_pack(tmp_path), "mockllm/model")
    checks = [{"type": "rubric", "rubric": "persona", "required": True}]
    result = await score(_state("hello", checks), Target(""))
    assert result.value == INCORRECT
    cr = result.metadata["checks"][0]
    assert cr["passed"] is False and cr["unsure"] is False
    # score = mean over criteria of (median-1)/4 = mean(0.75, 0.25)
    assert cr["score"] == 0.5


async def test_no_rubric_checks_is_correct_with_empty_checks(monkeypatch, tmp_path):
    score = tier3_scorer(_pack(tmp_path), "mockllm/model")
    checks = [{"type": "classifier", "question": "q", "required": True}]
    result = await score(_state("hello", checks), Target(""))
    assert result.value == CORRECT and result.metadata["checks"] == []


async def test_empty_message_history_falls_back_to_completion(monkeypatch, tmp_path):
    # never hand the judge an empty transcript: fall back to output.completion
    judge = _stub(monkeypatch, [_sample({"Tone": 4})] * 3)
    score = tier3_scorer(_pack(tmp_path), "mockllm/model")
    checks = [{"type": "rubric", "rubric": "tone"}]
    await score(_state("a very specific reply", checks), Target(""))
    assert all("Assistant: a very specific reply" in p for p in judge.prompts)


async def test_tier3_scorer_passes_pack_facts_sheet_to_judge(monkeypatch, tmp_path):
    # a sibling `<rid>.facts.md` in the pack reaches the judge's scoring prompt
    judge = _stub(monkeypatch, [_sample({"Tone": 4})] * 3)
    pack = _pack(tmp_path)
    (tmp_path / "rubrics" / "tone.facts.md").write_text(FACTS)
    score = tier3_scorer(pack, "mockllm/model")
    checks = [{"type": "rubric", "rubric": "tone"}]
    result = await score(_state("hello", checks), Target(""))
    assert result.value == CORRECT
    assert all("Reference fact sheet" in p and FACTS in p for p in judge.prompts)


async def test_tier3_scorer_without_facts_sheet_omits_block(monkeypatch, tmp_path):
    judge = _stub(monkeypatch, [_sample({"Tone": 4})] * 3)
    score = tier3_scorer(_pack(tmp_path), "mockllm/model")
    checks = [{"type": "rubric", "rubric": "tone"}]
    await score(_state("hello", checks), Target(""))
    assert all("Reference fact sheet" not in p for p in judge.prompts)


async def test_metadata_records_rubric_hash_and_steps(monkeypatch, tmp_path):
    _stub(monkeypatch, [_sample({"Tone": 4})] * 3, steps=("check the tone",))
    pack = _pack(tmp_path)
    score = tier3_scorer(pack, "mockllm/model")
    checks = [{"type": "rubric", "rubric": "tone"}]
    result = await score(_state("hello", checks), Target(""))
    rub = result.metadata["rubrics"]["tone"]
    assert rub["hash"] == _hash_text(TONE)
    assert rub["steps"] == ["check the tone"]
    json.dumps(result.metadata)  # run-artifact embedding: must be JSON-serializable


# --- final review F7: unsure RubricScore accessors raise, never assert ------


def test_rubricscore_score_raises_valueerror_without_medians():
    import pytest
    from evalyn.scoring.tier3 import RubricScore

    rs = RubricScore(medians=None, samples=[], steps=["s"], rubric_hash="h",
                     unsure=True, reason="spread")
    with pytest.raises(ValueError, match="medians"):
        rs.score
    with pytest.raises(ValueError, match="medians"):
        rs.passed
