/**
 * The cockpit wire contract, hand-mirrored from `src/evalyn/ui/models.py`.
 *
 * `models.py` is the source of truth; this file is a **hand-written** mirror
 * and `src/api/__tests__/types.test.ts` is the only thing holding the two
 * together. That test parses `models.py` at run time, so widening a Python enum
 * without touching this file goes red — do not "fix" it by editing the frozen
 * literals until you have read the Python change.
 *
 * Four properties of the wire that a TypeScript type cannot express, and that
 * every consumer of this file has to know:
 *
 * 1. **`VerdictTier` is a string, always.** `"1" | "2" | "3" | "abstained"`.
 *    Not an accident of Python's `str, Enum`: `abstained` is a member, so an
 *    integer wire form was never expressible. Never write `tier === 1`.
 * 2. **`next_cursor` is opaque.** It is the composite `"<created_at>|<run_id>"`,
 *    not a bare timestamp. Pass it back verbatim; never build one client-side.
 * 3. **Every response model is `extra="forbid"` server-side.** An unexpected
 *    key is a server error, not a tolerated addition. These interfaces are
 *    exact — adding an optional field here to "be safe" hides a real bug.
 * 4. **Absent is not null, and null is not zero.** Affordances come off
 *    `Capabilities`, never off truthiness. A `null` metric means "this run
 *    cannot tell you"; `0` means the measurement was zero.
 *
 * Optionality convention, applied consistently below:
 *
 * - **Response** models list every field as *present*, because FastAPI
 *   serialises defaults. A Python `X | None = None` becomes `X | null` — a
 *   required key holding a nullable value, never `field?: X`.
 * - **Request** models (`LaunchRequest`, `ControlRequest`) mark defaulted
 *   fields `?`, because the browser genuinely may omit them.
 */

// ---------------------------------------------------------------------------
// 1. `run_id` grammar — a path SEGMENT, never a path
// ---------------------------------------------------------------------------

/**
 * Byte-identical to `models.RUN_ID_PATTERN`.
 *
 * Path traversal is excluded by construction: the character class admits no
 * `/`. JavaScript's `$` anchors to the end of the string, matching the Rust
 * regex engine pydantic validates with — Python's own `re` is the odd one out
 * (its `$` also matches before a trailing newline), which is why `models.py`
 * uses `fullmatch` there and why this pattern needs no adjustment here.
 */
export const RUN_ID_PATTERN =
  "^(?:\\d{8}T\\d{6}\\d{0,6}-[0-9a-f]{8}-[A-Za-z0-9._-]+" +
  "|\\d{8}T\\d{6}-[A-Za-z0-9._-]+)$";

export const RUN_ID_RE = new RegExp(RUN_ID_PATTERN);

/** A validated artifact stem. Aliased, not branded — the server re-validates. */
export type RunId = string;

/**
 * The single authority on whether a string is a run id, mirroring
 * `models.is_run_id`. The `.json` guard is separate from the pattern because
 * `.` is legal inside a slug, so `…-example.json` matches the regex and would
 * send the server looking for `…-example.json.json`.
 */
export function isRunId(value: string): boolean {
  return RUN_ID_RE.test(value) && !value.endsWith(".json");
}

// ---------------------------------------------------------------------------
// 2. Redaction + streaming constants
// ---------------------------------------------------------------------------

/** The one and only way a redacted value is spelled: `«redacted:<kind>»`. */
export const REDACTION_MARKER_RE = /«redacted:[a-z_]+»/;

/** Header carrying the reveal token minted at server start. Per-object, logged. */
export const REVEAL_HEADER = "X-Evalyn-Reveal";

/** SSE heartbeat cadence, seconds. An idle run is not a dead connection. */
export const HEARTBEAT_SECONDS = 15;

// ---------------------------------------------------------------------------
// 3. Pagination cursor — opaque, and tie-safe by construction
// ---------------------------------------------------------------------------

export const CURSOR_SEPARATOR = "|";

/**
 * Split an opaque cursor into its `(created_at, run_id)` ordering key.
 *
 * The tuple **is** the sort key: rows are ordered by it descending. Compare the
 * parsed tuples, never the cursor strings — one `created_at` can be a prefix of
 * another (`…:44+00:00` vs `…:44.5+00:00`) and the separator sorts after the
 * characters that would have decided it, so a lexicographic comparison of the
 * joined form can invert the intended order.
 *
 * There is deliberately no `makeCursor` here. The SPA receives cursors and
 * hands them back verbatim; constructing one client-side is how the tie-unsafe
 * bare-timestamp form gets reintroduced, and the server rejects it.
 */
export function parseCursor(cursor: string): [createdAt: string, runId: RunId] {
  const at = cursor.indexOf(CURSOR_SEPARATOR);
  if (at === -1) {
    throw new Error(
      `cursor must be the opaque composite '<created_at>${CURSOR_SEPARATOR}<run_id>', ` +
        `got ${JSON.stringify(cursor)} — a bare timestamp is not tie-safe`,
    );
  }
  return [cursor.slice(0, at), cursor.slice(at + 1)];
}

// ---------------------------------------------------------------------------
// 4. Enums — closed sets. Each is a `const` array plus the union it induces,
//    so pages can both iterate members and switch on them exhaustively.
// ---------------------------------------------------------------------------

/** Classified lexically from the filename suffix — never by opening the file. */
export const RUN_MODES = ["gate", "compare", "discover"] as const;
export type RunMode = (typeof RUN_MODES)[number];

/**
 * Nine states, and the distinctions are load-bearing. `invalid` completed but
 * means nothing; `unreadable` is an artifact this build cannot parse — the run
 * may have been fine. `interrupted` vanished mid-flight; `failed_to_start`
 * never got that far.
 */
export const RUN_STATUSES = [
  "passed",
  "gate_failed",
  "invalid",
  "running",
  "paused",
  "cancelled",
  "interrupted",
  "failed_to_start",
  "unreadable",
] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

/** Every non-2xx body is `{"error": {...}}` with a code from this set. */
export const ERROR_CODES = [
  "not_found",
  "unreadable_artifact",
  "pack_error",
  "launch_refused",
  "busy",
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

/** String-valued on the wire. `abstained` is not tier 0. Never `tier === 1`. */
export const VERDICT_TIERS = ["1", "2", "3", "abstained"] as const;
export type VerdictTier = (typeof VERDICT_TIERS)[number];

/**
 * An **approximation** carried by list rows, computed from `probes[]` alone so
 * the list never calls `evaluate_gate`. The authoritative verdict comes from
 * `GET /api/runs/{id}/gate`. Never render this without saying so.
 */
export const VERDICT_HINTS = ["passed", "failed", "unknown"] as const;
export type VerdictHint = (typeof VERDICT_HINTS)[number];

export const CONTROL_ACTIONS = ["pause", "resume", "cancel"] as const;
export type ControlAction = (typeof CONTROL_ACTIONS)[number];

/**
 * A replay that ran and did not reproduce is a different claim from one that
 * never ran; a budget skip is different from `--no-replay`.
 */
export const REPLAY_STATUSES = [
  "reproduced",
  "not_reproduced",
  "skipped_budget",
  "skipped_disabled",
] as const;
export type ReplayStatus = (typeof REPLAY_STATUSES)[number];

export const TURN_ROLES = ["user", "assistant"] as const;
export type TurnRole = (typeof TURN_ROLES)[number];

export const TREND_METRICS = [
  "mean_score",
  "pass_k",
  "pass_at_k",
  "judge_usd",
] as const;
export type TrendMetric = (typeof TREND_METRICS)[number];

/**
 * The SSE `event:` names. The SPA switches on these; an unknown name is
 * ignored rather than fatal, but it must not be *emitted* without landing in
 * `models.EventName` first.
 */
export const EVENT_NAMES = [
  "run.started",
  "spend.updated",
  "artifact.written",
  "run.finished",
  "trial.started",
  "turn.sent",
  "turn.received",
  "trial.finished",
  "probe.scored",
  "pair.judged",
  "agent.step",
  "agent.reply",
  "confirm.result",
  "finding.staged",
  "replay.result",
  "control.paused",
  "control.resumed",
  "control.cancelled",
  "heartbeat",
] as const;
export type EventName = (typeof EVENT_NAMES)[number];

// ---------------------------------------------------------------------------
// 5. Error envelope
// ---------------------------------------------------------------------------

export interface ApiError {
  code: ErrorCode;
  message: string;
  /** Operator-facing extra context. Already redaction-scrubbed like any body. */
  detail: string | null;
}

/**
 * The body of **every** non-2xx response — including the ones no Evalyn handler
 * raises. The server re-wraps FastAPI's own `RequestValidationError` (422) and
 * `HTTPException` into this shape, so the SPA has exactly one error parser:
 * read `error.code`, switch on it.
 */
export interface ErrorEnvelope {
  error: ApiError;
}

// ---------------------------------------------------------------------------
// 6. Runs
// ---------------------------------------------------------------------------

/**
 * What this artifact can actually answer. Disable affordances off these
 * booleans, never off truthiness — a pre-#2b run has no `trial_records`, and an
 * empty transcript list must read as "not captured", not "the conversation was
 * empty".
 */
export interface Capabilities {
  /** Any `trial_records[].transcript` is non-empty — the drill-down works. */
  transcripts: boolean;
  /** `trial_records` is present and non-empty for at least one probe. */
  trial_records: boolean;
  /** Latency / invariant-failure aggregates are available. */
  hard_metrics: boolean;
}

export interface CheckView {
  check: string;
  tier: VerdictTier;
  required: boolean;
  weight: number;
  /** `null` when the check abstained (see `unsure`) — not `false`. */
  passed: boolean | null;
  score: number | null;
  /** 1-based turn index the evidence came from; `null` for whole-session checks. */
  turn: number | null;
  evidence: string;
  unsure: boolean;
  /** True when `evidence` passed through the redactor. */
  redacted: boolean;
}

export interface TranscriptTurn {
  role: TurnRole;
  text: string;
  redacted: boolean;
}

export interface ProbeRow {
  id: string;
  category: string;
  kind: string;
  safety_critical: boolean;
  samples: number;
  trials: number;
  /**
   * 0 means "unknown" on a pre-round-2 artifact — the gate skips its
   * incompleteness check in that case, so do not render it as "0 expected".
   */
  expected_trials: number;
  pass_at_k: number | null;
  pass_k: number | null;
  mean_score: number | null;
  unsure_trials: number;
  checks: CheckView[];
  /**
   * Epochs that have a trial record, i.e. the drill-downs that exist. Empty
   * means the row's drill-down is disabled, never that the run had no trials.
   */
  trial_epochs: number[];
}

/** One row of `GET /api/runs`. Cheap by construction. */
export interface RunSummary {
  run_id: RunId;
  mode: RunMode;
  /** `null` only when even the salvage read failed (unparseable JSON). */
  pack_name: string | null;
  /**
   * ISO-8601 UTC **verbatim** from the artifact, or recovered from the filename
   * stamp when the body is unreadable. The SPA formats; the server never does.
   */
  created_at: string;
  status: RunStatus;
  degraded: boolean;
  /**
   * Required when `degraded` — a greyed row with no explanation is the failure
   * mode this field exists to prevent. Render it as the row's tooltip.
   */
  degraded_reason: string | null;
  capabilities: Capabilities;
  /** Evalyn's OWN judge spend. `null` = not recorded, never `0`. */
  judge_usd: number | null;
  verdict_hint: VerdictHint | null;
}

/** `GET /api/runs/{id}/gate` — the real `evaluate_gate`, called lazily. */
export interface GateVerdict {
  run_id: RunId;
  exit_code: number;
  failures: string[];
  quarantined: string[];
  report_md: string;
  /** `null` = no baseline was available, which makes capability checks advisory. */
  baseline_run_id: string | null;
  /** True when `report_md` / `failures` passed through the redactor. */
  redacted: boolean;
}

/** The `discover`-specific half of a `RunDetail`. */
export interface DiscoverySummary {
  agent_model: string | null;
  rubric_judge_model: string | null;
  /**
   * Every counter goes to zero when the eval itself failed. Without this, a run
   * that never looked is byte-identical to a run that looked and found nothing.
   */
  eval_status: string;
  error_count: number;
  sessions_total: number;
  confirmed_count: number;
  live_spend_usd: number | null;
  reconciled_spend_usd: number | null;
  /** `max(live, reconciled)` — never the sum, never the lower of the two. */
  effective_spend_usd: number | null;
  budget_exhausted: boolean;
  partial: boolean;
  objectives: string[];
  findings: FindingRow[];
}

/**
 * `GET /api/runs/{id}`. A superset of the row, so the detail page renders from
 * a warm cache entry without a shape change.
 */
export interface RunDetail extends RunSummary {
  pack_hash: string | null;
  judge_model: string | null;
  /** Path as recorded, home directories scrubbed by the redactor. */
  log_path: string | null;
  rubric_scores_untrusted: boolean;
  total_unsure_trials: number | null;
  cancelled: boolean;
  probes: ProbeRow[];
  /** True when anything in this view passed through the redactor. */
  redacted: boolean;
  /** Populated for `mode === "compare"` only. */
  compare: Scoreboard | null;
  /** Populated for `mode === "discover"` only. */
  discovery: DiscoverySummary | null;
}

/**
 * Cursor pagination, `(created_at, run_id)` **descending**.
 *
 * `next_cursor` is opaque: hand it back as `?before=`, never parse it to build
 * a new one, never compare it as a string. `null` means the end.
 */
export interface RunListPage {
  items: RunSummary[];
  next_cursor: string | null;
}

/**
 * `GET /api/runs/{id}/trials/{probe_id}/{epoch}` — one conversation.
 *
 * 404s with the error envelope when the artifact has no `trial_records`; the
 * SPA should not have offered the drill-down in that case
 * (`capabilities.trial_records`), so a 404 here is a bug, not a state.
 */
export interface TrialView {
  run_id: RunId;
  probe_id: string;
  epoch: number;
  turns: TranscriptTurn[];
  /**
   * Target-session wall clock. `null` on pre-#2b logs. Excludes the
   * concurrency-gate queue wait, so it is not end-to-end latency.
   */
  session_seconds: number | null;
  invariant_failures: number;
  checks: CheckView[];
  redacted: boolean;
}

// ---------------------------------------------------------------------------
// 7. Discover findings
// ---------------------------------------------------------------------------

/**
 * `reproduced` is `trials >= 1 && pass_k === 0`; `pass_at_k > 0` separates a
 * flaky reproduction from a solid one, and `trials < expected_trials` separates
 * a partial one.
 */
export interface ReplayView {
  status: ReplayStatus;
  reproduced: boolean | null;
  trials: number | null;
  pass_k: number | null;
  pass_at_k: number | null;
  expected_trials: number | null;
  checks: CheckView[];
  reason: string;
}

/**
 * One row of `GET /api/discoveries` — the staged probe joined with its
 * `DiscoveryArtifact.findings[]` entry, which is where `confirmed` and the
 * replay verdict live (they are absent from the staged YAML).
 */
export interface FindingRow {
  /** The staged probe's id, i.e. the YAML filename stem. Also the path param. */
  probe_id: string;
  /** The `discover` run that produced it, so the finding is correlatable. */
  run_id: RunId | null;
  objective_id: string;
  confirmed: boolean;
  probe_path: string;
  category: string | null;
  safety_critical: boolean;
  persona_id: string;
  playbook_id: string;
  duplicate_of: string | null;
  duplicate_reason: string | null;
  replay_status: ReplayStatus | null;
  created_at: string | null;
  /** True when redaction touched this row — drives the `RedactedChip`. */
  redacted: boolean;
}

/**
 * `GET /api/discoveries/{probe_id}`. Redacted by default. Revealing is
 * per-object, gated on the `X-Evalyn-Reveal` token minted at server start and
 * logged to stderr with the probe id: no global off switch, no env var.
 */
export interface FindingDetail extends FindingRow {
  /** The staged file's bytes as committed — the thing a human will `git mv`. */
  probe_yaml: string;
  /** The eight keys `parse_provenance` lifts out of the YAML comment header. */
  provenance: Record<string, string>;
  checks: CheckView[];
  turns: TranscriptTurn[];
  replay: ReplayView | null;
}

// ---------------------------------------------------------------------------
// 8. Compare, trends, judge trust
// ---------------------------------------------------------------------------

/** Per-category (pair x criterion) verdict tally. Advisory only. */
export interface CategoryTally {
  wins_a: number;
  wins_b: number;
  ties: number;
  unsure: number;
  flips: number;
  criteria_judged: number;
  flip_rate: number;
}

/** From `trial_records` ONLY — never blended with verdicts. */
export interface HardMetrics {
  latency_mean_a: number | null;
  latency_mean_b: number | null;
  latency_p95_a: number | null;
  latency_p95_b: number | null;
  invariant_failures_a: number;
  invariant_failures_b: number;
  trials_a: number;
  trials_b: number;
}

/**
 * `GET /api/compare/{run_id}`.
 *
 * There is deliberately **no combined winner field**: compare is advisory, and
 * collapsing verdicts and hard metrics into one number is the exact claim
 * Evalyn refuses to make. Do not compute one in the SPA either.
 */
export interface Scoreboard {
  run_id: RunId;
  pack_name: string | null;
  created_at: string;
  label_a: string;
  label_b: string;
  source_a: string | null;
  source_b: string | null;
  created_at_a: string | null;
  created_at_b: string | null;
  categories: Record<string, CategoryTally>;
  hard_metrics: Record<string, HardMetrics>;
  excluded_pairs: number;
  judge_usd: number | null;
  /** Drives the banner: rubric verdicts here are untrusted. */
  rubric_scores_untrusted: boolean;
  redacted: boolean;
}

export interface TrendPoint {
  run_id: RunId;
  created_at: string;
  value: number;
}

/**
 * `GET /api/trends?pack&metric`, one series per probe. Degraded runs are
 * **skipped entirely** rather than emitted as null points, so a gap in the line
 * means "no readable run", not "zero" — do not connect across it silently.
 */
export interface TrendSeries {
  pack_name: string;
  probe_id: string;
  metric: TrendMetric;
  points: TrendPoint[];
}

/** The `(hits, total)` pair behind one criterion's agreement. */
export interface CriterionCounts {
  hits: number;
  total: number;
}

/**
 * `GET /api/trust?pack`.
 *
 * The field is `agreement` — **±1-point agreement as shipped** — and never
 * `kappa`: nothing computes Cohen's κ and the label must not imply a
 * certification that was not performed. A pack with no `calibration.json` is a
 * legitimate 200 with `agreement: null`, not a 404.
 */
export interface TrustReport {
  pack_name: string;
  judge_model: string | null;
  agreement: number | null;
  per_rubric_agreement: Record<string, number>;
  per_criterion_agreement: Record<string, number>;
  /** Keyed `"<rubric>:<criterion>"`, matching the calibration record. */
  per_criterion_counts: Record<string, CriterionCounts>;
  /** Criterion ids present in the rubric but absent from the matched pairs. */
  unmatched: string[];
  stale: boolean;
  stale_reason: string | null;
  calibrated_at: string | null;
  threshold: number | null;
}

// ---------------------------------------------------------------------------
// 9. Write side — request bodies, so defaulted fields are genuinely optional
// ---------------------------------------------------------------------------

/**
 * `POST /api/runs`.
 *
 * `extra="forbid"` server-side is a **safety guard**, not tidiness: there is no
 * field for a pack path, so a body carrying one is rejected rather than
 * ignored. `pack_id` indexes the start-time allowlist built from
 * `evalyn ui --target <path>`; a browser can never name a pack the operator did
 * not. `confirm` must echo the pack's name, so a drive-by `curl` cannot start
 * spend.
 */
export interface LaunchRequest {
  mode: RunMode;
  /** An id from `GET /api/packs` — an index into the allowlist, never a path. */
  pack_id: string;
  /** Must equal the pack's name. Wrong or absent ⇒ 400 `launch_refused`. */
  confirm: string;
  /** gate: the baseline to diff against. */
  baseline_run_id?: RunId | null;
  /** compare: the two gate artifacts to pair. */
  run_id_a?: RunId | null;
  run_id_b?: RunId | null;
  /**
   * discover: clamped server-side to
   * `min(request, pack.spec.budget.max_usd_per_run)`. The browser can lower the
   * ceiling, never raise it.
   */
  max_usd?: number | null;
  /** discover: subset of the pack's objectives. Empty ⇒ all of them. */
  objectives?: string[];
  allow_uncalibrated?: boolean;
}

/**
 * `POST /api/runs/{id}/control`.
 *
 * The corresponding `control.*` SSE event **is** the ack — do not treat the
 * 2xx as confirmation. If none lands within 60 s the server escalates to
 * `SIGTERM` on the process group, never `SIGKILL`.
 */
export interface ControlRequest {
  action: ControlAction;
}

// ---------------------------------------------------------------------------
// 10. Server meta
// ---------------------------------------------------------------------------

/** Drives the always-visible `RedactionBanner`. */
export interface RedactionMeta {
  enabled: boolean;
  marker: string;
  reveal_required: boolean;
}

/**
 * `GET /api/meta` — one of exactly two routes exempt from the redaction
 * chokepoint.
 *
 * `runs_dir` and `packs` are **display-safe labels**, with the home directory
 * collapsed to `~`. They exist to answer "which runs directory is this cockpit
 * serving" without answering "who is running it". Never treat either as a real
 * filesystem path and never send one back to the server.
 */
export interface MetaResponse {
  version: string;
  runs_dir: string;
  packs: string[];
  allow_discover: boolean;
  redaction: RedactionMeta;
  heartbeat_seconds: number;
}

/** `GET /api/health` — the other redaction-exempt route. */
export interface HealthResponse {
  ok: boolean;
  version: string;
}
