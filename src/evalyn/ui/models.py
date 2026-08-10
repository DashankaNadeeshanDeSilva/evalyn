"""The frozen cockpit API contract (Plan #4, Task 1) — the parallelism seam.

This module is a **separate API layer** over the three artifact dataclasses
(`RunArtifact`/`ProbeResult`, `CompareArtifact`, `DiscoveryArtifact`/`Finding`).
It does not replace them and nothing here is written to disk: the dataclasses
own the on-disk schema, these models own the wire. The two are allowed to
diverge — the wire adds `run_id`, `degraded`, `capabilities` and drops
`log_path` detail — and the mapping between them lives in `ui/index.py`.

Three rules make this a contract rather than a suggestion:

* **`extra="forbid"` everywhere** (R4-5). A later task that adds a response
  field without updating this module — and therefore `ui/src/api/types.ts` —
  fails loudly instead of drifting.
* **Closed enums, asserted as exact member sets** by `tests/ui/test_models.py`.
  Widening one is a deliberate, visible edit on both sides of the wire.
* **No `fastapi` / `starlette` import.** `evalyn.cli` reaches into
  `evalyn.ui` lazily; a web-framework import at this level would break the
  measured import-isolation baseline (`import evalyn.cli` loads neither
  fastapi nor uvicorn).

Two conventions the SPA depends on and must not be re-derived:

* **Absent vs null.** Affordances are disabled off `Capabilities`, never off
  the truthiness of a value. A `null` metric means "this run cannot tell you",
  which is not the same as `0.0`.
* **Degradation, not failure.** Every list row validates. An unreadable
  artifact still yields a `RunSummary` with `degraded=True`, a
  `degraded_reason`, null metrics, and a real `run_id` / `created_at` / `mode`
  (all three are recoverable from the filename alone).
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

__all__ = [
    # grammar + constants
    "RUN_ID_PATTERN", "RUN_ID_RE", "RunId", "is_run_id",
    "REDACTION_MARKER_RE", "redaction_marker", "HEARTBEAT_SECONDS",
    "CURSOR_SEPARATOR", "make_cursor", "parse_cursor",
    # enums
    "RunMode", "RunStatus", "ErrorCode", "VerdictTier", "VerdictHint",
    "ControlAction", "ReplayStatus", "TurnRole", "TrendMetric", "EventName",
    # errors
    "ApiError", "ErrorEnvelope",
    # runs
    "Capabilities", "CheckView", "TranscriptTurn", "ProbeRow", "RunSummary",
    "RunDetail", "DiscoverySummary", "RunListPage", "TrialView", "GateVerdict",
    # discover
    "ReplayView", "FindingRow", "FindingDetail",
    # compare + trends + trust
    "CategoryTally", "HardMetrics", "Scoreboard",
    "TrendPoint", "TrendSeries", "CriterionCounts", "TrustReport",
    # write side
    "LaunchRequest", "ControlRequest",
    # server meta
    "RedactionMeta", "MetaResponse", "HealthResponse",
]


# --------------------------------------------------------------------------
# 1. `run_id` grammar — a path SEGMENT, never a path
# --------------------------------------------------------------------------

#: Canonical id: `<stamp><micros?>-<uuid8>-<slug>`, i.e. an artifact filename
#: with `.json` and any mode suffix still attached to the slug but the
#: directory stripped. The `\d{0,6}` tail keeps the pre-microsecond stamps
#: readable, and the trailing alternative is the documented relaxation for the
#: legacy `20260723T080347-example` form that has no uuid segment at all.
#:
#: Path traversal is excluded **by construction**: the character class admits
#: no `/`, so a value that validates here is always safe to join onto `runs/`.
#: Task 2's `ui.paths.RUN_ID_RE` must be this same pattern — import it, do not
#: retype it, and use `is_run_id` rather than the bare regex.
RUN_ID_PATTERN = (
    r"^(?:\d{8}T\d{6}\d{0,6}-[0-9a-f]{8}-[A-Za-z0-9._-]+"
    r"|\d{8}T\d{6}-[A-Za-z0-9._-]+)$"
)
RUN_ID_RE = re.compile(RUN_ID_PATTERN)


def _not_a_filename(value: str) -> str:
    """Reject a *filename* handed in where an id belongs.

    `.` is legal inside a slug (pack names keep it), so `…-example.json`
    matches `RUN_ID_PATTERN` and the server would then go looking for
    `…-example.json.json`. This lives outside the pattern rather than as a
    `(?<!\\.json)$` lookbehind because pydantic v2 validates patterns with the
    Rust regex engine, which supports no look-around at all.
    """
    if value.endswith(".json"):
        raise ValueError("run_id is an artifact stem, not a filename "
                         "(drop the .json suffix)")
    return value


RunId = Annotated[
    str,
    StringConstraints(pattern=RUN_ID_PATTERN, max_length=255),
    AfterValidator(_not_a_filename),
]


def is_run_id(value: str) -> bool:
    """The single authority on whether a string is a run id.

    `RunIndex` uses this to exclude `baseline.json`, `logs/` and anything else
    a hostile `runs/` directory contains, without opening a single file.

    **`fullmatch`, never `match`.** Python's `$` also matches immediately
    before a trailing newline, so `RUN_ID_RE.match("…-example\\n")` succeeds —
    but pydantic compiles the same pattern with the Rust regex engine, whose
    `$` anchors to the end of the haystack only. `match` therefore made this
    predicate *more permissive than the `RunId` type it speaks for*: the index
    would admit a filename, and building the row from it would then raise. This
    function and `RunId` must accept exactly the same set of strings, and
    `tests/ui/test_models.py::test_is_run_id_and_the_RunId_type_never_disagree`
    holds them to it.
    """
    return bool(RUN_ID_RE.fullmatch(value)) and not value.endswith(".json")


# --------------------------------------------------------------------------
# 2. Redaction marker — ONE format, no second (spec §7 item 6)
# --------------------------------------------------------------------------

REDACTION_MARKER_RE = re.compile(r"«redacted:[a-z_]+»")


def redaction_marker(kind: str) -> str:
    """The only way a redacted value is ever spelled. `kind` is `[a-z_]+`."""
    if not re.fullmatch(r"[a-z_]+", kind):
        raise ValueError(f"redaction kind must match [a-z_]+, got {kind!r}")
    return f"«redacted:{kind}»"


#: The SSE stream emits a `heartbeat` comment at this cadence so an idle run
#: does not look like a dead connection to a proxy or to the browser.
HEARTBEAT_SECONDS = 15.0


# --------------------------------------------------------------------------
# 2b. Pagination cursor — opaque, and tie-safe by construction
# --------------------------------------------------------------------------

#: Legal in neither half: `run_id`'s character class excludes it, and an
#: ISO-8601 stamp cannot contain it. So one `split` is unambiguous.
CURSOR_SEPARATOR = "|"


def make_cursor(created_at: str, run_id: str) -> str:
    """Build the `next_cursor` for a page whose last row is `(created_at, run_id)`.

    Keyed on `created_at` alone the cursor is **not** unique: two artifacts
    written inside the same second share a timestamp, and `?before=<stamp>`
    then either repeats the tied row on the next page or drops it, depending on
    whether the comparison is strict. Appending `run_id` gives
    `(created_at, run_id)` a total order over the corpus, so exactly one row
    sits either side of any cursor.
    """
    if CURSOR_SEPARATOR in run_id:
        raise ValueError(f"run_id may not contain {CURSOR_SEPARATOR!r}: {run_id!r}")
    return f"{created_at}{CURSOR_SEPARATOR}{run_id}"


def parse_cursor(cursor: str) -> tuple[str, str]:
    """Split a cursor back into its `(created_at, run_id)` sort key.

    The returned tuple **is** the ordering key: list rows are sorted by it
    descending, and `?before=<cursor>` keeps rows whose key is strictly less.
    Compare the parsed tuples, never the cursor strings — one `created_at` can
    be a prefix of another (`…:44+00:00` vs `…:44.5+00:00`), and the separator
    sorts after the characters that would have decided it, so a lexicographic
    comparison of the joined form can invert the intended order.
    """
    head, sep, tail = cursor.partition(CURSOR_SEPARATOR)
    if not sep:
        raise ValueError(
            "cursor must be the opaque composite "
            f"'<created_at>{CURSOR_SEPARATOR}<run_id>', got {cursor!r} — a bare "
            "timestamp is not tie-safe"
        )
    return head, tail


# --------------------------------------------------------------------------
# 3. Enums — closed sets, `str`-valued so JSON and the TS union agree
# --------------------------------------------------------------------------

class RunMode(str, Enum):
    """Classified **lexically** from the filename suffix — never by opening it."""

    gate = "gate"
    compare = "compare"
    discover = "discover"


class RunStatus(str, Enum):
    """Nine states, and the distinctions are load-bearing.

    `invalid` is a run that completed but whose results mean nothing (a failed
    eval, zero trials); `unreadable` is an artifact this build cannot parse —
    the run may have been perfectly fine. `interrupted` is a process that
    vanished without writing an artifact; `failed_to_start` never got that far.
    """

    passed = "passed"
    gate_failed = "gate_failed"
    invalid = "invalid"
    running = "running"
    paused = "paused"
    cancelled = "cancelled"
    interrupted = "interrupted"
    failed_to_start = "failed_to_start"
    unreadable = "unreadable"


class ErrorCode(str, Enum):
    """Every non-2xx body is `{"error": {...}}` with a code from this set."""

    not_found = "not_found"
    unreadable_artifact = "unreadable_artifact"
    pack_error = "pack_error"
    launch_refused = "launch_refused"
    busy = "busy"


class VerdictTier(str, Enum):
    """Which scoring tier decided a check. `abstained` is not tier 0."""

    tier_1 = "1"
    tier_2 = "2"
    tier_3 = "3"
    abstained = "abstained"


class VerdictHint(str, Enum):
    """An **approximation** carried by list rows.

    Computed from `probes[]` alone so the list never calls `evaluate_gate`
    (which reads a baseline and renders markdown). The authoritative verdict
    comes from `GET /api/runs/{id}/gate`. Never render this without saying so.
    """

    passed = "passed"
    failed = "failed"
    unknown = "unknown"


class ControlAction(str, Enum):
    pause = "pause"
    resume = "resume"
    cancel = "cancel"


class ReplayStatus(str, Enum):
    """`ReplayResult` and `ReplaySkipped` flattened into four states.

    A replay that ran and did not reproduce (`not_reproduced`) is a different
    claim from one that never ran; and a budget skip (the run is `partial`)
    is different from `--no-replay` (nothing was involuntarily truncated).
    """

    reproduced = "reproduced"
    not_reproduced = "not_reproduced"
    skipped_budget = "skipped_budget"
    skipped_disabled = "skipped_disabled"


class TurnRole(str, Enum):
    user = "user"
    assistant = "assistant"


class TrendMetric(str, Enum):
    mean_score = "mean_score"
    pass_k = "pass_k"
    pass_at_k = "pass_at_k"
    judge_usd = "judge_usd"


class EventName(str, Enum):
    """The SSE `event:` names (spec §7 item 8).

    Mirrors the emit sites the event sink instruments, plus the three control
    acks and the heartbeat. The SPA switches on this; an unknown name is
    ignored rather than fatal, but it must not be *emitted* without landing
    here first.
    """

    run_started = "run.started"
    spend_updated = "spend.updated"
    artifact_written = "artifact.written"
    run_finished = "run.finished"
    trial_started = "trial.started"
    turn_sent = "turn.sent"
    turn_received = "turn.received"
    trial_finished = "trial.finished"
    probe_scored = "probe.scored"
    pair_judged = "pair.judged"
    agent_step = "agent.step"
    agent_reply = "agent.reply"
    confirm_result = "confirm.result"
    finding_staged = "finding.staged"
    replay_result = "replay.result"
    control_paused = "control.paused"
    control_resumed = "control.resumed"
    control_cancelled = "control.cancelled"
    heartbeat = "heartbeat"


# --------------------------------------------------------------------------
# 4. Base
# --------------------------------------------------------------------------

class _Model(BaseModel):
    """Every wire model forbids extra keys (R4-5)."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# 5. Error envelope (spec §7 item 3)
# --------------------------------------------------------------------------

class ApiError(_Model):
    code: ErrorCode
    message: str
    #: Operator-facing extra context. Already redaction-scrubbed like any body.
    detail: str | None = None


class ErrorEnvelope(_Model):
    """The body of **every** non-2xx response. Never a bare `{"detail": …}`."""

    error: ApiError


# --------------------------------------------------------------------------
# 6. Runs
# --------------------------------------------------------------------------

class Capabilities(_Model):
    """What this artifact can actually answer (spec §7 item 5).

    The SPA disables affordances off these booleans, never off truthiness — a
    pre-#2b run has no `trial_records`, and an empty transcript list must read
    as "not captured", not "the conversation was empty".
    """

    #: Any `trial_records[].transcript` is non-empty — the drill-down works.
    transcripts: bool
    #: `trial_records` is present and non-empty for at least one probe.
    trial_records: bool
    #: Latency / invariant-failure aggregates are available (compare artifacts,
    #: or gate artifacts whose trial records carry `session_seconds`).
    hard_metrics: bool


class CheckView(_Model):
    """One `CheckResult` as scored. Mirrors the artifact's check dicts."""

    check: str
    tier: int
    required: bool
    weight: float
    #: `None` when the check abstained (see `unsure`) — not `False`.
    passed: bool | None = None
    score: float | None = None
    #: 1-based turn index the evidence came from; `None` for whole-session checks.
    turn: int | None = None
    evidence: str = ""
    unsure: bool = False
    #: True when `evidence` passed through the redactor.
    redacted: bool = False


class TranscriptTurn(_Model):
    role: TurnRole
    text: str
    redacted: bool = False


class ProbeRow(_Model):
    """One `ProbeResult` on the wire."""

    id: str
    category: str
    kind: str
    safety_critical: bool
    samples: int
    trials: int
    #: 0 means "unknown" on a pre-round-2 artifact — the gate skips its
    #: incompleteness check in that case, so do not render it as "0 expected".
    expected_trials: int = 0
    pass_at_k: float | None = None
    pass_k: float | None = None
    mean_score: float | None = None
    unsure_trials: int = 0
    checks: list[CheckView] = []
    #: Epochs that have a trial record, i.e. the drill-downs that exist. Empty
    #: means the row's drill-down is disabled, never that the run had no trials.
    trial_epochs: list[int] = []


class RunSummary(_Model):
    """One row of `GET /api/runs`. Cheap by construction: no `evaluate_gate`,
    no `.eval` log read, and on the empty-filter path no file open at all
    beyond the artifact itself."""

    run_id: RunId
    mode: RunMode
    #: `None` only when even the salvage read failed (unparseable JSON).
    pack_name: str | None = None
    #: ISO-8601 UTC **verbatim** from the artifact, or recovered from the
    #: filename stamp when the body is unreadable. The SPA formats; the server
    #: never does.
    created_at: str
    status: RunStatus
    degraded: bool = False
    #: Human-readable, shown as the greyed row's tooltip. Required when
    #: `degraded` — a greyed row with no explanation is the failure mode this
    #: field exists to prevent.
    degraded_reason: str | None = None
    capabilities: Capabilities
    #: Evalyn's OWN judge spend. `None` = not recorded, never `0.0`.
    judge_usd: float | None = None
    verdict_hint: VerdictHint | None = None

    @model_validator(mode="after")
    def _degraded_rows_explain_themselves(self) -> "RunSummary":
        if self.degraded and not self.degraded_reason:
            raise ValueError("degraded_reason is required when degraded is True")
        return self


class GateVerdict(_Model):
    """`GET /api/runs/{id}/gate` — the real `evaluate_gate`, called lazily."""

    run_id: RunId
    exit_code: int
    failures: list[str] = []
    quarantined: list[str] = []
    report_md: str = ""
    #: Which baseline it diffed against; `None` = no baseline was available,
    #: which makes the capability checks advisory.
    baseline_run_id: str | None = None


class RunDetail(RunSummary):
    """`GET /api/runs/{id}`. A superset of the row, so the SPA can render the
    detail page from a warm cache entry without a shape change."""

    pack_hash: str | None = None
    judge_model: str | None = None
    #: Path as recorded, home directories scrubbed by the redactor.
    log_path: str | None = None
    rubric_scores_untrusted: bool = False
    total_unsure_trials: int | None = None
    cancelled: bool = False
    probes: list[ProbeRow] = []
    #: Populated for `mode == compare` only.
    compare: "Scoreboard | None" = None
    #: Populated for `mode == discover` only.
    discovery: "DiscoverySummary | None" = None


class DiscoverySummary(_Model):
    """The `discover`-specific half of a `RunDetail`.

    `eval_status` is here because every counter goes to zero when the eval
    itself failed: without it a run that never looked is byte-identical to a
    run that looked and found nothing.
    """

    agent_model: str | None = None
    rubric_judge_model: str | None = None
    eval_status: str = "success"
    error_count: int = 0
    sessions_total: int = 0
    confirmed_count: int = 0
    live_spend_usd: float | None = None
    reconciled_spend_usd: float | None = None
    #: `max(live, reconciled)` — never the sum, never the lower of the two.
    effective_spend_usd: float | None = None
    budget_exhausted: bool = False
    partial: bool = False
    objectives: list[str] = []
    findings: list["FindingRow"] = []


class RunListPage(_Model):
    """Cursor pagination, `(created_at, run_id)` **descending** (spec §7 item 9).

    `next_cursor` is `make_cursor(created_at, run_id)` of the last item; pass it
    back as `?before=` for the next page. `None` means the end. It is **opaque**
    to the SPA: parse it with `parse_cursor`, never compare it as a string, and
    never construct one by hand — the validator below rejects the bare-timestamp
    form precisely because it silently loses or duplicates tied rows.
    """

    items: list[RunSummary] = []
    next_cursor: str | None = None

    @field_validator("next_cursor")
    @classmethod
    def _cursor_is_the_tie_safe_composite(cls, value: str | None) -> str | None:
        if value is not None:
            parse_cursor(value)   # raises on the tie-unsafe bare-timestamp form
        return value


class TrialView(_Model):
    """`GET /api/runs/{id}/trials/{probe_id}/{epoch}` — one conversation.

    404s with the error envelope when the artifact has no `trial_records`;
    the SPA should not have offered the drill-down in that case
    (`capabilities.trial_records`), so a 404 here is a bug, not a state.
    """

    run_id: RunId
    probe_id: str
    epoch: int
    turns: list[TranscriptTurn] = []
    #: Target-session wall clock. `None` on pre-#2b logs. Excludes the
    #: concurrency-gate queue wait, so it is not end-to-end latency.
    session_seconds: float | None = None
    invariant_failures: int = 0
    checks: list[CheckView] = []
    #: True when anything in this view passed through the redactor.
    redacted: bool = False


# --------------------------------------------------------------------------
# 7. Discover findings
# --------------------------------------------------------------------------

class ReplayView(_Model):
    """`ReplayResult` on the wire. `reproduced` is `trials >= 1 and pass_k == 0`;
    `pass_at_k > 0` separates a flaky reproduction from a solid one, and
    `trials < expected_trials` separates a partial one."""

    status: ReplayStatus
    reproduced: bool | None = None
    trials: int | None = None
    pass_k: float | None = None
    pass_at_k: float | None = None
    expected_trials: int | None = None
    checks: list[CheckView] = []
    reason: str = ""


class FindingRow(_Model):
    """One row of `GET /api/discoveries` — the staged probe joined with its
    `DiscoveryArtifact.findings[]` entry, which is where `confirmed` and the
    replay verdict live (they are absent from the staged YAML)."""

    #: The staged probe's id, i.e. the YAML filename stem. Also the path
    #: parameter of `GET /api/discoveries/{probe_id}`.
    probe_id: str
    #: The `discover` run that produced it, so the finding is correlatable.
    run_id: RunId | None = None
    objective_id: str
    confirmed: bool
    probe_path: str
    category: str | None = None
    safety_critical: bool = False
    persona_id: str = ""
    playbook_id: str = ""
    duplicate_of: str | None = None
    duplicate_reason: str | None = None
    replay_status: ReplayStatus | None = None
    created_at: str | None = None
    #: True when redaction touched this row — drives the `RedactedChip`.
    redacted: bool = False


class FindingDetail(FindingRow):
    """`GET /api/discoveries/{probe_id}`.

    Redacted by default. Revealing is per-object, gated on the token minted at
    server start and logged to stderr with the probe id: there is no global off
    switch and no env var.
    """

    #: The staged file's bytes as committed — the thing a human will `git mv`.
    probe_yaml: str = ""
    #: The eight keys `parse_provenance` lifts out of the YAML comment header.
    provenance: dict[str, str] = {}
    checks: list[CheckView] = []
    turns: list[TranscriptTurn] = []
    replay: ReplayView | None = None


# --------------------------------------------------------------------------
# 8. Compare, trends, judge trust
# --------------------------------------------------------------------------

class CategoryTally(_Model):
    """Per-category (pair x criterion) verdict tally. Advisory only."""

    wins_a: int = 0
    wins_b: int = 0
    ties: int = 0
    unsure: int = 0
    flips: int = 0
    criteria_judged: int = 0
    flip_rate: float = 0.0


class HardMetrics(_Model):
    """From `trial_records` ONLY — never blended with verdicts."""

    latency_mean_a: float | None = None
    latency_mean_b: float | None = None
    latency_p95_a: float | None = None
    latency_p95_b: float | None = None
    invariant_failures_a: int = 0
    invariant_failures_b: int = 0
    trials_a: int = 0
    trials_b: int = 0


class Scoreboard(_Model):
    """`GET /api/compare/{run_id}`.

    There is deliberately **no combined winner field**: compare is advisory,
    and collapsing verdicts and hard metrics into one number is the exact
    claim Evalyn refuses to make.
    """

    run_id: RunId
    pack_name: str | None = None
    created_at: str
    label_a: str
    label_b: str
    source_a: str | None = None
    source_b: str | None = None
    created_at_a: str | None = None
    created_at_b: str | None = None
    categories: dict[str, CategoryTally] = {}
    hard_metrics: dict[str, HardMetrics] = {}
    excluded_pairs: int = 0
    judge_usd: float | None = None
    #: Drives the banner: the run was allowed past a missing/stale calibration,
    #: so its rubric verdicts are untrusted.
    rubric_scores_untrusted: bool = False


class TrendPoint(_Model):
    run_id: RunId
    created_at: str
    value: float


class TrendSeries(_Model):
    """`GET /api/trends?pack&metric`, one series per probe.

    Built from `RunSummary`-level data only — never by re-opening `.eval`
    logs — and degraded runs are **skipped entirely** rather than emitted as
    null points, so a gap in the line means "no readable run", not "zero".
    """

    pack_name: str
    probe_id: str
    metric: TrendMetric
    points: list[TrendPoint] = []


class CriterionCounts(_Model):
    """The `(hits, total)` pair behind one criterion's agreement."""

    hits: int
    total: int


class TrustReport(_Model):
    """`GET /api/trust?pack`.

    The field is `agreement` — **±1-point agreement as shipped** — and never
    `kappa`: nothing here computes Cohen's κ and the name must not imply a
    certification that was not performed. A pack with no `calibration.json` is
    a legitimate 200 with `agreement: null` and a "never calibrated" reason,
    not a 404.
    """

    pack_name: str
    judge_model: str | None = None
    agreement: float | None = None
    per_rubric_agreement: dict[str, float] = {}
    per_criterion_agreement: dict[str, float] = {}
    #: Keyed `"<rubric>:<criterion>"`, matching the calibration record.
    per_criterion_counts: dict[str, CriterionCounts] = {}
    #: Criterion ids present in the rubric but absent from the matched pairs.
    unmatched: list[str] = []
    stale: bool = True
    stale_reason: str | None = None
    calibrated_at: str | None = None
    threshold: float | None = None


# --------------------------------------------------------------------------
# 9. Write side
# --------------------------------------------------------------------------

class LaunchRequest(_Model):
    """`POST /api/runs`.

    `extra="forbid"` is a **safety guard**, not tidiness: there is no field for
    a pack path, so a body carrying one is rejected rather than ignored. The
    server resolves `pack_id` against the allowlist built from
    `evalyn ui --target <path>` at start; a browser can never name a pack the
    operator did not. `confirm` must echo the pack's name, so a drive-by
    `curl` cannot start spend.
    """

    mode: RunMode
    #: An id from `GET /api/packs` — an index into the start-time allowlist.
    pack_id: str
    #: Must equal the pack's name. Wrong or absent ⇒ 400 `launch_refused`.
    confirm: str
    #: gate: the baseline to diff against.
    baseline_run_id: RunId | None = None
    #: compare: the two gate artifacts to pair.
    run_id_a: RunId | None = None
    run_id_b: RunId | None = None
    #: discover: clamped server-side to
    #: `min(request, pack.spec.budget.max_usd_per_run)`. The browser can lower
    #: the ceiling, never raise it.
    max_usd: float | None = None
    #: discover: subset of the pack's objectives. Empty ⇒ all of them.
    objectives: list[str] = []
    allow_uncalibrated: bool = False


class ControlRequest(_Model):
    """`POST /api/runs/{id}/control`.

    The corresponding `control.*` SSE event **is** the ack. If none lands
    within 60 s the server escalates to `SIGTERM` on the process group, after
    writing to the control file — never `SIGKILL`, which loses the Inspect log.
    """

    action: ControlAction


# --------------------------------------------------------------------------
# 10. Server meta
# --------------------------------------------------------------------------

class RedactionMeta(_Model):
    """Drives the always-visible `RedactionBanner`."""

    enabled: bool = True
    marker: str = "«redacted:<kind>»"
    #: Reveal requires the `X-Evalyn-Reveal` token minted at server start.
    reveal_required: bool = True


class MetaResponse(_Model):
    """`GET /api/meta` — one of exactly two routes exempt from redaction."""

    version: str
    runs_dir: str
    packs: list[str] = []
    allow_discover: bool = False
    redaction: RedactionMeta = RedactionMeta()
    heartbeat_seconds: float = HEARTBEAT_SECONDS


class HealthResponse(_Model):
    """`GET /api/health` — the other redaction-exempt route."""

    ok: bool = True
    version: str


RunDetail.model_rebuild()
DiscoverySummary.model_rebuild()
