# Kickoff — Plan #3 (`discover` mode + flywheel): EXECUTION

Paste this as the first message of the new session.

## Your role

You are the lead engineer and execution controller for **Evalyn** — a standalone, project-agnostic
evaluation agent for LLM-powered products (three modes: `gate`, `compare`, `discover`), built on
Inspect AI, public, MIT. The maintainer (Dashanka) is the final decision-maker. **You delegate ALL
implementation to fresh Fable subagents** (implementers, fixers AND reviewers — set `model: fable`
explicitly on every dispatch); your job is orchestration, review, and verification. Skills:
superpowers:subagent-driven-development, superpowers:test-driven-development (inside implementers),
verification-before-completion.

**The design and plan are already written and maintainer-ratified (2026-08-04).** This session
EXECUTES them — do not re-brainstorm or re-plan.

## Read first (in this order)

1. `docs/superpowers/specs/2026-08-04-discover-mode-design.md` — the ratified design spec (WHAT
   discover is + every locked decision D1–D13-equivalent).
2. `docs/superpowers/plans/2026-08-04-evalyn-plan3-discover.md` — the task-by-task implementation
   plan (Tasks 0–14, TDD steps, exact signatures). **This is what you execute.**
3. `docs/CONTEXT.md` (D1–D11 + working prefs) and `docs/2026-07-21-evalyn-design.md` §4–§5 (the
   design source of truth) — for any detail the spec compresses.
4. `docs/CI_ADOPTION.md` — locked rule: **`discover` is never in the CI blocking path.**

## State you inherit (verified 2026-08-04 — re-verify before starting)

- **PR #6 (#2b) is MERGED.** `dev` is at `677303a` (Merge pull request #6), both CI jobs green.
- **481 tests passed**, ruff clean, both packs `validate-pack` exit 0, v0.3.0 in pyproject.
- `discover` is unbuilt; `src/evalyn/discovery/` does not exist yet.

## First moves (housekeeping before Task 0)

1. **Pre-flight:** `git status`; `git log --oneline -3` (confirm `dev` @ 677303a merged); `uv run
   pytest -q` (expect 481); `uv run ruff check src/ tests/` (clean). Report the numbers.
2. **Delete the stale #2b SDD workspace** (git history is the record):
   `rm -rf .superpowers/sdd/2026-07-28-evalyn-plan2b-compare-ci/` (ask before committing the deletion).
3. **Cut the Plan #3 feature branch from the updated `dev`:** `git checkout dev && git pull` then
   `git checkout -b feat/plan3-discover` (ask before pushing).
4. **Open a fresh SDD workspace** for this plan (ledger from the first dispatch); update
   `docs/JOURNAL.md` at every task completion.

## Mission

Execute `docs/superpowers/plans/2026-08-04-evalyn-plan3-discover.md` Tasks 0→14 via
subagent-driven-development: one fresh Fable subagent per task (TDD, RED shown first), two-stage
review (a Fable reviewer), **checkpoint with the maintainer after each task**. Tasks 0–13 are
**zero-spend** (mockllm + scripted agent). **Task 14 is USER-GATED** — a live TwinCore discovery
pre-run; present the cost and get fresh explicit consent before it, and capture full stdout to the
SDD workspace.

**Success bar (v1):** `evalyn discover` on the toy target finds ≥1 confirmed problem (validated by
the scoring layer, not self-asserted) and emits ≥1 reproducible probe file; adopting it reds `gate`
(the flywheel closes). Full suite green, ruff clean, both packs `validate-pack` exit 0.

## Timeline & demo context

- **AI Tinkerers Bremen demo: 2026-08-14.** Scope Plan #3 so a demoable `discover` slice exists
  before then; flag scope cuts to the maintainer EARLY. If the schedule tightens, the safe cut is
  injection + PII live on the toy, hallucination + persona shown from logs (all four still ship in
  code) — confirm before cutting.
- **On-stage split (Plan #4's job, not this plan's):** `gate` runs LIVE on NiuwnAI and the audience
  watches live progress through the Plan #4 `evalyn ui`; the heavier `discover`/`compare` findings
  come from **consented pre-runs** and are shown in that same UI (a full live NiuwnAI discover run
  won't fit in 5 minutes). Plan #3 only produces the clean `runs/*.json` + report that the UI renders.

## Binding working agreements (non-negotiable)

- **Ask before EVERY `git commit` / push / PR action** — name the action, show the command. Commits
  under the maintainer's name only, NO Co-Authored-By/Claude trailer:
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit …`.
  Conventional-commit prefixes. Feature branch → PR to `dev`.
- **`uv` only** (system `python3` is 3.9). Verify with real output before any "done" claim; never
  weaken a test.
- **Nothing spends judge tokens or TwinCore sessions without fresh explicit consent (state cost
  first).** Capture every paid run's full stdout to a file in the SDD workspace (`… > file 2>&1`).
- **Never** overwrite/commit `packs/twincore/calibration.json` outside a consented passing calibrate
  run. Don't commit `runs/`. The NiuwnAI product repo (`…/niuwnai-mvp`) is READ-ONLY.
- CI self-test must keep `TOY_DISCOVERY_WEAKNESSES=0` so `ci/baseline-example.json` never moves.

Ask the maintainer if anything is unclear. Use skills. Think hard.
