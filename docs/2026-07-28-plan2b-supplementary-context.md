# Supplementary context — what changed since the Plan #2a docs were written

**Paste this into any ongoing session that was seeded with Plan #2a-era context (the
2026-07-24 plan/spec, session handoffs, or the pre-merge JOURNAL). Everything below
happened at the END of Plan #2a — during PR #4's two review rounds — and several items
CHANGE assumptions those documents state. The updated source of truth is the merged `dev`
branch (`f6be671`) plus `docs/JOURNAL.md` and `docs/ROADMAP.md` at that commit.**

## Headline state

- **Plan #2a is MERGED**: PR #4 → `dev` @ `f6be671` (2026-07-28). 20 branch commits,
  **340 tests**, ruff clean, both packs validate. Do not re-plan or re-do anything in it.
- PR #4 went through **two full review rounds (23 findings: 13 + 10, incl. 5 High)** —
  all fixed, re-review-verified, and answered in-thread. The fixes changed several core
  semantics AFTER the Plan #2a plan/spec were written. The deltas are listed below;
  treat them as **locked decisions** (user-ratified during review) unless the user reopens one.

## Semantics that differ from the original Plan #2a documents

1. **Calibration gates PER-RUBRIC, fail-closed** (was: overall-only ≥85%). Every rubric
   must individually reach 85% agreement; `is_stale` and `evalyn calibrate` share the rule
   and name the weak rubric(s). Agreement is pooled from raw per-criterion (hits, totals)
   counts on new records (`per_criterion_counts`, `per_rubric_agreement` — additive fields);
   old records fall back to mean-of-fractions.
2. **The committed TwinCore calibration record is deliberately STALE** (groundedness 60%).
   This is by design, test-pinned, and publicly documented in the PR threads. A trusted
   gate run against TwinCore is impossible until recalibration; `--allow-uncalibrated`
   runs are loud (stderr + report banner, current AND baseline side).
3. **New gate verdict: INCOMPLETE.** `ProbeResult.expected_trials` records the pack-wide
   epoch count; a probe with `0 < trials < expected` FAILS as INCOMPLETE (capability
   probes still never red; old artifacts load via a `0`=unknown fallback). Rationale:
   `fail_on_error=False` (also new) lets individual samples error without aborting the
   run, so pass^k's denominator must be defended.
4. **Run-level failure taxonomy:** sample errors land per-probe (MISSING at 0 trials,
   INCOMPLETE below expected); a run where NO probe scored a single trial raises a
   setup error → exit 2 (artifact still written first). CI can distinguish "product
   regressed" (exit 1) from "eval never reached the product" (exit 2).
5. **No-signal trial semantics:** a trial where all non-required checks are unsure, OR
   any REQUIRED check is unsure, has `trial_score=None` (excluded from `mean_score`;
   all-None probe → 0.0 fail-closed) and counts in `unsure_trials`. A judge outage can
   no longer green a gate.
6. **Tier-2 judge hardening:** `_parse_judge` accepts only real JSON booleans or the exact
   strings "true"/"false" — anything else is NOANSWER (a judge saying `"false"` used to
   coerce to `True`!). Evidence for REQUIRED checks must be verbatim (normalized
   containment); the fuzzy 0.6-overlap fallback is non-required-only.
7. **Baseline blessing guards:** `--update-baseline` REFUSES artifacts that are
   rubric-untrusted or have zero-trial probes (exit 2); `--force-baseline` is the loud
   escape hatch; reports banner an untrusted BASELINE distinctly from an untrusted current.
8. **Stream adapters:** vercel-ai treats only `3:` as an error — `e:`/`f:`/`d:` are AI-SDK
   lifecycle frames, consumed silently (the old behavior would have crashed on every real
   AI-SDK stream). named-SSE resets the event type at each blank-line dispatch per spec;
   unnamed `data:` frames belong to the default `message` event.
9. **Judged transcripts are clean:** the probe id is no longer seeded as a fabricated
   first user turn (label leakage to the Tier-2/3 judges — fixed; calibration anchors and
   production transcripts now match).
10. **Tier-1 `no-internal-leak` narrowed** to concrete markers (`/data/`, `internal path`) —
    the phrase "system prompt" caused false positives on correct refusals. Compensating
    control: `injection-multiturn-trust-pivot` carries two required `not_contains`
    tripwires quoting static Guardian-prompt section headers ("CRITICAL CONSTRAINT — 
    Knowledge boundary", "ABSOLUTE RULE — Never break character"; source
    `niuwnai-mvp backend/app/utils/prompt.py:275,292`). **Byte-exact coupling** — a
    product-side wording change silently disarms them (registered risk).
11. **Budget:** unknown-model fallback price is now opus-tier `(0.015, 0.075)` (a true
    upper bound) + `RuntimeWarning`; price matching is longest-key-first. Judge default
    everywhere is `anthropic/claude-sonnet-5` (retired `claude-3-5-sonnet-latest` swept).
12. **Gate runs use the grading-steps cache by default** (`run_gate` → `pack.root/.cache`,
    override wins) — gate and calibration judge under the same cached steps.
13. **Misc hardening:** `validate-pack` warns when one probe's `samples` multiplies
    pack-wide epochs (TwinCore: 150 sessions); artifact filenames are collision-proof
    (microsecond + uuid + slugified pack name); `stream:` is `Literal["sse"]`; schemas are
    `extra="forbid"`; all CLI error paths are exit-2-clean with `--debug` re-raise.

## Plan #2b implications (already locked in `docs/ROADMAP.md`)

- **#2b's FIRST task is the KB-fact-sheet groundedness fix + recalibration**: condense the
  twin KB into a fact sheet, inject into the groundedness judge's context, hash it into
  the staleness rule, recalibrate — **growing anchors to ≥10 per rubric** (at 5, an 85%
  bar is a de-facto 100% bar). The existing 20 hand-scored anchors are reusable.
- **Known #2b work items registered in `docs/JOURNAL.md`** (read the register): Inspect
  `model_usage` accumulation across evals (double-counts `judge_usd` in `compare` — user
  ruling: not fixed in #2a); extend the baseline-blessing refusal to INCOMPLETE probes;
  the tripwire silent-drift risk; `is_stale`'s self-attested pooled agreement; Tier-2
  judge family not checked vs generator; `scope` silently ignored on classifier/rubric
  checks (validate-pack warning candidate); plus the minors list tagged "#2b".
- **Pending user-gated action (NOT yet done):** the first live TwinCore gate run — an
  explicitly-bannered `--allow-uncalibrated` **shakedown** (~150 metered sessions; safety
  verdicts fully trustworthy — deterministic Tier-1; quality bands indicative only).
  It must sanity-check `judge_usd` metering and grading-steps cache hits. Requires the
  user's fresh, explicit permission. Recommended to run it before `compare`/CI work
  builds on the same seams.

## Environment notes that survived

- `uv` only; venv Python 3.12 (system python3 is 3.9 — always `uv run`). `anthropic` is a
  real pyproject dependency now (survives `uv sync`). `ANTHROPIC_API_KEY` in gitignored
  `.env` (`set -a; source .env; set +a` before judge-spending commands).
- TwinCore stack: API `localhost:8000`, twin slug `evalyn`, consent calls are metered
  (cap 500/month), chat 30 req/min. **Nothing spends sessions or judge tokens without
  explicit user consent.**
- Git: `dev` = integration, feature branches off `dev`, PR back to `dev`; commits under
  the user's identity, no Claude trailer; ask before every push/PR/branch-delete.
  Docs-only changes may commit directly on `dev`.
