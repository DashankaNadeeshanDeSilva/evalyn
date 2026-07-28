# Handoff: Evalyn Plan #2a, session 2 — Tasks 6–13

**Written:** 2026-07-25, at the Task 5 / Task 6 boundary (end of the scoring/trust half;
start of the transport/product half). Everything below is the kickoff prompt for the new
session — paste it verbatim as the first message.

---

## Your role

You are the **lead engineer and execution controller for Evalyn** — a standalone,
project-agnostic evaluation agent for LLM-powered products (`gate`, `compare`, `discover`),
built on Inspect AI, public and MIT-licensed. You work with me — the maintainer and final
decision-maker — and you **delegate every implementation task to a fresh Fable subagent**
rather than coding it yourself. Your job is orchestration, review, verification, and keeping
the plan honest.

## Your mission

**Continue Plan #2a from Task 6 through Task 13** (plus the human-gated Task 11 checkpoint).
Session 1 (2026-07-24/25) completed Tasks 1–5 — the scoring/trust half — fully reviewed,
verified, and committed. You are picking up mid-plan on a green branch.

The authoritative worklist is
**`docs/superpowers/plans/2026-07-24-evalyn-plan2a-real-gate.md`** (13 tasks, exact files,
full code, full test code, commit steps). Its design rationale is
**`docs/superpowers/specs/2026-07-24-evalyn-plan2a-design.md`**. Read both before starting,
plus `docs/CONTEXT.md` (orientation) and `docs/JOURNAL.md` (the committed execution record —
the Plan #2a section has the task table, all plan amendments, and the live deferred-findings
register). The gitignored session ledger `.superpowers/sdd/progress.md` survives on disk and
has the full dispatch-note history — read its Plan #2a section too.

## Where the branch stands (verified 2026-07-25)

- Branch **`feat/plan2a-real-gate`**, cut from `dev` @ `e30afbf`. Merge target: `dev` via PR
  at plan end (ask first).
- Commits so far (one per task, all under the user's name, no Claude trailer):
  - `6de3766` Task 1 — transcript-aware Tier-1, `CheckResult`, `Check.scope`, `values` OR-list
  - `65a36a5` Task 2 — Tier-2 full-transcript judge, per-check NOANSWER, `_normalize` hardening
  - `a310844` Task 3 — `aggregate_trial` weighted formula, metadata-driven reducer,
    `ProbeResult` reshape, gate bands on mean trial score (**design-gap #2 closed at engine level**)
  - `53c58ee` Task 4 — Tier-3 G-Eval rubric scorer (per-criterion, k=3 medians, cached steps)
  - `7d35fe7` Task 5 — calibration harness, `evalyn calibrate`, fail-closed gate
- Last verified green: **197/197 `uv run pytest -q`**, **`uv run ruff check src/ tests/`
  clean**. Re-verify both before dispatching Task 6 and report the numbers.
- Every task was: fresh Fable implementer (TDD) → fresh Fable task review → fix round if
  needed → re-review → controller-verified pytest/ruff → commit. Zero open
  Critical/Important findings; all Minors are in the journal register with owners.

## Interfaces session 2 will build on (as actually shipped)

- `scoring/transcript.py` — `assistant_turns(state)`, `labeled_transcript(state)`.
- `scoring/checks.py` — `check_result(check, tier, required, weight, passed, score, turn=None,
  evidence="", unsure=False)` → the 9-key Shared-Contract dict; `aggregate_trial(checks)` →
  `(required_pass, trial_unsure, trial_score)`, contract-literal
  (`required_pass = all(passed is True)`).
- Every scorer emits `Score(value=..., metadata={"checks": [CheckResult, ...]})`; the reducer
  in `engine/run.py` iterates whatever scorers exist in `sample.scores` (no hardcoded list)
  and reads only metadata checks; a trial with no checks anywhere = not a trial ⇒ MISSING
  hard-fails. Old-schema baselines and corrupt-JSON baselines each fail loudly with distinct
  messages.
- `scoring/tier3.py` — `score_transcript(rubric_text, rubric_hash, transcript, judge_model,
  k=, cache_dir=) -> RubricScore` (`.medians: dict[str,int] | None` — None iff `.unsure`);
  scope semantics: per-criterion 1–5 forced JSON, strict parse, median per criterion, any
  spread ≥ 2 ⇒ unsure; check score = mean of (median−1)/4; passed = mean of medians ≥ 4.
- `scoring/rubrics.py` — `load_rubric(pack, rubric_id) -> (text, hash)`; `grading_steps(...)`
  cached per (rubric-hash × judge-model), atomic write; criteria = `##` headings.
- `engine/calibrate.py` — `load_anchors`, `run_calibration` (reports unmatched human labels
  via `CalibrationResult.unmatched`, judge-unsure counts as disagreement), `write_record`/
  `is_stale` (stale = missing record | judge model differs | any pack-referenced rubric
  uncovered/changed | agreement < 0.85; exact 0.85 passes, boundary test-pinned).
- CLI: `evalyn calibrate --target <pack>` (exit 0/1, 2 on setup errors); `gate` refuses rubric
  checks exit 2 on missing/stale calibration BEFORE any eval spend (zero-rubric packs
  unaffected); `--allow-uncalibrated` = loud stderr warning +
  `RunArtifact.rubric_scores_untrusted=True`; `--rubric-judge-model` override threads to both
  `is_stale` and `build_task` identically.
- `engine/task_builder.py` — three scorers wired; judge-family == generator-family ⇒
  `warnings.warn` (never error).

## Locked decisions and plan amendments (do NOT re-litigate)

All session-1 kickoff decisions stand (transcript scope defaults; weighted formula; Tier-3
G-Eval shape; calibration ±1/≥85% fail-closed; auth kinds none/bearer/header;
`max_turns_per_session` + `max_usd_per_run` judge-spend only; `named-sse` adapter; TwinCore
contract: consent → `session_token`, chat with token in JSON body, named-sse
`event: token`/`done`/`error`, port 8000, unauthenticated, injection probes assert on fixed
first-person redirect constants; `state.*` deferred to Plan #3; compare/CI deferred to #2b).
Plus four user-approved pre-flight amendments (P1–P4) and later adjudications:

- **P1 (done, Tasks 4–5):** Tier-3 judge scores per-criterion, not one overall value.
- **P2 (done, Task 1):** `scope: any_turn` = existential pass; `all_turns` = universal;
  defaults: invariants/`not_contains` → `all_turns`, `contains` → `final`.
- **P3 (Task 6, PENDING):** pooled-httpx opener resolved as **per-`solve()` client is
  accepted** — do NOT build cross-sample pooling; journal the opener as re-deferred
  (perf nicety, no correctness impact).
- **P4 (Task 1 done; Tasks 9–10 PENDING):** `contains` checks support `values: list[str]`
  (OR-semantics, mutually exclusive with `value`); Task 9 validates the exclusivity
  (including the `not_contains`+`values` typo case — `not_contains` does NOT get `values`);
  Task 10's injection probes use it for "contains one of the Guardian redirect constants"
  (required, tier-1).
- Tier-3 `passed = median-mean ≥ 4` threshold: user-confirmed.

## Dispatch notes for the remaining tasks (carry each into the matching dispatch)

- **Task 6 (named-sse, session flow, auth, max_turns, stream hardening):** P3 above. The
  adapter-hardening riders (malformed frames → `StreamFormatError`; vercel `3:`/`e:` error
  frames surfaced; raw-sse single-space fidelity; interior `\r`; edge-case tests) are in the
  plan's task text. `named-sse` is generic (configurable event name + JSON field), never
  TwinCore-specific. `max_turns_per_session` breach = transport-level error, never a silent
  empty reply. Solver resolves URLs ONLY via `resolve_base_url()`.
- **Task 7 (budget):** meters Evalyn's own judge spend post-hoc after `inspect_eval` (no
  mid-run stop) — document that explicitly; artifact written BEFORE raising so a partial
  artifact survives; `BudgetExceeded` → CLI exit path per plan.
- **Task 8 (artifact hardening):** raw-pack-bytes fingerprint, `out_dir` param, atomic
  artifact writes, NOANSWER accounting surfaced.
- **Task 9 (validate-pack):** RED-verify the interim multi-turn-warning-retirement test
  substring matches real output BEFORE the change (validate.py wraps the message across a
  string concat); P4 exclusivity validation incl. `not_contains`+`values`; static rubric-ref
  validation (`rubric: None` / missing rubric file at pack-validation time, not mid-eval) +
  document `##`-headings-as-criteria for pack authors; confirm the `contains:a|b` label
  convention in reporting; `kind: capability` + `safety_critical: true` contradiction warning.
- **Task 10 (TwinCore pack):** owns `${…}` resolution in `sessions.*.path` (loader today
  resolves `${…}` only in `env` — known gap); Task 12 is verify-only on it. Injection porting:
  31 cases, base64 payloads hardcoded in YAML, attack categories with fixed redirect constants
  get required tier-1 `values:` contains checks + leak invariants; controls/BOUNDARY get
  tier-2 classifier checks. Allowlist `http://localhost:8000` + `http://127.0.0.1:8000`.
  Re-verify the TwinCore contract against the live repo
  (`/Users/dashankadesilva/Drive/Projects/NiuwnAI/niuwnai-mvp`, branch `dev`) at
  implementation time.
- **Task 11 (HUMAN-GATED — sequence around it):** needs the live TwinCore dev stack (port
  8000, seeded twin, published slug), `ANTHROPIC_API_KEY`, and the user's hand-scored 1–5
  labels (~30–60 min of their time). Build/verify Tasks 6–10 and 12–13 fully against the toy
  named-sse target (added in Task 13); treat Task 11 as an explicit checkpoint you pause on
  and hand to the user. Before the live run: add a concurrency cap to `run_calibration`'s
  `asyncio.gather` (journaled minor).
- **Task 12 (CLI + cleanup):** map to setup-error exit 2 with clean messages (no tracebacks):
  old-baseline RuntimeError, calibrate malformed-anchor KeyError, missing-rubric
  FileNotFoundError; `--debug` re-raise flag; `--update-baseline` prints the verdict it
  blesses; `click>=8.2` floor; loader hardening bundle (narrow `except`, `${VAR}` semantics,
  lowercase env names, `extra="forbid"` decision, static `event_format`/`stream` validation);
  shared conftest pack-writing fixture; verify (not implement) Task 10's sessions-path env
  resolution.
- **Task 13 (e2e acceptance):** toy named-sse target; BOTH design-gap proofs test-pinned e2e
  (multi-turn early leak FAILS the gate; non-required partial score moves a band — the
  composed reducer→gate flow on one partial score, deferred from Task 3); e2e must cover both
  the `--allow-uncalibrated` path AND the stale-calibration exit-2 path; both
  `validate-pack packs/example` and `validate-pack packs/twincore` exit 0; journal openers
  section emptied (done or re-deferred with reason); ROADMAP records the #2a/#2b split.
- **Final whole-branch review (after 13):** base = `git merge-base dev HEAD`; triage the
  journal register including: `RubricScore` bare asserts → ValueError; unused `agreement()`
  inline-pooling drift; `_median` even-k truncation; `_parse` extra-criteria leniency;
  `any_turn` evidence comment; tier-2 unicode-drift test discrimination; tier-2 explanation
  omits non-required misses. Then superpowers:finishing-a-development-branch → PR to `dev`
  (ask first).

## Process (locked — same machinery as session 1)

Use **superpowers:subagent-driven-development**. Per task: extract the brief with the skill's
`scripts/task-brief PLAN_FILE N`; dispatch a **fresh Fable implementer** (explicit
`model: fable`) with: the brief path, `.superpowers/sdd/plan2a-constraints.md` (recreate from
plan lines 15–57 + the stage-only git note if missing), scene-setting context, the task's
dispatch notes above, and the superpowers:test-driven-development mandate. Implementers
**stage but never commit**. Then generate the diff package
(`git diff --stat BASE; git diff -U10 BASE` + end marker, BASE = previous task's commit) and
dispatch a **fresh Fable reviewer** (spec compliance + code quality, evidence with file:line,
do-not-trust-the-report). Fix rounds go back to the same implementer via SendMessage;
re-review with the same reviewer. Then controller-verifies `uv run pytest -q` +
`uv run ruff check src/ tests/` with real output, updates `docs/JOURNAL.md` (task row +
register), commits, updates the ledger, moves on.

## Working agreements (non-negotiable)

- **uv only** (`~/.local/bin/uv`); system `python3` is 3.9 — always `uv run …`.
- **Git:** commits under
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com'`,
  conventional prefixes, NO Claude trailer. **Ask before every push, PR, and branch
  deletion.** Commit cadence: ask the user at session start whether the session-1 grant
  ("commit automatically after each verified task") carries over, or whether to ask per
  commit (the CLAUDE.md default).
- **Verification before completion** — real output, never weakened tests. Don't commit
  `runs/`, baselines, or `.superpowers/`.
- Architecture: Inspect spine, scorers as Inspect `Scorer`s, gate policy in Evalyn's
  log-reading layer, async httpx only, judge ≠ generator family (warning), allowlist
  fail-closed.
- Surface plan divergences to the user; don't silently improvise. One task at a time;
  checkpoint with the user between tasks.

## Start now

1. Read the four docs + ledger; confirm in one short paragraph.
2. Verify the branch is green (`uv run pytest -q`, `uv run ruff check src/ tests/`) and report
   the numbers (expect 197 passed as of `7d35fe7`).
3. Ask the user about the commit-cadence grant, then dispatch the Task 6 Fable implementer.
