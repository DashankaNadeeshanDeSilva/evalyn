from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator

CheckType = Literal["invariant", "classifier", "contains", "not_contains", "rubric"]


class Check(BaseModel):
    type: CheckType
    ref: str | None = None          # for type=invariant: which invariant id
    question: str | None = None     # for type=classifier
    expect: bool | None = None      # for type=classifier
    value: str | None = None        # for type=contains/not_contains
    rubric: str | None = Field(
        default=None,
        description="for type=rubric: rubric id (file stem under <pack>/rubrics/)")
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


_EVENT_FORMATS = {"vercel-ai", "raw-sse", "named-sse", "json"}


class SessionEndpoint(BaseModel):
    method: str
    path: str
    stream: str | None = None       # "sse" | None
    event_format: str = "json"      # one of _EVENT_FORMATS
    event_name: str | None = None       # named-sse: which event carries content
    content_field: str | None = None    # named-sse: which JSON field holds the token
    open_body: dict = Field(default_factory=dict)      # body for the open request
    session_id_field: str = "session_id"               # response field holding the id
    message_field: str = "message"                     # request field for the user text
    session_field: str = "session_id"                  # request field for the session id

    @field_validator("event_format")
    @classmethod
    def _known_format(cls, v):
        if v not in _EVENT_FORMATS:
            raise ValueError(f"event_format {v!r} not in {sorted(_EVENT_FORMATS)}")
        return v


class AuthSpec(BaseModel):
    kind: Literal["none", "bearer", "header"] = "none"
    token: str | None = None
    header_name: str | None = None


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
    """Run budget caps."""

    max_usd_per_run: float = Field(
        default=5.0,
        description="Declarative only: parsed but not yet enforced (Plan #2).")
    max_turns_per_session: int = Field(
        default=12,
        description="Enforced by the session solver: a probe with more turns "
                    "than this cap fails loudly (RuntimeError) before any HTTP.")


class JudgeSpec(BaseModel):
    """Tier-3 rubric-judge configuration. Judge != generator family by default
    (self-preference bias); a family match is a warning, never an error."""

    rubric_model: str = "anthropic/claude-3-5-sonnet-latest"
    generator_family: str | None = Field(
        default=None,
        description="Model family of the TARGET's generator (e.g. 'openai') — "
                    "used only to warn when the rubric judge is the same family.")


class TargetSpec(BaseModel):
    name: str
    description: str = ""
    sessions: dict[str, SessionEndpoint]
    auth: AuthSpec = Field(default_factory=AuthSpec)
    env: dict[str, str] = Field(default_factory=dict)
    allowlist: list[str]
    invariants: list[Invariant] = Field(default_factory=list)
    state: StateSpec | None = None
    budget: Budget = Field(default_factory=Budget)
    judge: JudgeSpec = Field(default_factory=JudgeSpec)
    concurrency: int = 4
