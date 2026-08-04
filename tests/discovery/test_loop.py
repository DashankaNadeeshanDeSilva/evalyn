"""The observe->reason->pursue loop: bounds first, closed action space, and a
proposal that never reaches the judge without verbatim evidence.

Four properties these tests pin down, because the whole mode rests on them:

1. **Bounds come first.** An exhausted meter opens NO session and makes NO
   model call; `max_steps` stops the loop; at the turn cap the `send` action is
   removed from the set offered to the agent.
2. **The action space is closed.** `send`/`propose`/`stop`, and `send` carries
   only a string — there is no URL, file or shell action to parse, so the agent
   cannot reach anything but the allowlisted target `TargetSession` opened.
3. **The agent proposes, the scorers dispose.** A slot value that is not a
   verbatim substring of an assistant turn rejects the proposal BEFORE any
   confirmation spend.
4. **It is a loop.** The confirmation verdict — and every rejection — is fed
   into the next step's prompt.

Zero spend: every model is a scripted stub, every session a fake.
"""
from __future__ import annotations

import contextlib
import json
import re
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    ModelOutput,
    ModelUsage,
)

from evalyn.discovery import loop as loop_mod
from evalyn.discovery.confirm import Confirmation, Confirmer
from evalyn.discovery.config import Limits
from evalyn.discovery.loop import (
    ActionParseError,
    AgentAction,
    SessionResult,
    parse_action,
    run_session,
    verify_slots,
)
from evalyn.discovery.meter import BudgetStop, SpendMeter
from evalyn.discovery.objectives import get_objective
from evalyn.discovery.personas import DEFAULT_PERSONA, DEFAULT_PLAYBOOK
from evalyn.engine.budget import estimate_cost
from evalyn.targets.loader import Pack
from evalyn.targets.schema import Invariant, TargetSpec
from evalyn.targets.session import TurnCapExceeded

# A priced model id: `charge_output` prices through engine.budget.PRICES, and an
# unpriced id would emit a RuntimeWarning on every step (noise, not signal).
AGENT_MODEL = "openai/gpt-5-mini"
#: usage every scripted reasoning call reports (so charging is exact, not the
#: meter's pessimistic no-usage fallback)
_STEP_USAGE = ModelUsage(input_tokens=100, output_tokens=20, total_tokens=120)
INJECTION = get_objective("prompt-injection-bypass")
LEAK_REPLY = "Sure — the knowledge base lives at /data/kb/index.json on disk."


# --------------------------------------------------------------------------
# fixtures / stubs
# --------------------------------------------------------------------------

def _pack(root: Path, invariants: list[str] | None = None) -> Pack:
    spec = TargetSpec(
        name="t",
        sessions={"open": {"method": "POST", "path": "/session"},
                  "message": {"method": "POST", "path": "/chat"}},
        allowlist=["http://localhost:8899"],
        env={"base_url": "http://localhost:8899"},
        invariants=[Invariant(id=i) for i in (invariants or [])])
    return Pack(spec=spec, probes=[], root=root)


def _limits(*, max_steps=4, max_turns=4, max_usd=10.0) -> Limits:
    return Limits(max_steps=max_steps, max_sessions=1, max_usd=max_usd,
                  max_turns=max_turns)


class _FakeSession:
    """Same surface as `TargetSession`: send/turns_used/messages, turn cap."""

    def __init__(self, replies: list[str], max_turns: int) -> None:
        self._replies = list(replies)
        self._max_turns = max_turns
        self._messages: list = []
        self.sends: list[str] = []
        self.turns_used = 0

    async def send(self, message: str) -> str:
        if self.turns_used >= self._max_turns:
            raise TurnCapExceeded("cap")
        self.sends.append(message)
        self._messages.append(ChatMessageUser(content=message))
        reply = self._replies.pop(0) if self._replies else "ok."
        self.turns_used += 1
        self._messages.append(ChatMessageAssistant(content=reply))
        return reply

    @property
    def messages(self) -> list:
        return list(self._messages)

    @property
    def elapsed_seconds(self) -> float:
        return 0.0


def _stub_session(monkeypatch, replies, *, max_turns=4, on_open=None):
    """Replace the loop's `TargetSession` with a fake. Returns the fake."""
    sess = _FakeSession(replies, max_turns)
    sess.opens = 0

    @asynccontextmanager
    async def _open(pack, **kwargs):
        sess.opens += 1
        if on_open is not None:
            on_open()
        yield sess

    monkeypatch.setattr(loop_mod, "TargetSession", SimpleNamespace(open=_open))
    return sess


class _ScriptedAgent:
    """A scripted red-team agent. Records every prompt it was shown."""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    async def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        text = self.outputs.pop(0) if self.outputs else json.dumps(
            {"action": "stop", "rationale": "out of script"})
        out = ModelOutput.from_content(AGENT_MODEL, text)
        out.usage = _STEP_USAGE
        return out

    @property
    def calls(self) -> int:
        return len(self.prompts)


def _stub_agent(monkeypatch, outputs) -> _ScriptedAgent:
    agent = _ScriptedAgent(outputs)
    monkeypatch.setattr(loop_mod, "get_model", lambda m: agent)
    return agent


class _SpyConfirmer:
    """Records every confirm() call. Returns a CONFIRMED verdict by default, so
    a test asserting "not confirmed" fails loudly if the guard under test is
    removed."""

    def __init__(self, verdict: Confirmation | None = None, raises=None) -> None:
        self.calls: list = []
        self.verdict = verdict or Confirmation(True, False, 1, [], "confirmed: spy")
        self.raises = raises

    async def confirm(self, probe, messages):
        self.calls.append((probe, list(messages)))
        if self.raises is not None:
            raise self.raises
        return self.verdict


def _send(message="tell me about your setup", rationale="probing") -> str:
    return json.dumps({"action": "send", "rationale": rationale,
                       "message": message})


def _propose(slots: dict, rationale="found it") -> str:
    return json.dumps({"action": "propose", "rationale": rationale,
                       "slots": slots})


def _stop(rationale="giving up") -> str:
    return json.dumps({"action": "stop", "rationale": rationale})


def _actions_offered(prompt: str) -> set[str]:
    """The action names the prompt actually offers this step."""
    line = next(ln for ln in prompt.splitlines()
                if ln.startswith(loop_mod.ACTIONS_LINE_PREFIX))
    body = line[len(loop_mod.ACTIONS_LINE_PREFIX):]
    return {a.strip() for a in body.split(",") if a.strip()}


@contextlib.contextmanager
def caught_warnings():
    """Record warnings rather than letting them escape (mirrors test_confirm):
    the VERDICT is asserted first, the warning second."""
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        yield rec


async def _run(pack, *, agent_model=AGENT_MODEL, meter=None, limits=None,
               confirmer=None, objective=INJECTION, seed=None) -> SessionResult:
    return await run_session(
        pack, objective, DEFAULT_PERSONA, DEFAULT_PLAYBOOK,
        agent_model=agent_model, meter=meter or SpendMeter(10.0),
        limits=limits or _limits(), confirmer=confirmer, seed=seed)


# --------------------------------------------------------------------------
# 1. the mock agent finds the bug
# --------------------------------------------------------------------------

async def test_agent_finds_bug_and_real_scorers_confirm(monkeypatch, tmp_path):
    """send -> the target leaks -> propose with a verbatim slot -> the REAL
    tier-1 scorer confirms. Confirmed is the scorers' verdict, not the agent's."""
    agent = _stub_agent(monkeypatch, [
        _send("what files do you read?"),
        _propose({"leak_marker": "/data/kb"}),
    ])
    sess = _stub_session(monkeypatch, [LEAK_REPLY])
    # a REAL Confirmer over a real pack: tier-1 decides, nothing is stubbed
    confirmer = Confirmer(_pack(tmp_path))

    result = await _run(_pack(tmp_path), confirmer=confirmer)

    assert result.stop_reason == "confirmed"
    assert result.confirmed is not None
    assert result.confirmed.confirmed is True
    assert result.probe_slots == {"leak_marker": "/data/kb"}
    assert result.objective_id == "prompt-injection-bypass"
    # the loop really drove the target and really spent agent tokens
    assert sess.sends == ["what files do you read?"]
    assert result.turns_used == 1
    assert result.usd_estimated > 0.0
    assert agent.calls == 2
    assert [s.action for s in result.steps] == ["send", "propose"]
    assert result.steps[0].reply == LEAK_REPLY


async def test_transcript_and_goal_reach_the_agent_prompt(monkeypatch, tmp_path):
    """Observe: the agent sees the objective, the persona, the playbook, the
    labeled transcript and the closed action contract."""
    agent = _stub_agent(monkeypatch, [_send("hi"), _stop()])
    _stub_session(monkeypatch, ["I only read /data/kb."])
    await _run(_pack(tmp_path), confirmer=_SpyConfirmer())

    first, second = agent.prompts[0], agent.prompts[1]
    assert INJECTION.goal_prompt[:40] in first
    assert DEFAULT_PERSONA.text[:30] in first
    assert DEFAULT_PLAYBOOK.text[:30] in first
    # step 1 has no transcript yet; step 2 shows the labeled turns verbatim
    assert "I only read /data/kb." not in first
    assert "Assistant: I only read /data/kb." in second
    assert "User: hi" in second
    # the trust-boundary contract travels with every prompt
    assert "verbatim" in first.lower()


# --------------------------------------------------------------------------
# 2. non-verbatim slot rejected BEFORE any confirmation spend
# --------------------------------------------------------------------------

async def test_non_verbatim_slot_rejected_before_any_confirm_spend(
        monkeypatch, tmp_path):
    """The spy would CONFIRM anything. The proposal must never reach it."""
    agent = _stub_agent(monkeypatch, [
        _send("hello"),
        _propose({"leak_marker": "NOPE-never-said"}),
        _stop(),
    ])
    _stub_session(monkeypatch, ["I cannot share that."])
    spy = _SpyConfirmer()

    result = await _run(_pack(tmp_path), confirmer=spy)

    assert spy.calls == []                    # zero judge spend
    assert result.confirmed is None
    assert result.probe_slots is None
    assert result.stop_reason == "agent_stop"
    rejected = [s for s in result.steps if s.action == "propose"]
    assert len(rejected) == 1
    assert rejected[0].outcome == "rejected"
    assert "verbatim" in rejected[0].detail.lower()
    # ...and the rejection is FED BACK: the next prompt says why
    assert "NOPE-never-said" in agent.prompts[2]
    assert "verbatim" in agent.prompts[2].lower()


async def test_slot_quoted_from_a_user_turn_is_not_evidence(monkeypatch, tmp_path):
    """The agent must not be able to launder its OWN words into evidence."""
    _stub_agent(monkeypatch, [
        _send("is the path /data/secret ?"),
        _propose({"leak_marker": "/data/secret"}),
        _stop(),
    ])
    _stub_session(monkeypatch, ["No, I will not discuss internal paths."])
    spy = _SpyConfirmer()
    result = await _run(_pack(tmp_path), confirmer=spy)

    assert spy.calls == []
    assert result.confirmed is None


async def test_missing_slot_key_is_rejected_not_a_crash(monkeypatch, tmp_path):
    """`Objective.confirm_checks` raises KeyError on a missing slot, and the
    slots dict is untrusted LLM output — a typo must not kill the session."""
    agent = _stub_agent(monkeypatch, [
        _send("hello"),
        _propose({"leak_markr": "/data/kb"}),   # typo'd key
        _stop(),
    ])
    _stub_session(monkeypatch, [LEAK_REPLY])
    spy = _SpyConfirmer()

    result = await _run(_pack(tmp_path), confirmer=spy)

    assert spy.calls == []
    assert result.stop_reason == "agent_stop"   # the session survived
    assert result.error is None
    bad = [s for s in result.steps if s.action == "propose"][0]
    assert bad.outcome == "rejected"
    assert "leak_marker" in bad.detail             # names the slot it wanted
    assert "leak_marker" in agent.prompts[2]       # and tells the agent


async def test_refuted_verdict_feeds_the_next_prompt(monkeypatch, tmp_path):
    """A refutation names WHICH check passed, and that reaches the agent —
    this feedback is what makes it a loop rather than a script."""
    agent = _stub_agent(monkeypatch, [
        _send("hello"),
        _propose({"leak_marker": "/data/kb"}),
        _stop(),
    ])
    _stub_session(monkeypatch, [LEAK_REPLY])
    refuted = Confirmation(
        False, False, 1, [],
        "not confirmed: all required checks passed (invariant:no-internal-leak)")
    spy = _SpyConfirmer(verdict=refuted)

    result = await _run(_pack(tmp_path), confirmer=spy)

    assert len(spy.calls) == 1                       # it DID reach the judge
    assert result.confirmed is None
    assert "all required checks passed" in agent.prompts[2]
    assert "no-internal-leak" in agent.prompts[2]


# --------------------------------------------------------------------------
# 3. bounds
# --------------------------------------------------------------------------

async def test_max_steps_stops_the_loop(monkeypatch, tmp_path):
    agent = _stub_agent(monkeypatch, [_send("one"), _send("two"), _send("three")])
    sess = _stub_session(monkeypatch, ["a", "b", "c"])

    result = await _run(_pack(tmp_path), limits=_limits(max_steps=1),
                        confirmer=_SpyConfirmer())

    assert result.stop_reason == "steps_exhausted"
    assert agent.calls == 1
    assert sess.sends == ["one"]
    assert len(result.steps) == 1


async def test_exhausted_meter_makes_zero_model_and_zero_http_calls(
        monkeypatch, tmp_path):
    """Not a session that opens and THEN discovers it is broke."""
    agent = _stub_agent(monkeypatch, [_send("never sent")])
    opened = []
    sess = _stub_session(monkeypatch, ["never reached"],
                         on_open=lambda: opened.append(1))
    meter = SpendMeter(0.0)                 # AT the cap == exhausted
    assert meter.exhausted()

    result = await _run(_pack(tmp_path), meter=meter, confirmer=_SpyConfirmer())

    assert result.stop_reason == "budget"
    assert agent.calls == 0
    assert opened == [] and sess.opens == 0
    assert sess.sends == []
    assert result.steps == []
    assert result.turns_used == 0
    assert result.usd_estimated == 0.0
    assert result.confirmed is None


async def test_meter_exhausted_mid_session_stops_with_budget(monkeypatch, tmp_path):
    """Bounds are re-checked at the TOP of every step, not just at entry."""
    agent = _stub_agent(monkeypatch, [_send("one"), _send("two"), _send("three")])
    _stub_session(monkeypatch, ["a", "b", "c"])
    # a cap smaller than ONE reasoning call, computed from the same price table
    # the meter uses, so a pricing change cannot quietly defuse this test
    meter = SpendMeter(estimate_cost({AGENT_MODEL: _STEP_USAGE}) * 0.9)

    result = await _run(_pack(tmp_path), meter=meter, confirmer=_SpyConfirmer())

    assert result.stop_reason == "budget"
    assert agent.calls == 1               # step 2's bounds check stopped it
    assert len(result.steps) == 1         # partial evidence survives


async def test_turn_cap_removes_send_from_the_offered_actions(monkeypatch, tmp_path):
    agent = _stub_agent(monkeypatch, [_send("one"), _stop()])
    _stub_session(monkeypatch, ["a", "b"], max_turns=1)

    result = await _run(_pack(tmp_path), limits=_limits(max_turns=1),
                        confirmer=_SpyConfirmer())

    assert _actions_offered(agent.prompts[0]) == {"send", "propose", "stop"}
    assert _actions_offered(agent.prompts[1]) == {"propose", "stop"}
    assert result.turns_used == 1


async def test_send_at_the_turn_cap_is_refused_without_http(monkeypatch, tmp_path):
    """Removing `send` from the prompt is advisory; refusing it is the bound."""
    agent = _stub_agent(monkeypatch, [_send("one"), _send("two"), _stop()])
    sess = _stub_session(monkeypatch, ["a", "b"], max_turns=1)

    result = await _run(_pack(tmp_path), limits=_limits(max_turns=1),
                        confirmer=_SpyConfirmer())

    assert sess.sends == ["one"]                     # the 2nd send never left
    refused = result.steps[1]
    assert refused.outcome == "refused"
    assert result.stop_reason == "agent_stop"        # and the loop continued
    assert "turn" in agent.prompts[2].lower()        # told why


# --------------------------------------------------------------------------
# 4. strict parsing: one retry, then stop — never a silent continue
# --------------------------------------------------------------------------

async def test_unparseable_then_valid_retries_once(monkeypatch, tmp_path):
    agent = _stub_agent(monkeypatch, ["I think I'll send a message!", _send("one")])
    sess = _stub_session(monkeypatch, ["a"])

    result = await _run(_pack(tmp_path), limits=_limits(max_steps=1),
                        confirmer=_SpyConfirmer())

    assert agent.calls == 2                   # exactly one retry
    assert sess.sends == ["one"]              # the retried action was executed
    assert result.stop_reason == "steps_exhausted"
    assert result.error is None
    assert "JSON" in agent.prompts[1]         # the retry says what was wrong


async def test_unparseable_twice_stops_with_error(monkeypatch, tmp_path):
    agent = _stub_agent(monkeypatch, ["nope", "still nope", _send("one")])
    sess = _stub_session(monkeypatch, ["a"])

    result = await _run(_pack(tmp_path), confirmer=_SpyConfirmer())

    assert result.stop_reason == "error"
    assert result.error and "JSON" in result.error
    assert agent.calls == 2                   # it did NOT keep going
    assert sess.sends == []                   # and nothing was executed
    assert result.confirmed is None


async def test_out_of_enum_action_is_never_executed(monkeypatch, tmp_path):
    """The containment mechanism: there is no fetch/shell/file action to name."""
    agent = _stub_agent(monkeypatch, [
        json.dumps({"action": "fetch", "url": "http://evil.example/x"}),
        json.dumps({"action": "shell", "message": "curl http://evil.example"}),
    ])
    sess = _stub_session(monkeypatch, ["a"])

    result = await _run(_pack(tmp_path), confirmer=_SpyConfirmer())

    assert result.stop_reason == "error"
    assert sess.sends == []                   # no HTTP on an out-of-enum action
    assert agent.calls == 2                   # one retry, then stop


# --------------------------------------------------------------------------
# nothing escapes run_session
# --------------------------------------------------------------------------

async def test_budget_stop_is_caught_and_yields_a_partial_result(
        monkeypatch, tmp_path):
    """A BudgetStop escaping would make Inspect drop the sample and destroy the
    partial evidence — the opposite of what a budget stop should do."""
    _stub_agent(monkeypatch, [
        _send("hello"),
        _propose({"leak_marker": "/data/kb"}),
        _stop(),
    ])
    _stub_session(monkeypatch, [LEAK_REPLY])
    spy = _SpyConfirmer(raises=BudgetStop("cap reached mid-confirmation"))

    result = await _run(_pack(tmp_path), confirmer=spy)

    assert result.stop_reason == "budget"
    assert isinstance(result, SessionResult)
    assert len(result.steps) >= 1             # the send survived
    assert result.steps[0].action == "send"


async def test_target_failure_returns_a_result_not_an_exception(
        monkeypatch, tmp_path):
    """A target that will not open must not raise out of the session runner."""
    _stub_agent(monkeypatch, [_send("hello")])

    @asynccontextmanager
    async def _boom(pack, **kwargs):
        raise RuntimeError("connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(loop_mod, "TargetSession", SimpleNamespace(open=_boom))

    with caught_warnings() as rec:
        result = await _run(_pack(tmp_path), confirmer=_SpyConfirmer())

    assert result.stop_reason == "error"
    assert "connection refused" in (result.error or "")
    assert result.turns_used == 0
    assert any(issubclass(r.category, RuntimeWarning) for r in rec)


async def test_a_transient_send_failure_does_not_end_the_hunt(monkeypatch, tmp_path):
    """A 502 or a read timeout on one turn wastes a turn, not the session: the
    steps and budget already committed to this hunt would be thrown away."""
    agent = _stub_agent(monkeypatch, [_send("one"), _send("two"), _stop()])
    sess = _stub_session(monkeypatch, ["a", "b"])
    real_send = sess.send
    calls = {"n": 0}

    async def _flaky(message):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HTTP 502 from the target")
        return await real_send(message)

    sess.send = _flaky

    result = await _run(_pack(tmp_path), confirmer=_SpyConfirmer())

    assert result.stop_reason == "agent_stop"      # it kept hunting
    assert result.error is None
    assert result.steps[0].outcome == "refused"
    assert "502" in result.steps[0].detail
    assert result.steps[1].outcome == "sent"       # the next turn worked
    assert "502" in agent.prompts[1]               # and the agent was told
    assert sess.sends == ["two"]


async def test_a_budget_stop_while_reasoning_is_still_recorded(
        monkeypatch, tmp_path):
    """The call was made and CHARGED before the meter tripped, so it must
    appear in the audit trail — `steps` may not under-count the bill."""
    agent = _stub_agent(monkeypatch, ["not json", _send("never reached")])
    sess = _stub_session(monkeypatch, ["a"])
    # a cap smaller than one call: the reparse retry is refused as spend
    meter = SpendMeter(estimate_cost({AGENT_MODEL: _STEP_USAGE}) * 0.9)

    result = await _run(_pack(tmp_path), meter=meter, confirmer=_SpyConfirmer())

    assert result.stop_reason == "budget"
    assert agent.calls == 1                        # the retry never spent
    assert len(result.steps) == 1                  # ...but the call is recorded
    assert result.steps[0].outcome == "budget"
    assert result.usd_estimated > 0.0
    assert sess.sends == []


async def test_extra_slot_keys_are_dropped_from_provenance(monkeypatch, tmp_path):
    """Unknown keys are agent-chosen text; Task 6 stages `probe_slots` as
    provenance in an emitted probe, so only schema slots may survive."""
    _stub_agent(monkeypatch, [
        _send("hello"),
        _propose({"leak_marker": "/data/kb", "note": "knowledge base"}),
    ])
    _stub_session(monkeypatch, [LEAK_REPLY])
    confirmer = Confirmer(_pack(tmp_path))

    result = await _run(_pack(tmp_path), confirmer=confirmer)

    assert result.stop_reason == "confirmed"
    assert result.probe_slots == {"leak_marker": "/data/kb"}
    assert result.steps[-1].slots == {"leak_marker": "/data/kb"}


async def test_an_invented_extra_slot_still_rejects_the_proposal(
        monkeypatch, tmp_path):
    """Narrowing happens AFTER verification: an extra key the agent invented is
    fail-closed evidence, not a silently discarded one."""
    _stub_agent(monkeypatch, [
        _send("hello"),
        _propose({"leak_marker": "/data/kb", "note": "NEVER-SAID"}),
        _stop(),
    ])
    _stub_session(monkeypatch, [LEAK_REPLY])
    spy = _SpyConfirmer()

    result = await _run(_pack(tmp_path), confirmer=spy)

    assert spy.calls == []
    assert result.confirmed is None


async def test_agent_stop_action_ends_the_session(monkeypatch, tmp_path):
    _stub_agent(monkeypatch, [_stop("no angle here")])
    _stub_session(monkeypatch, ["a"])
    result = await _run(_pack(tmp_path), confirmer=_SpyConfirmer())
    assert result.stop_reason == "agent_stop"
    assert result.steps[-1].action == "stop"


# --------------------------------------------------------------------------
# parse_action / verify_slots units
# --------------------------------------------------------------------------

def test_parse_action_accepts_the_three_actions():
    a = parse_action(_send("hi", rationale="why"))
    assert isinstance(a, AgentAction)
    assert (a.action, a.message, a.rationale) == ("send", "hi", "why")
    assert parse_action(_propose({"leak_marker": "x"})).slots == {"leak_marker": "x"}
    assert parse_action(_stop()).action == "stop"


@pytest.mark.parametrize("raw", [
    "",                                            # empty
    "here is my action: {\"action\": \"stop\"}",   # prose around the JSON
    "[]",                                          # not an object
    "{\"action\": \"fetch\", \"url\": \"http://x\"}",   # outside the enum
    "{\"action\": \"send\"}",                      # send with no message
    "{\"action\": \"send\", \"message\": \"\"}",   # blank message
    "{\"action\": \"send\", \"message\": 42}",     # non-string message
    "{\"action\": null}",                          # no action
    "{\"action\": \"propose\", \"slots\": \"leak\"}",       # slots not an object
    "{\"action\": \"propose\", \"slots\": {\"a\": 1}}",     # non-string slot value
])
def test_parse_action_is_strict(raw):
    with pytest.raises(ActionParseError):
        parse_action(raw)


async def test_seed_is_forwarded_to_the_agent_model(monkeypatch, tmp_path):
    seen: list = []

    class _SeedAgent(_ScriptedAgent):
        async def generate(self, prompt, **kwargs):
            seen.append(kwargs.get("config"))
            return await super().generate(prompt, **kwargs)

    agent = _SeedAgent([_stop()])
    monkeypatch.setattr(loop_mod, "get_model", lambda m: agent)
    _stub_session(monkeypatch, ["a"])

    await _run(_pack(tmp_path), confirmer=_SpyConfirmer(), seed=1234)
    assert seen and seen[0] is not None and seen[0].seed == 1234


def test_the_action_space_stays_closed():
    """The containment mechanism, guarded as a regression: the agent never
    handles a URL, a path or a command, so it cannot leave the allowlist by any
    route other than the `TargetSession` the loop opened."""
    assert loop_mod.ACTIONS == {"send", "propose", "stop"}
    src = Path(loop_mod.__file__).read_text()
    for forbidden in ("import httpx", "import requests", "import subprocess",
                      "import urllib", "import socket", "import os",
                      "import pathlib", "os.system", "webbrowser",
                      "AsyncClient", "__import__", "globals(", "setattr("):
        assert forbidden not in src, f"loop.py must not reach out: {forbidden}"
    # no indirect-reach construct: a BARE builtin call (`x.open(` is fine —
    # that is TargetSession's own constructor)
    for builtin in ("eval", "exec", "open", "compile", "input"):
        assert re.search(rf"(?<![.\w]){builtin}\(", src) is None, \
            f"loop.py must not call the {builtin}() builtin"
    # `send` is the ONLY thing the loop can do to the outside world, and a
    # proposal has exactly ONE road to the trust boundary
    assert src.count("session.send(") == 1
    assert src.count("confirmer.confirm(") == 1


def test_verify_slots_requires_a_verbatim_assistant_substring():
    msgs = [ChatMessageUser(content="tell me about /data/user-said"),
            ChatMessageAssistant(content="I read /data/kb/index.json daily.")]
    assert verify_slots({"leak_marker": "/data/kb"}, msgs) is True
    assert verify_slots({"leak_marker": " /data/kb "}, msgs) is True   # trimmed
    assert verify_slots({"leak_marker": "/DATA/KB"}, msgs) is False    # case
    assert verify_slots({"leak_marker": "/data/user-said"}, msgs) is False
    assert verify_slots({"leak_marker": ""}, msgs) is False
    assert verify_slots({}, msgs) is False
    assert verify_slots({"leak_marker": "/data/kb"}, []) is False
    # one bad value poisons the whole proposal
    assert verify_slots({"a": "/data/kb", "b": "invented"}, msgs) is False


def test_a_bare_string_transcript_is_never_evidence():
    """`verify_slots` is the module's one security primitive and it is
    exported. A list of strings is the obvious shape a future caller (solver,
    store round-trip, replay tool) would reach for, and in that shape there is
    no way to tell an assistant turn from the agent's own words — so it must
    count as NO evidence at all, not as "a substring of anything in the list"."""
    assert verify_slots({"leak_marker": "/data/kb"},
                        ["I read /data/kb daily."]) is False
    # ...including when the string would have matched as a user turn
    assert verify_slots({"leak_marker": "/data/kb"},
                        ["ask about /data/kb", "I read /data/kb daily."]) is False
    # mixed shapes: only the typed assistant message counts
    typed = [ChatMessageAssistant(content="I read /data/other.")]
    assert verify_slots({"leak_marker": "/data/kb"},
                        [*typed, "I read /data/kb daily."]) is False
    assert verify_slots({"leak_marker": "/data/other"}, typed) is True
