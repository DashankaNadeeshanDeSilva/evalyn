"""Characterization tests for TargetSession (Plan #3 Task 0).

TargetSession is the target driver session_solver already uses, lifted out of
its closures so discover can reuse the SAME open/send/turn-cap/SSE-parse path.
These tests pin the extracted behavior against the same bundled toy target the
solver tests drive.
"""
from pathlib import Path

import pytest

from evalyn.targets.loader import AllowlistError, Pack, load_pack
from evalyn.targets.schema import TargetSpec
from evalyn.targets.session import TargetSession, TurnCapExceeded

MINIPACK = Path(__file__).parent.parent / "fixtures" / "minipack"


@pytest.mark.asyncio
async def test_open_send_drives_toy_target(toy_target, monkeypatch):
    """open -> send returns the target's reply; the session records the turn."""
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(MINIPACK)
    async with TargetSession.open(pack) as session:
        reply = await session.send("Where did you work?")
        assert "Acme" in reply
        assert session.turns_used == 1
        assert [m.role for m in session.messages] == ["user", "assistant"]
        assert session.messages[0].text == "Where did you work?"
        assert session.messages[1].text == reply
    assert session.elapsed_seconds > 0


@pytest.mark.asyncio
async def test_open_refuses_non_allowlisted_base_url(monkeypatch):
    """Containment: open() forms its URL via resolve_base_url, so a base_url
    outside the pack allowlist can never produce a session."""
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://evil.example")
    pack = load_pack(MINIPACK)
    with pytest.raises(AllowlistError):
        async with TargetSession.open(pack):
            pytest.fail("session opened against a non-allowlisted base_url")


def _capped_pack(url: str, max_turns: int) -> Pack:
    spec = TargetSpec.model_validate({
        "name": "t",
        "sessions": {
            "open": {"method": "POST", "path": "/session"},
            "message": {"method": "POST", "path": "/chat", "stream": "sse",
                        "event_format": "vercel-ai"},
        },
        "auth": {"kind": "none"},
        "env": {"base_url": url},
        "allowlist": [url],
        "budget": {"max_turns_per_session": max_turns},
    })
    return Pack(spec=spec, probes=[], root=Path("."))


@pytest.mark.asyncio
async def test_send_past_turn_cap_raises_turn_cap_exceeded(toy_target):
    """send() at the pack's max_turns_per_session cap fails loudly BEFORE any
    HTTP for that turn -- never a silent extra turn."""
    pack = _capped_pack(toy_target, max_turns=1)
    async with TargetSession.open(pack) as session:
        reply = await session.send("hi")
        assert isinstance(reply, str) and reply
        with pytest.raises(TurnCapExceeded, match="max_turns_per_session=1"):
            await session.send("hi again")
    assert session.turns_used == 1
