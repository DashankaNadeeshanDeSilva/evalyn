"""Run configuration and the limit-resolution safety boundary.

`resolve_limits` is the one place where a CLI flag meets a pack cap. The rule
it enforces is not a preference: the pack's caps are authoritative and clamp
DOWNWARD only. A run may always ask for less; it may never buy itself more.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from evalyn.discovery.config import (
    DEFAULT_MAX_SESSIONS,
    DEFAULT_MAX_STEPS,
    DEFAULT_MAX_USD,
    CliLimits,
    DiscoveryConfig,
    Limits,
    resolve_limits,
)
from evalyn.targets.loader import Pack
from evalyn.targets.schema import TargetSpec


def make_pack(*, max_usd: float = 1.0, max_turns: int = 6) -> Pack:
    spec = TargetSpec.model_validate({
        "name": "t",
        "sessions": {
            "open": {"method": "POST", "path": "/session"},
            "message": {"method": "POST", "path": "/chat"},
        },
        "allowlist": ["http://localhost:8899"],
        "budget": {"max_usd_per_run": max_usd, "max_turns_per_session": max_turns},
    })
    return Pack(spec=spec, probes=[], root=Path("."))


def test_resolve_limits_clamps_down():
    """A --max-usd above the pack cap is clamped to the cap; below it stands."""
    pack = make_pack(max_usd=1.0)
    assert resolve_limits(pack, CliLimits(max_usd=10.0)).max_usd == 1.0
    assert resolve_limits(pack, CliLimits(max_usd=0.25)).max_usd == 0.25


def test_resolve_limits_turn_cap_is_never_raised():
    pack = make_pack(max_turns=6)
    assert resolve_limits(pack, CliLimits(max_turns=99)).max_turns == 6
    assert resolve_limits(pack, CliLimits(max_turns=2)).max_turns == 2


def test_resolve_limits_defaults_to_the_pack_caps():
    pack = make_pack(max_usd=1.0, max_turns=6)
    limits = resolve_limits(pack)
    assert limits.max_usd == 1.0
    assert limits.max_turns == 6
    assert limits.max_steps == DEFAULT_MAX_STEPS
    assert limits.max_sessions == DEFAULT_MAX_SESSIONS


def test_resolve_limits_honours_step_and_session_caps():
    """Steps and sessions have no pack cap — they are purely the operator's."""
    limits = resolve_limits(make_pack(), CliLimits(max_steps=3, max_sessions=1))
    assert limits.max_steps == 3
    assert limits.max_sessions == 1


def test_resolve_limits_rejects_non_positive_bounds():
    for cli in (CliLimits(max_steps=0), CliLimits(max_sessions=0),
                CliLimits(max_turns=0), CliLimits(max_usd=-1.0)):
        with pytest.raises(ValueError):
            resolve_limits(make_pack(), cli)


def test_a_disabled_pack_usd_cap_still_leaves_a_ceiling():
    """`max_usd_per_run: 0` means "no pack ceiling" (schema semantics), so the
    CLI value stands — and with no CLI value we fall back to a finite default
    rather than turning an autonomous agent loose on an unbounded budget."""
    pack = make_pack(max_usd=0.0)
    assert resolve_limits(pack, CliLimits(max_usd=25.0)).max_usd == 25.0
    assert resolve_limits(pack).max_usd == DEFAULT_MAX_USD


def test_limits_is_frozen():
    limits = resolve_limits(make_pack())
    with pytest.raises(dataclasses.FrozenInstanceError):
        limits.max_usd = 999.0


def test_discovery_config_is_frozen():
    cfg = DiscoveryConfig(limits=resolve_limits(make_pack()))
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.agent_model = "openai/gpt-5"


def test_discovery_config_defaults():
    cfg = DiscoveryConfig(limits=resolve_limits(make_pack()))
    assert set(cfg.objectives) == {
        "prompt-injection-bypass", "pii-leak", "persona-break", "hallucination"}
    assert cfg.agent_model == "openai/gpt-5-mini"
    assert cfg.replay is True
    assert isinstance(cfg.limits, Limits)


def test_discovery_config_rejects_an_unknown_objective():
    with pytest.raises(ValueError, match="nope"):
        DiscoveryConfig(limits=resolve_limits(make_pack()), objectives=("nope",))


def test_discovery_config_rejects_an_empty_objective_set():
    with pytest.raises(ValueError):
        DiscoveryConfig(limits=resolve_limits(make_pack()), objectives=())
