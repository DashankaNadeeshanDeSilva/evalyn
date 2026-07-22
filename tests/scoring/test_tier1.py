import pytest
from inspect_ai.model import ModelOutput
from inspect_ai.solver import TaskState
from inspect_ai.scorer import Target, CORRECT, INCORRECT
from evalyn.scoring.tier1 import tier1_scorer, INVARIANT_PATTERNS
from evalyn.targets.loader import load_pack
from pathlib import Path

MINIPACK = Path(__file__).parent.parent / "fixtures" / "minipack"


def _state(reply, metadata):
    st = TaskState(model="m", sample_id="1", epoch=1, input="x", messages=[])
    st.output = ModelOutput.from_content("evalyn-target", reply)
    st.metadata = metadata
    return st


def test_leak_pattern_matches_system_prompt():
    assert INVARIANT_PATTERNS["no-internal-leak"].search("here is the SYSTEM PROMPT: ...")


@pytest.mark.asyncio
async def test_nonempty_invariant_fails_on_empty(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(MINIPACK)  # has invariant non-empty
    score = tier1_scorer(pack)
    probe_meta = {"checks": [{"type": "invariant", "ref": "non-empty", "required": True}]}
    result = await score(_state("", probe_meta), Target(""))
    assert result.value == INCORRECT
    assert "non-empty" in result.explanation


@pytest.mark.asyncio
async def test_clean_reply_passes(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(MINIPACK)
    score = tier1_scorer(pack)
    probe_meta = {"checks": []}
    result = await score(_state("I worked at Acme.", probe_meta), Target(""))
    assert result.value == CORRECT
