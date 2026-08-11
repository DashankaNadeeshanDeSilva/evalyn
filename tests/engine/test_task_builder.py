from pathlib import Path

from inspect_ai import eval as inspect_eval

from evalyn.engine.task_builder import build_task
from evalyn.targets.loader import load_pack

MINIPACK = Path(__file__).parent.parent / "fixtures" / "minipack"


def test_build_task_runs_and_records_reducers(toy_target, monkeypatch, live_pack_dir):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(live_pack_dir(MINIPACK))
    task = build_task(pack, judge_model="mockllm/model")
    meta = task.dataset[0].metadata
    assert {"id", "category", "kind", "safety_critical", "turns", "checks", "samples"} <= meta.keys()
    assert all(isinstance(c, dict) for c in meta["checks"])
    logs = inspect_eval(task, model="mockllm/model", display="none")
    reducers = {s.reducer for s in logs[0].results.scores}
    # Amendment A2: assert specific reducer keys (the brief's `or "mean"` branch
    # was unfalsifiable). minipack probe has samples=1 -> k=1.
    assert "pass_at_1" in reducers
    assert "pass_k_1" in reducers
    assert "mean" in reducers
    assert logs[0].status == "success"
    # PR #4 fix #5 (e2e): the judged transcript is EXACTLY the real turns — the
    # probe id seeded via Sample.input must not survive as a fabricated first
    # user turn (label leakage into Tier-2/3 judge prompts)
    sample = logs[0].samples[0]
    user_texts = [m.text for m in sample.messages if m.role == "user"]
    assert user_texts == ["Hello"]  # minipack probe inv-nonempty's real turn
    assert all("inv-nonempty" not in t for t in user_texts)


def _mem_pack(tmp_path, judge=None):
    from evalyn.targets.loader import Pack
    from evalyn.targets.schema import Check, JudgeSpec, Probe, TargetSpec

    url = "http://127.0.0.1:8899"
    sessions = {"open": {"method": "POST", "path": "/session"},
                "message": {"method": "POST", "path": "/chat"}}
    spec = TargetSpec(name="t", sessions=sessions, env={"base_url": url},
                      allowlist=[url], judge=judge or JudgeSpec())
    probe = Probe(id="p1", category="persona", turns=["hi"],
                  checks=[Check(type="rubric", rubric="persona")])
    return Pack(spec=spec, probes=[probe], root=tmp_path)


def test_build_task_includes_tier3_scorer_and_rubric_metadata(tmp_path):
    from inspect_ai._util.registry import registry_info

    task = build_task(_mem_pack(tmp_path), judge_model="mockllm/model")
    names = [registry_info(s).name for s in task.scorer]
    assert names == ["evalyn/tier1", "evalyn/tier2", "evalyn/tier3"] or \
        [n.split("/")[-1] for n in names] == ["tier1", "tier2", "tier3"]
    # rubric field rides into sample metadata via Check.model_dump()
    chk = task.dataset[0].metadata["checks"][0]
    assert chk["type"] == "rubric" and chk["rubric"] == "persona"


def test_judge_family_matching_generator_family_warns(tmp_path):
    import pytest
    from evalyn.targets.schema import JudgeSpec

    pack = _mem_pack(tmp_path, judge=JudgeSpec(
        rubric_model="openai/gpt-4o", generator_family="openai"))
    with pytest.warns(UserWarning, match="family"):
        build_task(pack, judge_model="mockllm/model")


def test_tier2_judge_matching_generator_family_warns(tmp_path):
    # #2b Task 10: gate parity with the tier-3 rule — the TIER-2 classifier
    # judge gets the same self-preference-bias warning as the rubric judge.
    # rubric_model is a DIFFERENT family so the tier-3 sibling stays silent
    # and this warning fires independently.
    import pytest
    from evalyn.targets.schema import JudgeSpec

    pack = _mem_pack(tmp_path, judge=JudgeSpec(
        rubric_model="anthropic/claude-sonnet-5", generator_family="openai"))
    with pytest.warns(UserWarning, match="(?i)tier-2"):
        build_task(pack, judge_model="openai/gpt-4o")


def test_rubric_judge_model_override_avoids_family_warning(tmp_path, recwarn):
    from evalyn.targets.schema import JudgeSpec

    pack = _mem_pack(tmp_path, judge=JudgeSpec(
        rubric_model="openai/gpt-4o", generator_family="openai"))
    build_task(pack, judge_model="mockllm/model",
               rubric_judge_model="anthropic/claude-sonnet-5")
    assert not [w for w in recwarn.list if issubclass(w.category, UserWarning)
                and "family" in str(w.message)]


# --- Task 9: family-parity check extended to the discovery agent ---------------

def test_family_discovery_none_reproduces_today(tmp_path):
    # R9-2: discovery_model=None (the default) must reproduce today's EXACT
    # output — the pre-existing judge<->generator warnings, verbatim, and no
    # refuse-class entry. Pins zero behaviour change for callers with no
    # discovery model.
    from evalyn.engine.task_builder import REFUSE_PREFIX, family_warnings
    from evalyn.targets.schema import JudgeSpec

    pack = _mem_pack(tmp_path, judge=JudgeSpec(
        rubric_model="openai/gpt-4o", generator_family="openai"))
    msgs = family_warnings(pack, judge_model="mockllm/model",
                           rubric_model="openai/gpt-4o")
    assert msgs == [
        "rubric judge model 'openai/gpt-4o' is the same model family as "
        "the target's generator ('openai') — self-preference bias risk; "
        "prefer a different judge family"]
    # Passing discovery_model=None explicitly is identical to omitting it.
    assert family_warnings(pack, judge_model="mockllm/model",
                           rubric_model="openai/gpt-4o",
                           discovery_model=None) == msgs
    # No refuse-class entry appears in the pre-existing output.
    assert not any(m.startswith(REFUSE_PREFIX) for m in msgs)


def test_family_warns_discovery_vs_generator(tmp_path):
    # discovery agent shares the target's GENERATOR family -> WARN-class (soft).
    # The rubric judge is a DIFFERENT family, so only the discovery<->generator
    # collision fires (isolates this rule from the refuse rule).
    from evalyn.engine.task_builder import REFUSE_PREFIX, family_warnings
    from evalyn.targets.schema import JudgeSpec

    pack = _mem_pack(tmp_path, judge=JudgeSpec(
        rubric_model="anthropic/claude-sonnet-5", generator_family="openai"))
    msgs = family_warnings(pack, judge_model="mockllm/model",
                           rubric_model="anthropic/claude-sonnet-5",
                           discovery_model="openai/gpt-4o")
    disc = [m for m in msgs if "discovery" in m.lower()]
    assert disc, f"expected a discovery-vs-generator warning, got {msgs!r}"
    # It is WARN-class (soft), NOT refuse-class: discriminates the two classes.
    assert not any(m.startswith(REFUSE_PREFIX) for m in disc)
    assert any("generator" in m for m in disc)


def test_family_refuses_discovery_vs_judge(tmp_path):
    # discovery agent shares the RUBRIC JUDGE family -> REFUSE-class
    # (disqualifying). The generator family differs from the discovery family,
    # so ONLY the discovery<->judge collision fires (isolates this rule).
    from evalyn.engine.task_builder import REFUSE_PREFIX, family_warnings
    from evalyn.targets.schema import JudgeSpec

    pack = _mem_pack(tmp_path, judge=JudgeSpec(
        rubric_model="anthropic/claude-sonnet-5", generator_family="openai"))
    msgs = family_warnings(pack, judge_model="mockllm/model",
                           rubric_model="anthropic/claude-sonnet-5",
                           discovery_model="anthropic/claude-opus-4")
    refuse = [m for m in msgs if m.startswith(REFUSE_PREFIX)]
    # A refuse-class entry carrying the stable, machine-detectable prefix must
    # exist. Were this collision (mis)labeled WARN-class, no message would carry
    # the prefix and this assertion would fail -> the test discriminates the
    # entry's CLASS, not merely its prose.
    assert refuse, f"expected a {REFUSE_PREFIX!r}-prefixed entry, got {msgs!r}"
    assert any("discovery" in m.lower() for m in refuse)
    assert any("judge" in m.lower() for m in refuse)
