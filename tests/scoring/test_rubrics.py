import pytest
from inspect_ai.model import ModelOutput, get_model

from evalyn.scoring.rubrics import (
    _hash_text,
    grading_steps,
    load_rubric,
    load_rubric_context,
    load_rubric_steps,
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


# --- frozen grading steps: committed `<rid>.steps.json` artifacts ----------
# (2026-07-31 run #3 remediation: the judge's operative instructions become a
# human-reviewed in-pack file, not a runtime LLM artifact)


def test_load_rubric_steps_none_without_file(tmp_path):
    pack = _pack(tmp_path)
    assert load_rubric_steps(pack, "persona") is None


def test_load_rubric_steps_reads_committed_file(tmp_path):
    pack = _pack(tmp_path)
    (tmp_path / "rubrics" / "persona.steps.json").write_text(
        '["Check voice is first person", "Check warmth"]')
    assert load_rubric_steps(pack, "persona") == [
        "Check voice is first person", "Check warmth"]


@pytest.mark.parametrize("content", [
    "not json at all",          # invalid JSON
    '"a bare string"',          # valid JSON, not a list
    "[]",                       # empty list
    '["ok", ""]',               # empty-string entry
    '["ok", 3]',                # non-string entry
])
def test_load_rubric_steps_malformed_raises(tmp_path, content):
    pack = _pack(tmp_path)
    (tmp_path / "rubrics" / "persona.steps.json").write_text(content)
    with pytest.raises(ValueError, match="steps"):
        load_rubric_steps(pack, "persona")


def test_steps_file_changes_rubric_hash(tmp_path):
    # the hash COVERS the frozen steps exactly like the facts sheet: editing
    # committed steps stales calibration records, is_stale, and cache keys
    pack = _pack(tmp_path)
    text1, h1 = load_rubric(pack, "persona")
    (tmp_path / "rubrics" / "persona.steps.json").write_text('["v1 step"]')
    text2, h2 = load_rubric(pack, "persona")
    assert text1 == text2          # rubric/prompt text stays rubric-only
    assert h1 != h2                # but the hash covers the steps file
    (tmp_path / "rubrics" / "persona.steps.json").write_text('["v2 step"]')
    _, h3 = load_rubric(pack, "persona")
    assert h2 != h3


def test_no_steps_no_facts_hash_is_plain_text_sha(tmp_path):
    # rubrics without steps or facts files hash exactly as before, so other
    # packs are unaffected by the steps-freeze mechanism
    pack = _pack(tmp_path)
    _, h = load_rubric(pack, "persona")
    assert h == _hash_text(RUBRIC)


def test_facts_and_steps_fold_into_hash_deterministically(tmp_path):
    # a rubric may have both files; text-only, facts-only, steps-only and
    # facts+steps must all hash distinctly, and repeat loads are stable
    pack = _pack(tmp_path)
    _, h_text = load_rubric(pack, "persona")
    (tmp_path / "rubrics" / "persona.facts.md").write_text("FACT: x")
    _, h_facts = load_rubric(pack, "persona")
    (tmp_path / "rubrics" / "persona.steps.json").write_text('["step"]')
    _, h_both = load_rubric(pack, "persona")
    (tmp_path / "rubrics" / "persona.facts.md").unlink()
    _, h_steps = load_rubric(pack, "persona")
    assert len({h_text, h_facts, h_steps, h_both}) == 4
    (tmp_path / "rubrics" / "persona.facts.md").write_text("FACT: x")
    _, h_both_again = load_rubric(pack, "persona")
    assert h_both == h_both_again


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


async def test_grading_steps_accumulates_generation_usage(monkeypatch):
    # PR #6 fix: the optional usage_acc seam captures the generation call's
    # tokens (model-id -> {input_tokens, output_tokens}) so callers that meter
    # their own spend (judge_pair) can count steps generation
    from inspect_ai.model import ModelUsage

    from evalyn.scoring import rubrics as r

    class _M:
        async def generate(self, prompt):
            out = ModelOutput.from_content("mockllm/model", '["step a"]')
            out.usage = ModelUsage(input_tokens=7, output_tokens=3)
            return out

    monkeypatch.setattr(r, "get_model", lambda name: _M())
    acc: dict = {}
    steps = await grading_steps(RUBRIC, _hash_text(RUBRIC), "mockllm/model",
                                None, usage_acc=acc)
    assert steps == ["step a"]
    assert acc == {"mockllm/model": {"input_tokens": 7, "output_tokens": 3}}


async def test_grading_steps_cache_hit_accumulates_nothing(monkeypatch, tmp_path):
    # no generation on a cache hit -> nothing metered
    _stub_steps_model(monkeypatch, ['["step a"]'])
    h = _hash_text(RUBRIC)
    await grading_steps(RUBRIC, h, "mockllm/model", tmp_path)  # populate cache
    acc: dict = {}
    await grading_steps(RUBRIC, h, "mockllm/model", tmp_path, usage_acc=acc)
    assert acc == {}


async def test_grading_steps_without_cache_dir_calls_model_each_time(monkeypatch):
    calls = _stub_steps_model(monkeypatch, ['["step a"]'])
    h = _hash_text(RUBRIC)
    await grading_steps(RUBRIC, h, "mockllm/model", None)
    await grading_steps(RUBRIC, h, "mockllm/model", None)
    assert calls["n"] == 2


async def test_grading_steps_unparseable_raises_and_never_caches(monkeypatch, tmp_path):
    # RETIRED SEAM (2026-07-31, run #3 root cause): the old behavior silently
    # fell back to [rubric_text[:500]] AND cached it — the judge then scored
    # against a truncated rubric with no band definitions. New contract:
    # unparseable steps output FAILS LOUDLY (refusing beats judging with a
    # truncated rubric) and nothing is ever written to the cache.
    _stub_steps_model(monkeypatch, ["Sure! Here are some steps: 1. vibe check"])
    with pytest.raises(RuntimeError, match="grading steps"):
        await grading_steps(RUBRIC, _hash_text(RUBRIC), "mockllm/model", tmp_path)
    assert list(tmp_path.iterdir()) == []  # no cache entry, no temp residue


async def test_grading_steps_non_list_json_raises(monkeypatch, tmp_path):
    # valid JSON that is not a list (e.g. a bare string) must fail loudly too —
    # iterating a str would silently produce per-character "steps"
    _stub_steps_model(monkeypatch, ['"check the vibe"'])
    with pytest.raises(RuntimeError, match="grading steps"):
        await grading_steps(RUBRIC, _hash_text(RUBRIC), "mockllm/model", tmp_path)
    assert list(tmp_path.iterdir()) == []


async def test_grading_steps_strips_code_fences(monkeypatch, tmp_path):
    # micro-fix bundled with the freeze: a ```json fenced reply is ordinary
    # model behavior, not a failure — unwrap it before parsing
    _stub_steps_model(
        monkeypatch, ['```json\n["check voice", "check warmth"]\n```'])
    steps = await grading_steps(RUBRIC, _hash_text(RUBRIC), "mockllm/model", tmp_path)
    assert steps == ["check voice", "check warmth"]


async def test_grading_steps_prompt_demands_verbatim_criterion_headings(monkeypatch):
    # 2026-07-30 calibrate failure: generated steps renamed the rubric's
    # criteria ("Claim Support"/"Specificity" vs the actual `##` headings) and
    # the judge followed the steps' names — the generator must be instructed
    # to use each criterion's exact heading name verbatim
    from evalyn.scoring import rubrics as r
    prompts = []

    class _Judge:
        async def generate(self, prompt):
            prompts.append(prompt)
            return ModelOutput.from_content("mockllm/model", '["step"]')

    monkeypatch.setattr(r, "get_model", lambda name: _Judge())
    await grading_steps(RUBRIC, _hash_text(RUBRIC), "mockllm/model", None)
    [p] = prompts
    assert "exact" in p and "verbatim" in p and "heading" in p


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
