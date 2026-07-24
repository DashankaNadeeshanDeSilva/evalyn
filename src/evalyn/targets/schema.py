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
    values: list[str] | None = Field(
        default=None,
        description="contains only: multi-value OR form — the check passes if ANY "
                    "listed string is present. Mutually exclusive with `value` "
                    "(static validation of the exclusivity arrives in Task 9). "
                    "not_contains does not accept `values`.")
    scope: Literal["final", "any_turn", "all_turns"] | None = Field(
        default=None,
        description="Transcript scope override. final = evaluate against the last "
                    "assistant turn only; any_turn = existential PASS: passes if ANY "
                    "assistant turn satisfies the check; all_turns = universal: must "
                    "hold on EVERY assistant turn (any violating turn fails it). "
                    "Defaults when unset: invariant/not_contains -> all_turns "
                    "(fail-closed, every turn scanned); contains -> final.")
    required: bool = Field(
        default=False,
        description="required -> gates the trial: the trial's binary verdict "
                    "(feeding pass@k/pass^k) passes only if EVERY required check "
                    "passes, and any required failure zeroes the trial score. "
                    "non-required -> contributes to the weighted trial score "
                    "instead of gating.")
    weight: float = Field(
        default=1.0,
        description="Weight in the non-required weighted mean: trial_score = "
                    "sum(w_i * score_i) / sum(w_i) over non-required checks "
                    "(unsure checks excluded from both sums). Ignored for "
                    "required checks — they gate rather than weigh.")


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
