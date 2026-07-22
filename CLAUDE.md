# Evalyn

Standalone, project-agnostic **evaluation agent for LLM-powered products** (three modes: `gate`,
`compare`, `discover`). Built on Inspect AI. Public, MIT-licensed. Currently **pre-code** — docs and
plans only; Plan #1 (the `gate` foundation) is written and next to build.

## Source-of-truth docs (read on demand — don't duplicate them here)

- `docs/CONTEXT.md` — orientation, locked decisions, working preferences. **Read first each session.**
- `docs/2026-07-21-evalyn-design.md` — full technical design (what Evalyn is).
- `docs/ROADMAP.md` — how the 3 plans stage; what's in each.
- `docs/superpowers/plans/` — the executable, task-by-task plans (Plan #1 lives here).
- `docs/EVALYN_EXPLAINED.md` — plain-English overview.
- `docs/JOURNAL.md` — progress journal: task status, deferred findings register, decisions.
  **Update at every task completion**; triage its open items at each plan's final review.

## Environment & commands

- Package manager is **`uv`** (`~/.local/bin/uv`); project venv is `.venv` (Python 3.12).
  **Gotcha:** system `python3` is 3.9 — too old for Inspect. Always go through `uv run` / `.venv`.
- Once the package exists (Plan #1): `uv sync` (install), `uv run pytest -q` (tests),
  `uv run ruff check src/` (lint), `uv run evalyn ...` (CLI).
- The practice target runs via `uv run python examples/toy_target.py` (serves `127.0.0.1:8899`);
  point the engine at a target with the `EVALYN_TARGET_URL` env var.

## Git & branch conventions — IMPORTANT

- Remote: `origin` → https://github.com/DashankaNadeeshanDeSilva/evalyn
- **Dev-integration model:** `main` = stable release; `dev` = integration. **All work goes on a
  feature branch cut from `dev`, merged back to `dev` via PR.** Never commit work straight to `main`
  (or `dev`).
- **YOU MUST commit only automatically. ASK for explicit approval before every `git push` and before
  opening/updating any PR.**
- **All commits under the user's name only — NO `Co-Authored-By` / Claude trailer:**
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit ...`
- Conventional-commit prefixes: `feat:`, `docs:`, `test:`, `fix:`, `chore:`.

## Architecture constraints (non-obvious — honor these)

- **Build on Inspect AI; do not hand-roll the eval spine.** Probe suite → Inspect `Task`; session
  driver → `Solver`; each scoring tier → `Scorer`; a run → an Inspect eval log. Pin
  `inspect_ai>=0.3.249`.
- **Per-probe pass/fail policy lives in Evalyn's own gate-diff layer**, not in Inspect (Inspect
  reducers are task-level). Safety-critical probes gate on **pass^k** (all trials pass).
- **External HTTP is async `httpx` only** (never blocking `requests`); bound with Inspect
  `concurrency()`.
- **Judge ≠ generator family by default** (avoid self-preference bias).
- **Target allowlist is enforced** — a run refuses any `base_url` not allowlisted in the pack.

## Working style

- Quality over speed. Delegate heavy reading/searching to subagents; return conclusions, not dumps.
- **Verification before completion:** run the tests/lint and show real output before claiming done —
  evidence, not assertions.
