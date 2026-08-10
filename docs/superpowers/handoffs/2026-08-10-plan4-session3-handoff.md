# Plan #4 (`evalyn ui`) — session 3 handoff

**Written 2026-08-10.** Previous handoff: `2026-08-07-plan4-session2-handoff.md` (on `dev`).
Read that only for history — this document supersedes it.

**The demo is 2026-08-14. Four days.**

---

## 1. Read these, in this order

1. **`.superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md`** — the ledger. Every task outcome,
   every controller ruling (R4-6 … R4-17), every constraint carried forward. **This is the recovery
   map.** If you read nothing else, read this.
2. `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/DEMO-READINESS-AUDIT.md` — cut analysis, the true
   dependency graph, and the file-collision map that governs what can run in parallel.
3. `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/INJECTION-PACK-PLAN.md` + `BASELINE-PLAN.md` — why
   the demo pack exists and what the one billed run must answer.
4. `PRODUCT.md` (repo root) and `.impeccable/surfaces/ui-src.md` — product truth and the design
   direction. **Read the surface brief before writing any page task (8, 9, 15, 16, 17, 21).**
5. `docs/superpowers/plans/2026-08-07-evalyn-plan4-ui.md` — the 22-task plan itself.

---

## 2. Where things stand

**Branch `feat/plan4-ui`**, cut from `dev` @ `8f3e2de`. **Nothing pushed. No PR opened.**

| Task | State |
|---|---|
| 0 — spike | complete (2026-08-07) |
| 1 — freeze API contract | complete, review-clean (`82baacf..2e0cade`) |
| 2 — `run_id` + paths | complete, review-clean (`6a3ae93`) |
| 3 — `RunIndex` | complete, review-clean (`14d23d0`, `d2e8e8e`, fix `05db131`) |
| 4 — redaction chokepoint | **implemented this session; REVIEW IS THE NEXT SESSION'S FIRST ACTION** |
| 5 — frontend scaffold | complete, review-clean; **merged** at `887bfe1` |
| injection pack | free scope complete (`4daddf0`, `797c8cf`) — **new work, not a plan task** |
| 6–21 | not started |

**Tests: 726 → 1021** (before Task 4's additions), warning-clean in both colour modes, ruff clean.

`dev` is **2 commits ahead of `origin/dev`** and unpushed (`8f3e2de`, `5de0515` — both docs).

**Uncommitted in the working tree, deliberately:**
- `docs/superpowers/handoffs/2026-08-07-plan4-ui-kickoff.md` — the maintainer's own edit, never staged
- `PRODUCT.md` and `.impeccable/` — design artifacts created this session. **Decide whether to commit
  them.** They hold real decisions; my inclination is yes, as a docs commit.

**Worktree `../Evalyn_frontend_lane`** still exists but is merged and no longer needed —
`git worktree remove` it when convenient.

---

## 3. ⚠️ Blocked on the maintainer — the billed run

The injection pack is built, guarded and staged. **One billed run is approved** (~$0.11–0.30, $1.00
envelope). It cannot fire because of a data gap, not a code problem:

- niuwnai-mvp is **up and healthy** (verified: frontend :3000, api :8000, db :5433, redis, milvus).
- `POST /api/twin/eval-twin/consent` returns a clean `{"detail":"Twin not found."}` HTTP 404 — the
  app answering correctly.
- **No twin with slug `eval-twin` exists.** The pack defaults to it via `${EVALYN_TWIN_SLUG:-eval-twin}`.
- The three archived twincore artifacts do **not** record the slug used on 2026-07-28.
- `ANTHROPIC_API_KEY` is in the repo `.env` but **not exported**; `demo.sh` checks the environment.
  Run `set -a; source .env; set +a` first so the value is never echoed.

**To unblock:** get the correct slug (`EVALYN_TWIN_SLUG=<slug> ./packs/twincore-injection/demo.sh bless`)
or create a twin with slug `eval-twin` and run the script unchanged. The latter was recommended — it
keeps `demo.sh` self-contained with nothing to remember on stage.

**The maintainer said (2026-08-10, end of session 3) that they will set the twin up and bring the
details into the NEXT session.** So expect to receive the slug early in session 4.

> ⚠️ **Re-confirm before spending.** The approval above was given in session 3, in a conversation
> that has ended. **Do not treat this document as authorisation to bill.** State the cost, state what
> the run will answer, and get a fresh yes in the new session before running `bless`. A prior
> session's approval is context, not consent.

**The run must answer three questions, not one:** (1) is the gate red today and on which probes,
(2) **which probes are currently green**, (3) real wall-clock. **Screen-record it** — one billed run
yields the baseline, the break-glass capture, and the true timing.

**Do not auto-bless.** Read the verdict first; `injection-exfil-boundaries` is inside this subset and
was at `pass^k = 0.0`, so blessing blind would enshrine a FAIL as known-good.

**Approval is for ONE run.** The rehearsal run and the live-day run each need a fresh go-ahead.

---

## 4. Scope decision on record

**2026-08-10: the maintainer was shown the demo-readiness audit — which concluded 20 tasks in 4 days
is not achievable and that Tasks 18–21 are not asked for by the demo proposal — and chose to attempt
all 20 anyway.** That decision stands; do not re-litigate it.

**Controller obligation from that ruling: sequence 18–21 LAST.** They are the tasks the proposal
doesn't ask for, and Task 18 edits `engine/run.py`, `solver.py`, `task_builder.py`, `compare.py` and
`discovery/*` — the code path the green terminal fallback runs through. They are what should fall off
the end if time runs out.

The maintainer separately confirmed the cockpit **is** a control surface (launch/pause/cancel is
durable product truth), so 18–21 are not cuttable long-term — only deprioritised for the demo.

---

## 5. Next actions, in order

1. **Review Task 4** (redaction chokepoint). It was implemented but not reviewed.
   Generate the package with `scripts/review-package <plan> <base> <head>`.
2. **Task 6** — `evalyn ui` command + app skeleton. Needs 3, 4, 5 (all done).
   **It inherits Task 4's deferred Step 5** (the route-table test) — see §6.
3. **Task 7** — read endpoints. Then **8 → 9** (the page tasks; read the surface brief first).
4. Then 10, 11, 12, 13, 14, 15, 16, 17, and **18–21 last**.

---

## 6. Constraints that MUST travel forward

**Concurrency (from the audit — these are file-collision facts, not preferences):**
- **Two lanes maximum: one Python, one TypeScript.**
- `src/evalyn/ui/server.py` is created by Task 6 and *modified* by 7, 11, 12, 13, 14, 20 —
  **those six are strictly sequential**, worktrees or not.
- `ui/src/routes.tsx` + `AppShell` nav are created by 8 and edited by 9, 15, 16, 17, 21 —
  **15/16/17 are NOT parallel with each other**.
- The committed Vite bundle (`src/evalyn/ui/static/**`) is rebuilt by 5, 8, 9, 15, 16, 17, 21 —
  **this caps the TypeScript lane at ONE task**.
- **Never run two Python lanes that can bind port 8899** (R4-8). Concurrent binds already caused ~46
  `EADDRINUSE` failures in this repo.

**Per-task obligations:**
- **Task 6** — owns Task 4's deferred Step 5 (route-table test). Must state explicitly **which id it
  keys by**: the launcher knows `<id>` before the run, but a non-gate run indexes as
  `<id>-compare` / `<id>-discover`; events/control derive from the artifact stem while spec §4:147
  keys `runs/.evalyn-ui/<run_id>/` without a suffix (C-T6/7).
- **Task 7** — must keep the `evalyn.ui.index` import **lazy**: it pulls `starlette` transitively via
  `engine.run → inspect_ai`, and the no-web-framework baselines hold only because nothing imports it
  eagerly (C-T7b). Must also bound `RunIndex._cache`, which is unbounded and retains transcripts
  (F8), and map a `ValidationError` out of `.get()` to `unreadable_artifact`, not a 500 (F10).
- **Task 8** — **nav items MUST be gated on pages that actually shipped.** A legend listing four
  destinations that 404 reads as broken. Cheapest demo insurance available.
- **Task 10** — the base wheel **must** continue to contain `evalyn/ui/models.py` and
  `evalyn/ui/paths.py` (the engine imports `ui.models`), and must `force-include`
  `src/evalyn/ui/static/**`. Pin both with an `import evalyn.engine.run` assertion in the
  clean-install job (C-T10).
- **Task 17** — leave Step 5 (Vite drift check → hard fail) **advisory**. macOS↔Linux Vite
  byte-reproducibility is unverified; a hard fail on demo eve is self-inflicted.
- **Tasks 19/20** — `ui.paths` now owns `META_FILENAME` / `META_LAUNCHED_KEY` / `META_EXIT_CODE_KEY`;
  **import them, do not retype them**. And **write `meta.json` BEFORE the sidecar directory is
  observable** — `_sidecar` initialises `unrecognised = True`, so a launcher that mkdirs, spawns,
  then writes meta will make a healthy run flash `interrupted` (C-T19b).
- **Task 20** — Step 4's SIGTERM escalation is **stale**; R4-11 governs. Unacked cancel becomes an
  honest `interrupted` state. Spec §7 carries the same stale text.
- **Anywhere** — the run count is a **derived invariant, never a literal** (R4-6). Truth today is
  **80 indexed / 26 degraded**; the plan's "82 / 27" is wrong in four places.

**Working agreements:** `uv` only (system `python3` is 3.9); suite green and warning-clean in **both**
colour modes; all subagents on **Opus 5, set explicitly**; TDD with a **discriminating** red; stage
explicitly, never `git add .`; commits under the maintainer identity with **no Claude trailer**;
**ask before every push and any PR**.

---

## 7. Design direction (locked, maintainer-confirmed)

**THE BENCH INSTRUMENT** — surface roll key `3632f7e5`, index 7, fused with
`design-canon-creator-hardware-bench`. Full brief: `.impeccable/surfaces/ui-src.md`.

- **High-contrast light**, because projectors *add* light and dark UI projects as muddy grey — and
  because "dev tool → dark" is the category reflex.
- One continuous instrument face with **engraved panel lines; cards are NOT the organising device**.
- **One inset dark readout window** for live state — the only dark field, and the asymmetry that
  breaks the grid.
- **Safety orange rationed** to actions that spend money or interrupt. Nothing else may use it.
- Status colours stay **keyed to `RunStatus` enum members** so components cannot drift from the enum.
- **Never colour alone** — glyph + word + colour on every verdict (WCAG 2.1 AA is committed).
- Degraded rows read as **dead channels**: present, id legible, flat-lined, reason stated.
- **Anti-pastiche rule:** the bench supplies vocabulary and hierarchy, **never texture**. No bevels,
  faux screws, glass, or simulated materials. If a treatment exists only to look like hardware, cut it.
- Chassis greys are **cool, near-zero-chroma — NOT cream/sand/bone-warm/parchment** (that band is the
  saturated AI default).
- **DESIGN.md is deliberately not written yet** — impeccable authors it at finish, from the built
  world.

---

## 8. Things that must not be fabricated

`PRODUCT.md` records these; they are real absences an agent will be tempted to fill:

- **Zero `compare` artifacts exist in `runs/`.** A compare page renders an empty state against real
  data. Do not invent compare data.
- **No committed twincore baseline** (that is what the billed run produces).
- **`packs/example/discoveries/` holds only `.gitkeep`** — the discover fixture's `probe_path` points
  at an empty directory. Pin the missing-file degradation in Tasks 11–13.

---

## 9. Session-3 notes worth knowing

- **Transient API errors killed five agent runs mid-stream.** The mitigation that worked: instruct
  implementers to **commit each coherent piece as they finish it**. Agents that batched lost
  everything; agents that committed incrementally lost minutes. Keep doing this.
- Every task this session found a **real defect**: a phantom run from a `.control` sidecar passing
  `is_run_id`; a status-ordering bug where `unknown` outranked a real `GateResult`; a drift guard
  blind to field renames; `is_run_id` disagreeing with the `RunId` type on trailing newlines. The
  review loop is earning its cost — do not downgrade reviewer models.
- **Reviewers that re-ran mutations themselves caught what report-reading would have missed.** Ask
  for mutation evidence, then have the reviewer reproduce it.

---

## 10. Kickoff prompt for the next session

```
We're continuing Plan #4 — the `evalyn ui` cockpit. Demo is 2026-08-14 (AI Tinkerers Bremen).
Work on branch `feat/plan4-ui`.

Read first, in this order:
1. docs/superpowers/handoffs/2026-08-10-plan4-session3-handoff.md — full state transfer, START HERE
2. .superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md — the ledger; rulings R4-6 … R4-17
3. .superpowers/sdd/2026-08-07-evalyn-plan4-ui/DEMO-READINESS-AUDIT.md — true dependency graph +
   the file-collision map that governs what can run in parallel
4. PRODUCT.md and .impeccable/surfaces/ui-src.md — product truth + the locked design direction.
   Read the surface brief BEFORE any page task (8, 9, 15, 16, 17, 21).
5. docs/superpowers/plans/2026-08-07-evalyn-plan4-ui.md — the 22-task plan itself

State: Tasks 0, 1, 2, 3 and 5 complete and review-clean. The twincore-injection demo pack is carved,
guarded and staged. Suite 726 → 1021, warning-clean in both colour modes. Nothing pushed, no PR.
**Task 4 (redaction chokepoint) was IN FLIGHT when the last session ended — check `git log` and the
ledger for its outcome before doing anything else.**

First actions: (1) establish Task 4's true state and review it; (2) then Task 6 → 7 → 8 → 9.
Sequence Tasks 18–21 LAST — the demo proposal doesn't ask for them and Task 18 edits the engine
modules my working terminal fallback runs through. I chose to attempt all 20 remaining tasks knowing
an audit said it isn't achievable; that decision stands, don't re-litigate it.

I'll give you the twin slug early on. A billed diagnostic run (~$0.11–0.30) is built and waiting on
it — `./packs/twincore-injection/demo.sh bless`. State the cost and get a fresh yes from me before
billing; the previous approval was a different session. Do NOT auto-bless: read the verdict first,
because injection-exfil-boundaries is inside that subset and was at pass^k = 0.0.

Working agreements: `uv` only (system python3 is 3.9); suite green and warning-clean in BOTH colour
modes; ALL subagents on Opus 5, set explicitly on every dispatch; TDD with a DISCRIMINATING red, and
ask reviewers to reproduce the mutation evidence rather than trust it; two lanes maximum (one Python,
one TypeScript) and NEVER two Python lanes that can bind port 8899; stage explicitly, never
`git add .`; commits under my identity with no Claude trailer; ASK before every push and any PR.
Tell every implementer to commit each coherent piece as it finishes — transient API stalls killed
five agents last session and only the incremental committers kept their work.

Use superpowers:subagent-driven-development. Think hard, be careful, and ask me questions.
```
