from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

CheckType = Literal["invariant", "classifier", "contains", "not_contains"]


class Check(BaseModel):
    type: CheckType
    ref: str | None = None          # for type=invariant: which invariant id
    question: str | None = None     # for type=classifier
    expect: bool | None = None      # for type=classifier
    value: str | None = None        # for type=contains/not_contains
    required: bool = Field(
        default=False,
        description="required -> hard pass/fail. The non-required semantics "
                    "(contribute a weighted score instead of gating) are not yet "
                    "implemented — that consumer arrives in Plan #2.")
    weight: float = Field(
        default=1.0,
        description="Declarative only: parsed and validated but not yet used in "
                    "scoring — the weighted/non-required scoring consumer arrives "
                    "in Plan #2. Today every check scores with equal weight.")


class Probe(BaseModel):
    id: str
    category: str
    kind: Literal["regression", "capability"] = "regression"
    safety_critical: bool = False
    turns: list[str]
    checks: list[Check]
    samples: int = Field(default=1, ge=1)
    reference: str | None = None    # known-good reply, proves solvability (validate-pack)


class SessionEndpoint(BaseModel):
    method: str
    path: str
    stream: str | None = None       # "sse" | None
    event_format: str = "json"      # "vercel-ai" | "raw-sse" | "json"


class StateCheck(BaseModel):
    id: str
    request: dict
    expect: dict


class StateSpec(BaseModel):
    checks: list[StateCheck] = Field(default_factory=list)
    seed_fingerprint: dict | None = None
    reset: dict | None = None


class Invariant(BaseModel):
    id: str


class Budget(BaseModel):
    """Run budget caps. Declarative only for now: both fields are parsed and
    validated but not yet enforced anywhere — the enforcement consumers arrive
    in Plan #2. Declared caps do not stop or bound a run today."""

    max_usd_per_run: float = Field(
        default=5.0,
        description="Declarative only: parsed but not yet enforced (Plan #2).")
    max_turns_per_session: int = Field(
        default=12,
        description="Declarative only: parsed but not yet enforced (Plan #2).")


class TargetSpec(BaseModel):
    name: str
    description: str = ""
    sessions: dict[str, SessionEndpoint]
    auth: dict = Field(default_factory=lambda: {"kind": "none"})
    env: dict[str, str] = Field(default_factory=dict)
    allowlist: list[str]
    invariants: list[Invariant] = Field(default_factory=list)
    state: StateSpec | None = None
    budget: Budget = Field(default_factory=Budget)
    concurrency: int = 4
