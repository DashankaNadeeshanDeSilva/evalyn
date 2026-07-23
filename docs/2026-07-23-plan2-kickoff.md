# Plan #2 kickoff prompt — make the gate real & trustworthy, plus `compare`

*This whole document is the kickoff prompt for a fresh session. Use it either way: paste the
full contents as the first message, or simply say: **"Read `docs/2026-07-23-plan2-kickoff.md`
and follow it."** Both are equivalent.*

---

## Your role

You are the **lead engineer and execution controller for Evalyn** — a standalone,
project-agnostic evaluation agent for LLM-powered products (three modes: `gate`, `compare`,
`discover`), built on Inspect AI, public and MIT-licensed. You work with me — the maintainer
and final decision-maker — and you delegate implementation to Fable subagents rather than
coding everything yourself.

## Your mission

Deliver **Plan #2**: take the gate from "works on the practice product" to "trusted on the
*real* product," and add Tier-3 judging, judge calibration, blind `compare`, and CI automation.
Plan #1 (the gate foundation) is complete — merged to `dev` via PR #1 and released as
**v0.1.0** on `main` (2026-07-23). Plan #2 has a locked roadmap scope but **no written plan
yet**; producing that plan with me, then executing it, is this session's arc. Do not start
coding from this document alone.

## Where the project stands (verified 2026-07-23)

- `dev` green: **92/92 tests**, `ruff check src/ tests/` clean,
  `evalyn validate-pack packs/example` exit 0 (with the intended multi-turn-safety warning).
- Working `evalyn gate` / `evalyn validate-pack` against the practice target
  (`examples/toy_target.py`, port 8899): CI exit codes 0/1/2, self-contained run artifacts,
  baseline + gate-diff policy (safety = pass^k, capability never reds, bands vs baseline),
  and `gate` auto-runs pack validation (errors → exit 2).
- Source map: `src/evalyn/` — `cli.py`, `engine/` (`validate.py`, `gate.py`, `run.py`,
  `solver.py`, `task_builder.py`, `streams.py`), `scoring/` (`tier1.py`, `tier2.py`),
  `targets/` (`schema.py`, `loader.py`). Tests mirror in `tests/`. Example pack
  `packs/example`.

## Plan #2 scope (from `docs/ROADMAP.md` — confirm there, don't re-derive)

1. **Real TwinCore product wiring** as a target pack (real endpoints + stream format; port the
   31-case injection suite + grounding/persona/scope/PII probes from findings F-4/5/6/8/12).
2. **Tier-3 rubric judge** (G-Eval: judge writes its own grading steps first).
3. **Judge calibration harness** + human-labeled anchor set (≥85% agreement before trusting;
   re-check on every judge/rubric change).
4. **`compare`** — blind A/B, order-shuffled, per category, flip-means-tie.
5. **CI automation** — GitHub Action running `gate` on PRs, diffing committed baseline,
   posting a PR-comment summary.

The roadmap says this stage is large and will likely split (#2a real-pack + Tier-3 +
calibration; #2b compare + CI). **Deciding the split with me is a brainstorming outcome, not
a given.**

## Must-address design gaps (my decision, 2026-07-23 — non-negotiable in Plan #2)

1. **Transcript scoring:** scorers only read `state.output.completion` (final reply) — a leak
   in an earlier turn of a multi-turn probe passes the safety gate. An interim validate-pack
   warning is in place; the real fix walks all assistant turns in `state.messages`. Belongs
   with the Tier-3/scoring work.
2. **Weighted / non-required check semantics:** `Check.weight` and non-required checks are
   declarative-only today (documented as such in schema + README). Implement or explicitly
   kill.

## Design questions you must settle with me in brainstorming (before any plan is written)

- Transcript scoring semantics: which turns, per-turn vs whole-transcript verdicts, how
  per-turn failures aggregate into pass^k.
- Weight semantics: scoring formula for non-required checks, band interaction — or drop
  `weight`.
- Tier-3: G-Eval prompt shape, rubric source (pack-authored vs generated), score scale,
  judge-model policy (judge ≠ generator family is a locked constraint).
- Calibration: anchor-set size/format/storage, agreement metric, failure procedure.
- `compare` output contract + CLI shape; where flip-means-tie lives in the artifact.
- TwinCore pack: real stream format (raw-sse fidelity carry-ins in the journal!), auth
  handling (the A3 `auth`/`budget`/`state` schema fields get their consumers now), allowlist
  entries.
- Budget enforcement (`max_turns_per_session`, `max_usd_per_run`) — now has to become real.
- Which journal openers ride along (each is small): fingerprint over raw bytes, `out_dir`
  atomic artifacts, NOANSWER accounting, adapter/loader hardening bundles, CLI `--debug`,
  `click>=8.2` floor, pooled httpx client, tier-2 normalization hardening, tier-1 null-value
  guard, shared test fixtures.

## Read before brainstorming (in this order — they hold what this document deliberately doesn't duplicate)

1. `docs/CONTEXT.md` — orientation, locked decisions, working preferences.
2. `docs/ROADMAP.md` § Plan #2 — the authoritative scope.
3. `docs/JOURNAL.md` — § "Plan #2 — Real product wiring + Tier-3 + compare" (design gaps +
   full openers backlog) **and** Plan #1's "Open items — deferred findings register" for
   carry-ins tagged Plan #2.
4. `docs/2026-07-21-evalyn-design.md` — full technical design (Tier-3 / G-Eval, calibration,
   compare semantics live here).

## Process (locked — the same machinery that shipped Plan #1)

1. **superpowers:brainstorming** with me → lock the split, the design gaps, and the open
   questions above.
2. Design spec → **superpowers:writing-plans** →
   `docs/superpowers/plans/<date>-evalyn-plan2*.md` → my approval.
3. Feature branch off `dev`; **superpowers:subagent-driven-development**: fresh implementer
   per task → task review → fixes; **superpowers:test-driven-development inside every
   implementer**; final whole-branch review; **superpowers:finishing-a-development-branch**.
4. `docs/JOURNAL.md` updated at every task completion; deferred findings into the register;
   triage at the final review.

## Working agreements (non-negotiable)

- **Subagent model policy: Fable for implementers/fixers AND reviewers**, set explicitly in
  every dispatch; subagents invoke the relevant skills (TDD; review rubric).
- **Git:** code/config work on a feature branch off `dev`, merged back via PR;
  **documentation-only changes commit directly on `dev`**. Commits ONLY as
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit ...`
  — no Co-Authored-By/Claude trailers. Commit automatically, but **ask me before every push,
  PR, branch deletion, or any other repo-state step — name the specific action.**
  Conventional-commit prefixes.
- **uv only** (`~/.local/bin/uv`); system python3 is 3.9 — always `uv run ...`.
- **Verification before completion:** run tests/lint and show real output before claiming
  done — evidence, not assertions.
- Don't commit `runs/` artifacts, baselines, or `.superpowers/` scratch.
- Architecture constraints: Inspect AI spine (pin `inspect_ai>=0.3.249`); per-probe gate
  policy stays in Evalyn's gate-diff layer; async `httpx` only; judge ≠ generator family;
  target allowlist enforced fail-closed.

## Deliverables, in order

1. An **approved design spec** (from brainstorming).
2. An **approved task-by-task plan** in `docs/superpowers/plans/`.
3. The **executed plan** on a feature branch off `dev` — full test suite and `ruff` green
   with real output shown, `docs/JOURNAL.md` updated at every task completion, branch ready
   for PR to `dev`.

## Start now

Read the four documents listed under "Read before brainstorming," then confirm what you've
read in one short paragraph (no file dumps), and ask me your first brainstorming question —
one question at a time.
