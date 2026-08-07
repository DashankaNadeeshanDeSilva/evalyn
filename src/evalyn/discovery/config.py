"""Run configuration for `discover`, and the limit-resolution safety boundary.

`resolve_limits` is the one place a CLI flag meets a pack cap. The rule it
enforces is a safety boundary, not a preference: **the pack's caps are
authoritative and clamp DOWNWARD only.** A run may always ask for less than the
pack allows; it may never buy itself more. That holds for both the USD ceiling
and the per-session turn cap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from evalyn.discovery.objectives import OBJECTIVES
from evalyn.targets.loader import Pack

#: Steps per session and sessions per run have no pack-level cap — they cost
#: nothing but time, and the USD ceiling is the real bound.
DEFAULT_MAX_STEPS = 8
DEFAULT_MAX_SESSIONS = 4
#: Used ONLY when the pack disables its own cap (`max_usd_per_run: 0`) and the
#: operator named no ceiling either. An autonomous agent is never turned loose
#: on an unbounded budget; this mirrors the schema's own Budget default.
DEFAULT_MAX_USD = 5.0

DEFAULT_AGENT_MODEL = "openai/gpt-5-mini"
DEFAULT_JUDGE_MODEL = "mockllm/model"


@dataclass(frozen=True)
class Limits:
    """Resolved bounds for one `discover` run. Every field is final."""

    max_steps: int
    max_sessions: int
    max_usd: float
    max_turns: int  # per session; the pack's cap, or lower


@dataclass(frozen=True)
class CliLimits:
    """What the operator asked for. `None` = "not specified, use the default"."""

    max_steps: int | None = None
    max_sessions: int | None = None
    max_usd: float | None = None
    max_turns: int | None = None


def _positive(name: str, value: int | None) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")


def resolve_limits(pack: Pack, cli_limits: CliLimits | None = None) -> Limits:
    """Combine operator request with pack caps. Pack caps clamp downward only."""
    cli = cli_limits or CliLimits()
    _positive("max_steps", cli.max_steps)
    _positive("max_sessions", cli.max_sessions)
    _positive("max_turns", cli.max_turns)
    if cli.max_usd is not None and cli.max_usd < 0:
        raise ValueError(f"max_usd must be >= 0, got {cli.max_usd}")

    budget = pack.spec.budget
    if budget.max_usd_per_run > 0:
        # min(), never the CLI value alone: a flag above the cap is clamped.
        max_usd = (budget.max_usd_per_run if cli.max_usd is None
                   else min(cli.max_usd, budget.max_usd_per_run))
    else:
        # 0 disables the pack's cap (schema semantics), so there is no ceiling
        # to clamp against and the operator's value stands.
        max_usd = DEFAULT_MAX_USD if cli.max_usd is None else cli.max_usd

    pack_turns = budget.max_turns_per_session
    max_turns = pack_turns if cli.max_turns is None else min(cli.max_turns, pack_turns)

    return Limits(
        max_steps=DEFAULT_MAX_STEPS if cli.max_steps is None else cli.max_steps,
        max_sessions=DEFAULT_MAX_SESSIONS if cli.max_sessions is None else cli.max_sessions,
        max_usd=max_usd,
        max_turns=max_turns,
    )


@dataclass(frozen=True)
class DiscoveryConfig:
    """Everything one `discover` run needs, resolved and immutable."""

    limits: Limits
    #: Objective ids to hunt, in order. Ids (not `Objective`s) so the run
    #: artifact serialises cleanly.
    objectives: tuple[str, ...] = field(default_factory=lambda: tuple(OBJECTIVES))
    persona: str | None = None
    playbook: str | None = None
    agent_model: str = DEFAULT_AGENT_MODEL
    judge_model: str = DEFAULT_JUDGE_MODEL
    rubric_judge_model: str | None = None
    #: `None` = the pack's own `discoveries/` staging dir.
    staging_dir: Path | None = None
    out_dir: Path = Path("runs")
    seed: int | None = None
    replay: bool = True

    def __post_init__(self) -> None:
        if not self.objectives:
            raise ValueError("no objectives selected — nothing to hunt")
        unknown = [o for o in self.objectives if o not in OBJECTIVES]
        if unknown:
            raise ValueError(
                f"unknown objective(s): {', '.join(unknown)} — "
                f"known: {', '.join(OBJECTIVES)}")
