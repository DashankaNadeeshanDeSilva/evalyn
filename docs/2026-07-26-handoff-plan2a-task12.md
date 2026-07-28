# Session-4 kickoff — Evalyn Plan #2a: Task 12 → 13 → final review → PR

Paste this whole document as the opening prompt of the new session (or tell the agent to
read it and follow it).

---

## Your role

You are the **lead engineer and execution controller for Evalyn** — a standalone,
project-agnostic evaluation agent for LLM-powered products (`gate`, `compare`, `discover`),
built on Inspect AI, public and MIT-licensed. You work with me — the maintainer and final
decision-maker — and you **delegate every implementation task to a fresh Fable subagent**
rather than coding it yourself. Your job is orchestration, review, verification, and keeping
the plan honest.

## Your mission

**Finish Plan #2a: Task 12 → Task 13 → final whole-branch review → push + PR to `dev`
(ask first).** Sessions 1–3 completed Tasks 1–11; every task was reviewed,
controller-verified, and committed. You pick up on a green branch with the human-gated
calibration checkpoint (Task 11) DONE — the rubric judge is calibrated at 88%.

## Source documents (read these first)

| Document | What it is |
|---|---|
| `docs/superpowers/plans/2026-07-24-evalyn-plan2a-real-gate.md` | **The authoritative worklist** — Task 12 at the `## Task 12:` heading, Task 13 at `## Task 13:`. |
| `docs/superpowers/specs/2026-07-24-evalyn-plan2a-design.md` | Design rationale. |
| `docs/CONTEXT.md` | Orientation, locked decisions, working preferences. |
| `docs/JOURNAL.md` | **The committed execution record** — Plan #2a task table (Tasks 1–11 with SHAs), the four pre-flight amendments, and the live **deferred-findings register** (main input to the final review). |
| `docs/ROADMAP.md` | Task 13 must record the #2a/#2b split here. |
| `.superpowers/sdd/progress.md` | Gitignored session ledger. Plan #2a section starts at `# SDD progress ledger — Plan #2a trusted gate on real product`. Sessions 1–3 history is all there. |
| `.superpowers/sdd/plan2a-constraints.md` | Global Constraints + Shared `CheckResult` Contract handed to every implementer and reviewer. Recreate from plan lines 15–57 if missing. |
| `.superpowers/sdd/2026-07-24-evalyn-plan2a-real-gate/` | The plan's SDD workspace: task briefs/reports, review packages, and session-3 scratch tools (see below). |

## Environment & commands

- Package manager **`uv`** (`~/.local/bin/uv`); venv `.venv` (Python 3.12).
  **Gotcha:** system `python3` is 3.9 — always `uv run …`.
- `uv sync` / `uv run pytest -q` / `uv run ruff check src/ tests/` /
  `uv run evalyn gate|calibrate|validate-pack …`.
- **`ANTHROPIC_API_KEY` lives in `.env` at the repo root** (gitignored; contains my real
  key — never print or commit it). Shell state doesn't persist between Bash calls, so
  prefix any judge-spending command with: `set -a; source .env; set +a; …`.
- **`anthropic` package is venv-only** (`uv pip install anthropic`, done in session 3).
  `uv sync` WILL DROP IT until Task 12 adds it to pyproject — re-install if judge calls
  suddenly fail with "pip install anthropic".
- Env vars: `EVALYN_TARGET_URL` (target base URL), `EVALYN_TWIN_SLUG` (TwinCore slug,
  default `eval-twin`; the live twin is `evalyn`).
- TwinCore product repo (READ-ONLY, never modify):
  `/Users/dashankadesilva/Drive/Projects/NiuwnAI/niuwnai-mvp`, branch `dev`.

## Live TwinCore stack (running on my machine)

- API on `http://localhost:8000` (frontend :3000, db :5433, redis :6379, milvus :19530).
- Published twin: slug **`evalyn`** ("Evalyn Reed", 10 KB markdown files / 11 chunks in
  Milvus). Seeded owner: evalyn@example.com / user-id 2171f65d-5b3b-4cb1-8436-e301f11b4fd7.
- Flow: `GET /api/twin/evalyn` → `POST …/consent {"consent": true}` → `{"session_token"}`
  (Redis TTL 7200 s) → `POST …/chat {"message", "session_token"}` → SSE `token`/`error`/`done`.
- **Every consent call is one metered visitor session.** Cap raised to **500/month**
  (session 3 consumed ~22). Chat rate limit 30 req/min per session token.
- **NOTHING that spends live sessions or judge tokens runs without my explicit consent.**
  The first full gate run against the live twin (~120–150 sessions + a few $ judge spend)
  is pending and needs my go — likely during/after Task 13. It will also be the first
  real exercise of the `judge_usd` metering seam in a gate artifact — sanity-check and
  report it.

## Where the branch stands (verified 2026-07-26, end of session 3)

Branch **`feat/plan2a-real-gate`**, cut from `dev` @ `e30afbf`. Merge target: `dev` via PR
at plan end (ask first).

| Commit | Task | What landed |
|---|---|---|
| `6de3766`…`c2f1dde` | 1–10 | Sessions 1–2 (see JOURNAL task table) |
| `f314632` | — | docs: session-3 handoff |
| `6107596` | 11 pre | `run_calibration` bounded concurrency: keyword-only `max_concurrency: int = 4`, semaphore around the awaited judge call, `<1` → ValueError |
| `ab53694` | 11 | **20 human-labeled anchors + `calibration.json` (88% agreement) + rubric iterations + judge swap to `anthropic/claude-sonnet-5` + `packs/*/.cache/` gitignored** |

- **Push state: origin has up to `f314632`. `6107596` and `ab53694` are LOCAL ONLY** —
  pushing needs my explicit approval.
- Last verified green: **246 passed**, ruff clean, `validate-pack packs/twincore` exit 0
  (50 probes). Test-count trail: 197 @ T5 → 217 @ T6 → 225 @ T7 → 228 @ T8 → 236 @ T9 →
  243 @ T10 → 246 @ T11. Re-verify all three before dispatching anything.
- Zero open Critical/Important findings. All minors in the JOURNAL register with owners.

## Task 11 outcome (context you need)

- **Calibration PASSED: 88% (35/40 anchor×criterion pairs within ±1; threshold 0.85).**
  Per-criterion: persona 100/100, honesty 100/100, completeness 100/80, groundedness 60/60.
- Judge is **`anthropic/claude-sonnet-5`** — `claude-3-5-sonnet-latest` was retired
  upstream (404). User-approved successor; pinned in `calibration.json`; `target.yaml` and
  pack README updated. Running `gate`/`calibrate` with any other `--rubric-judge-model`
  makes calibration stale (fail-closed by design).
- It took 5 calibration runs + 4 rubric-wording iterations (60→75→78→82.5→88%). Root
  causes fixed in rubric text: the transcript-only judge treated unverifiable specifics as
  fabrication (groundedness) and honest "I'm an AI twin" acknowledgments as
  character-breaks (persona). The user also re-assessed 2 groundedness labels and
  contributed the decisive band-4 sentence (now verbatim in `rubrics/groundedness.md`).
- **Observed k=3 judge sampling noise: ±1 agreement band on untouched rubrics between
  runs.** 88% has margin; don't panic over small drift if recalibrating.
- 20 anchors in `packs/twincore/anchors/` (5 per rubric). Capture tooling lives in the
  SDD workspace: `capture_anchors.py` + `anchor_questions.yaml` (metered-session guard:
  refuses without `--yes`; `--only id,…` to re-capture a subset; never overwrites scored
  files) and `diag_calibration.py` (prints judge medians vs human labels per anchor —
  costs ~$0.20/run in judge tokens, needs `.env` sourced).
- Session-3 capture incident (contained, for awareness): a helper-verification step hit
  the live stack and burned 13 sessions; the 12 genuine transcripts were kept as anchors.
  The `--yes` guard exists because of this. Total session-3 judge spend ≈ $2.50.

## User rulings from session 3 (do NOT re-litigate)

- Commit-cadence grant re-confirmed: auto-commit per verified task; **ask before every
  push, PR, and branch deletion**. Re-confirm the grant at session start.
- Not-in-KB honesty classifiers **stay non-required** (score-weighted, band-moving; can't
  alone hard-fail the gate). Revisit only after live runs show judge reliability.
- Judge = `anthropic/claude-sonnet-5` (user chose the Sonnet successor over Haiku).
- **User design note (registered, deferred to Plan #2b / final-review triage):** the
  structural groundedness fix is injecting a condensed KB fact sheet into the groundedness
  judge's context (hashed with the rubric so staleness catches edits) — "give the judge
  the ground, don't lower the anchors." Don't implement in #2a unless the final review
  decides otherwise.

## Locked decisions & amendments (all implemented — do not re-litigate)

P1 per-criterion Tier-3; P2 scope semantics (`any_turn`/`all_turns`/`final`, fail-closed
defaults); P3 per-`solve()` httpx client (no cross-sample pooling); P4 `contains`
`values:` OR-list with XOR validation. Calibration ±1 per (anchor×criterion), ≥85%,
fail-closed; judge ≠ generator family (warning only); allowlist fail-closed; budget =
judge-spend only, post-hoc metering, no mid-run stop; artifact written before
BudgetExceeded raises; fingerprint over raw pack bytes; `state.*` → Plan #3; `compare`
mode + CI → Plan #2b. Interface details: see the session-3 handoff
(`docs/2026-07-25-handoff-plan2a-task11.md`, "Interfaces you will build on") — still
accurate, plus Task 11's `max_concurrency` param.

## Task 12 — CLI wiring + cleanup bundle (START HERE)

**A Task 12 implementer was dispatched in session 3 and STOPPED before making any
changes** (user hold). The tree is clean; re-dispatch fresh. The brief already exists:
`.superpowers/sdd/2026-07-24-evalyn-plan2a-real-gate/task-12-brief.md` (regenerate with
`scripts/task-brief` if in doubt). Controller dispatch notes that bind alongside the brief:

1. **Exit-2 mappings** (no tracebacks; `--debug` re-raises): old-schema-baseline
   `RuntimeError`; calibrate malformed-anchor raw `KeyError` (missing `rubric`/`transcript`);
   missing-rubric raw `FileNotFoundError`.
2. `event_format`/`stream` static validation **already landed in Task 6** — VERIFY it
   exists + is tested; don't duplicate.
3. **VERIFY (not implement)** Task 10's `${…}` resolution in `sessions.*.path` is
   test-pinned.
4. Loader hardening: narrow `except Exception` → `pydantic.ValidationError`; `${VAR}`
   set-but-empty semantics; lowercase env names in `_ENV_RE`; **decision made: add
   `extra="forbid"`** to schema models + typo'd-key test. (Anchor YAMLs have trailing
   comment blocks — not pydantic-validated, don't break `load_anchors`.)
5. Folded-in additions: CLI `--out-dir` on `gate` (threads `run_gate(out_dir=…)`); print
   `total_unsure_trials` in the human-readable gate report; thread `out_dir=tmp_path`
   through older run_gate tests that write CWD `runs/`; add
   `"claude-sonnet-5": (0.003, 0.015)` to `engine/budget.py` PRICES (keep the retired
   `claude-3-5-sonnet` key); **add `anthropic` to pyproject dependencies** (currently
   venv-only!) and `click>=8.2` floor.
6. Shared conftest fixtures (`minimal_pack`, `minimal_pack_with_probe`) extracted from
   `tests/test_cli.py` + `tests/engine/test_validate.py`; migrate Task 3's local helper.
   Scope = those files only.

## Task 13 — end-to-end acceptance

- Toy **named-sse** target added here.
- **BOTH design-gap proofs test-pinned e2e:** (a) multi-turn early leak FAILS the gate;
  (b) a non-required partial score moves a band (composed reducer→gate on one partial
  score, deferred from Task 3).
- e2e covers **both** `--allow-uncalibrated` **and** the stale-calibration exit-2 path.
- `validate-pack packs/example` and `packs/twincore` both exit 0.
- JOURNAL openers section emptied (each item done or re-deferred **with a reason**).
- `docs/ROADMAP.md` records the #2a/#2b split.
- The live gate run against TwinCore (user consent required — sessions + judge spend) is
  the natural acceptance companion here; ask the user when ready.

## Final whole-branch review (after Task 13)

- Base = `git merge-base dev HEAD`. Build the review package, dispatch on the **most
  capable model**. Point it at the JOURNAL register (~20 open minors, owners tagged).
  Session-3 additions to that list: Task 11 pre-flight test polish (cap `== cap`
  assertion, ValueError-before-work pin); KB-fact-sheet judge context (user note — triage,
  likely re-defer to #2b); k=3 sampling-noise observation. The compare-mode `model_usage`
  accumulation item is tagged **Plan #2b** — do not fix in #2a.
- ONE fix wave, one scoped re-review, adjudicate residuals.
- Then superpowers:finishing-a-development-branch → **push + PR to `dev` (ask first —
  `6107596` and `ab53694` are still unpushed)**.

## Process (locked — same machinery as sessions 1–3)

Use **superpowers:subagent-driven-development**. Per task:

1. Brief: `scripts/task-brief PLAN_FILE N` (from the skill's directory).
2. Fresh **Fable implementer** (explicit `model: fable`): brief path,
   `.superpowers/sdd/plan2a-constraints.md`, one paragraph of scene-setting, the task's
   dispatch notes above, superpowers:test-driven-development mandate, report-file path in
   the plan workspace. **Implementers stage but never commit.**
3. Diff package: `git diff --stat BASE` + `git diff -U10 BASE` + end marker into one
   workspace file, **excluding `docs/JOURNAL.md`**.
4. Fresh **Fable reviewer** (spec + quality, file:line evidence, don't trust the report,
   read-only).
5. Fix rounds → same implementer via SendMessage; scoped re-review by the same reviewer.
   Never fix in the controller.
6. Controller-verify pytest/ruff with real output, update JOURNAL (task row + register),
   commit, append ledger, move on.

## Working agreements (non-negotiable)

- **uv only**; commits under
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com'`,
  conventional prefixes, **no Co-Authored-By/Claude trailer**.
- Auto-commit per verified task (confirm at session start); **ask before every push, PR,
  branch deletion, live-session spend, and judge spend**.
- Verification before completion — real output, never weakened tests. Never commit
  `runs/`, baselines, `.superpowers/`, `.env`, or `packs/*/.cache/`.
- Inspect spine; gate policy in Evalyn's log-reading layer; async httpx only;
  judge ≠ generator family (warning); allowlist fail-closed.
- Surface plan divergences; one task at a time; checkpoint between tasks.

## Start now

1. Read the source documents + the ledger's Plan #2a section; confirm understanding in one
   short paragraph.
2. Verify green — `uv run pytest -q` (expect 246), `uv run ruff check src/ tests/`,
   `uv run evalyn validate-pack packs/twincore` — report the numbers.
3. Confirm the commit-cadence grant still holds.
4. Dispatch Task 12 (fresh implementer; brief + dispatch notes above) and run the loop.

Guide me step by step. Ask me if you have questions. Use skills.
