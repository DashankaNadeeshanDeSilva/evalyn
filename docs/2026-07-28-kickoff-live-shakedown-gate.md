# Kickoff — first LIVE gate run against TwinCore (shakedown)

## Your role

You are the lead engineer and execution controller for **Evalyn** (standalone eval agent for
LLM products, built on Inspect AI). You work with me — the maintainer and final
decision-maker. Your mission in this session is exactly one thing: **run the first live
`evalyn gate` against the real TwinCore product, as a shakedown, and analyze the results.**
No feature work, no Plan #2b tasks — those come later.

## Read first (in this order)

1. `docs/2026-07-28-plan2b-supplementary-context.md` — **supersedes all Plan #2a-era
   assumptions**; lists the post-review semantics (per-rubric calibration gating,
   INCOMPLETE verdicts, no-signal trials, strict judge parsing, baseline guards, …).
2. `docs/CONTEXT.md` — orientation and locked decisions.
3. `docs/JOURNAL.md` — Plan #2a section: the deferred-findings register holds the
   live-run caveats you must watch for (listed again below).
4. `packs/twincore/README.md` — the pack you are about to run.

## State you inherit (verified 2026-07-28)

- Branch `dev` @ `f6be671` (Plan #2a merged via PR #4 after two review rounds).
  **340 tests green, ruff clean, `validate-pack packs/twincore` exit 0** — re-verify all
  three before anything else and report the numbers.
- **The committed TwinCore calibration record is deliberately STALE** (per-rubric gating;
  groundedness at 60%). This is correct and by design. Therefore this run REQUIRES
  `--allow-uncalibrated` and is a **shakedown**: safety verdicts are fully trustworthy
  (deterministic Tier-1 redirect-constant / tripwire / PII checks), quality bands are
  indicative-only and will be loudly bannered as UNTRUSTED in the report.
- The judge model is pinned: `anthropic/claude-sonnet-5` (in `target.yaml` and the
  calibration record). **Do not override the rubric judge model** — any other model makes
  calibration staleness worse, and the PRICES table prices sonnet-5 correctly. For the
  Tier-2 classifier judge, use `anthropic/claude-sonnet-5` too (it is priced in the
  budget table; an unpriced model falls back to opus-tier pricing + RuntimeWarning and
  could spuriously trip the $5 cap). Judge≠generator family holds: TwinCore's twin is
  GPT-powered.

## Environment

- **`uv` only** — system python3 is 3.9. `uv run pytest -q`, `uv run evalyn …`.
- `ANTHROPIC_API_KEY` lives in gitignored `.env` at repo root (never print/commit it).
  Shell state does not persist between commands: prefix judge-spending commands with
  `set -a; source .env; set +a; …`.
- Live TwinCore stack (must already be up on my machine): API `http://localhost:8000`,
  twin slug **`evalyn`**. Flow: `GET /api/twin/evalyn` (unmetered — fine for a health
  check) → consent → chat (SSE). Env vars the pack resolves: `EVALYN_TARGET_URL`
  (set to `http://localhost:8000`) and `EVALYN_TWIN_SLUG` (set to `evalyn`).
- READ-ONLY product repo (never modify, never needed this session):
  `/Users/dashankadesilva/Drive/Projects/NiuwnAI/niuwnai-mvp`.

## Cost reality — every step below the line spends my money/quota

- **Every consent call = one metered visitor session.** The run consumes ~**150 sessions**
  (50 probes × 3 pack-wide epochs — `validate-pack` prints this warning). Monthly cap:
  500. Confirm with me how many sessions remain before running.
- **Judge spend:** Tier-2 classifiers + Tier-3 rubrics at k=3 on ~150 trials, sonnet-5.
  Pack cap `max_usd_per_run: 5.00`; metering is **post-hoc** (no mid-run stop) — the cap
  bounds what a run may have spent, checked after. Expect a few dollars.
- **Chat rate limit:** 30 req/min per session token; Evalyn's concurrency is bounded via
  Inspect `concurrency()` — do not raise pack concurrency.

## Protocol (strict)

1. **Pre-flight (no spend):** verify green (pytest/ruff/validate-pack); check the stack
   answers (`curl -s http://localhost:8000/api/twin/evalyn | head -c 200`); confirm `.env`
   has the key; run `uv run evalyn gate --help` and read the actual flags — do not guess
   CLI syntax. Confirm the grading-steps cache `packs/twincore/.cache/` exists (warm from
   calibration) and note whether it's populated.
2. **ASK ME FOR EXPLICIT GO before the run command.** Present: the exact command line you
   will execute, expected session consumption, expected judge spend. **NOTHING that spends
   sessions or judge tokens runs without my explicit consent — including retries.** One
   run only; if it fails, diagnose fully before proposing (and asking about) another.
3. **The run** (shape — verify flags against `--help` first):
   ```bash
   set -a; source .env; set +a; \
   EVALYN_TARGET_URL=http://localhost:8000 EVALYN_TWIN_SLUG=evalyn \
   uv run evalyn gate --target packs/twincore --allow-uncalibrated \
     --judge-model anthropic/claude-sonnet-5 --out-dir runs/
   ```
   Exit 1 (gate FAIL) is a *plausible, informative* outcome — analyze, don't panic.
   Exit 2 means setup/infra — diagnose before any re-spend.
4. **Post-run analysis (the actual deliverable):**
   - **`judge_usd` sanity check** — first real exercise of the metering seam. Compare the
     artifact's `judge_usd` against the Anthropic console's actual spend for the window;
     report both numbers and the delta.
   - **Grading-steps cache** — confirm the run HIT the calibration-warmed cache
     (`packs/twincore/.cache/`) rather than regenerating steps (this validates the PR-fix
     that threaded `cache_dir` through `run_gate`).
   - **Verdict walk-through:** per failed probe, classify — real product failure vs known
     caveat. Known caveats from the register: **Guardian BOUNDARY classification** (a safe
     block with owner-custom redirect text matches none of the three redirect constants →
     required `contains` fails on a SAFE reply — fail-loud by design); the byte-exact
     Guardian-prompt **tripwires** on `injection-multiturn-trust-pivot`; the narrow
     `first-person` invariant; k=3 judge sampling noise (±1 band).
   - **New-semantics check:** any MISSING/INCOMPLETE probes (transient 502s now surface —
     that's correct behavior, count them); `total_unsure_trials`; both UNTRUSTED banners.
   - **Baseline: DO NOT bless.** `--update-baseline` would refuse this artifact
     (untrusted) and that refusal is correct — do not use `--force-baseline`. The first
     blessed baseline comes after #2b recalibration.
5. **Record:** update `docs/JOURNAL.md` — a "first live run" entry (numbers, failures
   classification, metering delta, cache behavior) and close/annotate the register items
   this run exercises (`_judge_usd` seam never exercised with billable usage; BOUNDARY
   caveat observed-or-not). Commit docs on `dev` (docs-only exception). The run artifact
   in `runs/` is **gitignored — never commit it**; quote numbers into the JOURNAL instead.

## Ground rules (non-negotiable)

- Commits under
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com'`,
  conventional prefixes, no Claude trailer. Docs-only commits go straight on `dev`;
  **ask before any push**.
- Never commit: `runs/`, `.env`, `packs/*/.cache/`, `.superpowers/`.
- Never modify: `packs/twincore/calibration.json`, `packs/twincore/anchors/`, anything in
  `niuwnai-mvp`.
- Verification before claims: real command output, always.
- If the stack is down or the key is missing, STOP and tell me — do not improvise
  against other endpoints.

## Start now

1. Read the four docs above; confirm your understanding of "shakedown, not trust
   demonstration" in one short paragraph.
2. Run the pre-flight (no spend) and report.
3. Present the run command + cost estimate and **wait for my explicit go**.
