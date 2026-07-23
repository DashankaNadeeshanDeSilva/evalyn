# Plan #2 kickoff — make the gate real & trustworthy, plus `compare` (session handoff)

**Purpose:** everything a fresh session needs to start Plan #2. Plan #1 (gate foundation) is
**merged to `dev`** (PR #1, merge commit `d4ce297`, 2026-07-23) and fully journaled. Plan #2 has
a locked roadmap scope but **no written plan yet** — writing that plan (with the user, via
brainstorming) is this kickoff's first unit of work. Do not start coding from this document.

## 1. Read first, in this order

1. `docs/CONTEXT.md` — orientation, locked decisions, working preferences (session convention).
2. This file.
3. `docs/ROADMAP.md` § "Plan #2" — the authoritative scope (5 items, likely split #2a/#2b).
4. `docs/JOURNAL.md` — § "Plan #2 — Real product wiring + Tier-3 + compare": the two
   **must-address design gaps** and the full openers backlog. Also skim Plan #1's "Open items —
   deferred findings register" for carry-ins tagged Plan #2 (raw-sse fidelity, budget/auth/state
   consumers, adapter hardening).
5. `docs/2026-07-21-evalyn-design.md` — full technical design (Tier-3 / G-Eval, calibration,
   compare semantics live here).

## 2. State at kickoff (verified 2026-07-23)

- `dev` at `d4ce297`: **92/92 tests**, `ruff check src/ tests/` clean,
  `evalyn validate-pack packs/example` exit 0 (with the intended multi-turn-safety warning).
- Working `evalyn gate` / `evalyn validate-pack` against the practice target
  (`examples/toy_target.py`, port 8899), CI exit codes 0/1/2, self-contained run artifacts,
  baseline + gate-diff policy (safety = pass^k, capability never reds, bands vs baseline).
- `gate` auto-runs validate-pack (errors → exit 2) — landed post-review, already done from the
  Plan #2 openers list.
- Source map: `src/evalyn/` — `cli.py`, `engine/` (`validate.py`, `gate.py`, `run.py`,
  `solver.py`, `task_builder.py`, `streams.py`), `scoring/` (`tier1.py`, `tier2.py`),
  `targets/` (`schema.py`, `loader.py`). Tests mirror in `tests/`. Example pack `packs/example`.

## 3. Plan #2 scope (from ROADMAP — confirm, don't re-derive)

1. **Real TwinCore product wiring** as a target pack (real endpoints + stream format; port the
   31-case injection suite + grounding/persona/scope/PII probes from findings F-4/5/6/8/12).
2. **Tier-3 rubric judge** (G-Eval: judge writes its own grading steps first).
3. **Judge calibration harness** + human-labeled anchor set (≥85% agreement before trusting;
   re-check on every judge/rubric change).
4. **`compare`** — blind A/B, order-shuffled, per category, flip-means-tie.
5. **CI automation** — GitHub Action running `gate` on PRs, diffing committed baseline, posting
   a PR-comment summary.

ROADMAP itself says this stage is large and will likely split (#2a real-pack + Tier-3 +
calibration; #2b compare + CI). **Deciding the split is a brainstorming outcome, not a given.**

## 4. Must-address design gaps (user decision 2026-07-23 — non-negotiable in Plan #2)

1. **Transcript scoring:** scorers only read `state.output.completion` (final reply) — a leak in
   an earlier turn of a multi-turn probe passes the safety gate. Interim guard (validate-pack
   warning) is in place; the real fix walks all assistant turns in `state.messages`. Belongs
   with the Tier-3/scoring work.
2. **Weighted / non-required check semantics:** `Check.weight` and non-required checks are
   declarative-only today (documented as such in schema + README). Implement or explicitly kill.

## 5. Design questions to settle in brainstorming (before writing the plan)

- Transcript scoring semantics: which turns, per-turn vs whole-transcript verdicts, how per-turn
  failures aggregate into pass^k.
- Weight semantics: scoring formula for non-required checks, band interaction — or drop `weight`.
- Tier-3: G-Eval prompt shape, rubric source (pack-authored vs generated), score scale,
  judge-model policy (judge ≠ generator family is a locked constraint).
- Calibration: anchor-set size/format/storage, agreement metric, failure procedure.
- `compare` output contract + CLI shape; where flip-means-tie lives in the artifact.
- TwinCore pack: real stream format (raw-sse fidelity carry-ins from journal!), auth handling
  (A3 `auth`/`budget`/`state` fields get their consumers now), allowlist entries.
- Budget enforcement (`max_turns_per_session`, `max_usd_per_run`) — now has to become real.
- Which journal openers ride along (each is small): fingerprint over raw bytes, `out_dir`
  atomic artifacts, NOANSWER accounting, adapter/loader hardening bundles, CLI `--debug`,
  `click>=8.2` floor, pooled httpx client, tier-2 normalization hardening, tier-1 null-value
  guard, shared test fixtures.

## 6. Process (locked — same machinery that shipped Plan #1)

1. **superpowers:brainstorming** with the user → lock scope, the split decision, and the design
   answers above.
2. **superpowers:writing-plans** → `docs/superpowers/plans/<date>-evalyn-plan2*.md`.
3. Feature branch off `dev` (e.g. `feat/real-gate` / per split); **superpowers:using-git-worktrees**
   if isolation is wanted (Plan #1 ran in-place — fine).
4. **superpowers:subagent-driven-development**: fresh implementer per task → task review → user
   checkpoint cadence as agreed; **superpowers:test-driven-development inside every implementer**;
   final whole-branch review; **superpowers:finishing-a-development-branch** at the end.
5. `docs/JOURNAL.md` updated at every task completion; deferred findings into the register;
   triage at the final review.

## 7. Working rules (locked by the user — do not deviate)

- **Subagent model policy: Fable for implementers/fixers AND reviewers**, set explicitly in every
  dispatch; subagents invoke the relevant skills (TDD; review rubric). (Auto-memory
  `sdd-subagent-model-policy`.)
- **Git:** all work on a feature branch off `dev`, merged back to `dev` via PR. Commits ONLY as
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit ...`
  — no Co-Authored-By/Claude trailers. Commit automatically; **ask before every push and before
  opening/updating any PR.** Conventional-commit prefixes.
- **uv only** (`~/.local/bin/uv`); system python3 is 3.9 — always `uv run ...`.
- **Verification before completion:** run tests/lint and show real output before claiming done.
- Don't commit `runs/` artifacts, baselines, or `.superpowers/` scratch.
- Architecture constraints (CLAUDE.md): Inspect AI spine (pin `inspect_ai>=0.3.249`); per-probe
  gate policy stays in Evalyn's gate-diff layer; async `httpx` only; judge ≠ generator family;
  target allowlist enforced fail-closed.

## 8. Kickoff prompt for the new session

> **Role:** You are the lead engineer and execution controller for **Evalyn**, a standalone,
> project-agnostic evaluation agent for LLM-powered products (three modes: `gate`, `compare`,
> `discover`), built on Inspect AI. You work with me — the maintainer and final
> decision-maker — and you delegate implementation to Fable subagents rather than coding
> everything yourself.
>
> **Mission:** Deliver **Plan #2**: take the gate from "works on the practice product" to
> "trusted on the real product," and add Tier-3 judging, judge calibration, blind `compare`,
> and CI automation (authoritative scope: `docs/ROADMAP.md` § Plan #2; it will likely split
> into #2a/#2b — that split is ours to decide together).
>
> **Inputs — read in this order before anything else:**
> `docs/2026-07-23-plan2-kickoff.md` (this handoff; follow its reading list) →
> `docs/CONTEXT.md` → `docs/ROADMAP.md` § Plan #2 → `docs/JOURNAL.md` § Plan #2
> (must-address design gaps + openers) and Plan #1's deferred-findings register →
> `docs/2026-07-21-evalyn-design.md`.
>
> **Process (skills, in order):** superpowers:brainstorming with me to lock the split, the two
> must-address design gaps, and the kickoff doc's open design questions → design spec →
> superpowers:writing-plans → my approval of the plan → superpowers:subagent-driven-development
> (Fable implementers AND reviewers, superpowers:test-driven-development inside every
> implementer) → final whole-branch review → superpowers:finishing-a-development-branch.
>
> **Deliverables, in order:** (1) an approved design spec; (2) an approved task-by-task plan in
> `docs/superpowers/plans/`; (3) the executed plan on a feature branch off `dev` — full test
> suite and `ruff` green with real output shown, `docs/JOURNAL.md` updated at every task
> completion, branch ready for PR to `dev`.
>
> **Working agreements (non-negotiable):** ask me before every push, PR, branch deletion, or
> any other repo-state step — name the specific action; commits only under my git identity
> with no Co-Authored-By/Claude trailers; `uv` only (system python3 is too old);
> verification-before-completion — evidence, not assertions; docs-only changes go directly on
> `dev`, all code/config via feature branch + PR.
>
> **Start now** by confirming what you've read from the inputs (one short paragraph, no file
> dumps), then ask me your first brainstorming question — one question at a time.
