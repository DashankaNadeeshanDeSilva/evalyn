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
