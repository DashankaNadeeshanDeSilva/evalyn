import pytest
from inspect_ai.model import ModelOutput, get_model

from evalyn.scoring.rubrics import (
    _hash_text,
    grading_steps,
    load_rubric,
    load_rubric_context,
    parse_criteria,
)
from evalyn.targets.loader import Pack
from evalyn.targets.schema import TargetSpec

RUBRIC = """# Persona

## voice
First person, in character.

## warmth
Friendly, never dismissive.
"""


def _pack(tmp_path):
    (tmp_path / "rubrics").mkdir()
    (tmp_path / "rubrics" / "persona.md").write_text(RUBRIC)
    spec = TargetSpec(name="t", sessions={}, allowlist=[])
    return Pack(spec=spec, probes=[], root=tmp_path)


def test_load_rubric_returns_text_and_stable_hash(tmp_path):
    pack = _pack(tmp_path)
    text, h = load_rubric(pack, "persona")
    assert "First person" in text and h == _hash_text(text)


def test_missing_rubric_raises(tmp_path):
    pack = _pack(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_rubric(pack, "nope")


def test_facts_sheet_changes_rubric_hash(tmp_path):
    # convention over config: a sibling `<rid>.facts.md` is hash-coupled into
    # load_rubric's hash, so calibration records, is_stale, and the
    # grading-steps cache key all stale automatically on a facts edit
    pack = _pack(tmp_path)
    text1, h1 = load_rubric(pack, "persona")
    (tmp_path / "rubrics" / "persona.facts.md").write_text(
        "FACT: owner has 6 years experience")
    text2, h2 = load_rubric(pack, "persona")
    assert text1 == text2          # criteria/prompt text stays rubric-only
    assert h1 != h2                # but the hash covers the facts sheet
    assert load_rubric_context(pack, "persona") == "FACT: owner has 6 years experience"


def test_facts_sheet_edit_changes_hash_again(tmp_path):
    pack = _pack(tmp_path)
    (tmp_path / "rubrics" / "persona.facts.md").write_text("FACT: v1")
    _, h1 = load_rubric(pack, "persona")
    (tmp_path / "rubrics" / "persona.facts.md").write_text("FACT: v2")
    _, h2 = load_rubric(pack, "persona")
    assert h1 != h2


def test_no_facts_sheet_is_none_and_hash_stable(tmp_path):
    # rubrics without a facts sheet hash exactly as before (sha256 of the text)
    pack = _pack(tmp_path)
    text, h = load_rubric(pack, "persona")
    assert load_rubric_context(pack, "persona") is None
    assert h == _hash_text(text)


def test_parse_criteria_extracts_h2_section_names():
    assert parse_criteria(RUBRIC) == ["voice", "warmth"]


def test_parse_criteria_falls_back_to_h1_title():
    assert parse_criteria("# Persona\nFirst person, in character.") == ["Persona"]


def test_parse_criteria_falls_back_to_overall_without_headings():
    assert parse_criteria("Just be good.") == ["overall"]


def _stub_steps_model(monkeypatch, outputs):
    """Stub rubrics.get_model with a counting mockllm factory."""
    from evalyn.scoring import rubrics as r
    calls = {"n": 0}

    def fake_get_model(name):
        calls["n"] += 1
        return get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", o)
                            for o in outputs])

    monkeypatch.setattr(r, "get_model", fake_get_model)
    return calls


async def test_grading_steps_parses_json_array(monkeypatch, tmp_path):
    _stub_steps_model(monkeypatch, ['["check voice", "check warmth"]'])
    steps = await grading_steps(RUBRIC, _hash_text(RUBRIC), "mockllm/model", tmp_path)
    assert steps == ["check voice", "check warmth"]


async def test_grading_steps_cached_per_rubric_hash_and_judge_model(monkeypatch, tmp_path):
    calls = _stub_steps_model(monkeypatch, ['["step a"]'])
    h = _hash_text(RUBRIC)
    first = await grading_steps(RUBRIC, h, "mockllm/model", tmp_path)
    second = await grading_steps(RUBRIC, h, "mockllm/model", tmp_path)
    assert first == second == ["step a"] and calls["n"] == 1  # cache hit, no 2nd call
    # a different judge model must NOT reuse the cache entry
    await grading_steps(RUBRIC, h, "mockllm/other", tmp_path)
    assert calls["n"] == 2


async def test_grading_steps_without_cache_dir_calls_model_each_time(monkeypatch):
    calls = _stub_steps_model(monkeypatch, ['["step a"]'])
    h = _hash_text(RUBRIC)
    await grading_steps(RUBRIC, h, "mockllm/model", None)
    await grading_steps(RUBRIC, h, "mockllm/model", None)
    assert calls["n"] == 2


async def test_grading_steps_unparseable_falls_back_to_raw_rubric(monkeypatch):
    _stub_steps_model(monkeypatch, ["Sure! Here are some steps: 1. vibe check"])
    steps = await grading_steps(RUBRIC, _hash_text(RUBRIC), "mockllm/model", None)
    assert len(steps) == 1 and "First person" in steps[0]


async def test_grading_steps_cache_write_is_atomic(monkeypatch, tmp_path):
    # Task-5 note: concurrent first-time samples must never observe a partial
    # cache file — the write goes to a temp file then os.replace, leaving no
    # temp residue behind
    import os as _os

    from evalyn.scoring import rubrics as r
    replaced = []
    real_replace = _os.replace

    def spy_replace(src, dst):
        replaced.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(r.os, "replace", spy_replace)
    _stub_steps_model(monkeypatch, ['["step a"]'])
    steps = await grading_steps(RUBRIC, _hash_text(RUBRIC), "mockllm/model", tmp_path)
    cached = list(tmp_path.iterdir())
    assert len(cached) == 1 and cached[0].suffix == ".json"  # no temp residue
    import json
    assert json.loads(cached[0].read_text()) == steps == ["step a"]
    assert len(replaced) == 1 and replaced[0][1] == str(cached[0])
