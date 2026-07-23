# Session handoff — Plan #1 pre-merge fix bundle (2026-07-23)

**Purpose:** everything a fresh session needs to finish Plan #1. The previous session executed
all 14 tasks of `docs/superpowers/plans/2026-07-22-evalyn-gate-foundation.md` via
subagent-driven development and ran two final whole-branch reviews. Verdict: **merge WITH
FIXES** — a user-approved 10-item fix bundle remains, then the branch close-out.

## Repo state (verified at handoff)

- Branch: `feat/gate-foundation` (24+ commits off `dev`, merge-base `93483c6`). **Not pushed.**
- Working tree clean; full suite **69/69 passing**; `ruff check src/` clean;
  `evalyn validate-pack packs/example` → exit 0. DoD of Plan #1 is met and journaled.
- A previously started fixer was stopped; its partial (test-only, uncommitted) edits were
  discarded. Nothing of the fix bundle is applied yet.

## The work: the 10 fixes

**Source of truth: `docs/JOURNAL.md` → section "Final whole-branch reviews (2026-07-23)"** —
the checklist there is the exact user-approved scope (each item small; TDD per fix; ONE commit).
Acceptance: full suite green (~75+ tests), `ruff check src/ tests/` BOTH clean, example pack
still validates clean.

After the fixes: re-run the acceptance trio (pytest, ruff, validate-pack), update the journal
(check off the bundle), then use **superpowers:finishing-a-development-branch** for the
merge/PR decision. Two design-level gaps were explicitly deferred — see the journal's
"Plan #2 — Design gaps deferred from Plan #1" section; do NOT attempt them in this bundle.

## Working rules (locked by the user — do not deviate)

- **Subagent model policy: Fable for implementers/fixers AND reviewers** (set explicitly in
  every Agent dispatch; also in auto-memory `sdd-subagent-model-policy`).
- **Git:** commits ONLY as
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit ...`
  — NO Co-Authored-By/Claude trailer. **Never push / never open a PR without explicit user
  approval.** Conventional-commit prefixes.
- **uv only** (`~/.local/bin/uv`); system python3 is 3.9 — always `uv run ...`.
- **Verification before completion:** run tests/lint and show real output before claiming done.
- Don't commit `runs/` artifacts, baselines, or `.superpowers/` scratch.

## Kickoff prompt for the new session

> Read `docs/2026-07-23-handoff-premerge-fixes.md` first, then `docs/JOURNAL.md` (especially
> the "Final whole-branch reviews (2026-07-23)" section — the 10-item user-approved fix
> bundle — and the working rules in the handoff doc; also skim `docs/CONTEXT.md` if you need
> product orientation). Then: dispatch ONE Fable fixer subagent (superpowers:
> subagent-driven-development conventions, superpowers:test-driven-development inside it) to
> apply all 10 fixes as ONE commit under my git identity (no trailers, never push). When it
> reports, have a Fable reviewer verify the fix commit against the checklist, run the
> acceptance trio yourself (`uv run pytest -q`, `uv run ruff check src/ tests/`,
> `uv run evalyn validate-pack packs/example`) and show me the output, update
> `docs/JOURNAL.md` (check off the bundle, note the commit), and then walk me through
> superpowers:finishing-a-development-branch — I decide on push/PR.
