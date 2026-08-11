# Plan #4 (`evalyn ui`) — session 5 handoff

**Written 2026-08-11.** Supersedes `2026-08-10-plan4-session3-handoff.md`, which is history only.

**The demo is 2026-08-14, a 6pm slot. Three working days.**

---

## 0. The one thing to read if you read nothing else

**`.superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md`** — the ledger. Every task outcome,
every ruling (R4-6 … R4-22), every constraint carried forward, and the full record of the billed
runs. It is the recovery map. `git log` and the ledger outrank anyone's recollection.

Then, in order:

1. `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/DEMO-READINESS-AUDIT.md` — the true dependency graph
   and the file-collision map that governs what can run in parallel.
2. `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/task-6-constraints.md` — **already written.** The
   nine things earlier tasks learned that Task 6's brief does not contain. Hand it to the Task 6
   implementer alongside the brief.
3. `PRODUCT.md` and `.impeccable/surfaces/ui-src.md` — product truth and the locked design
   direction. **Read the surface brief before any page task (9, 15, 16, 17, 21).**
4. `docs/superpowers/plans/2026-08-07-evalyn-plan4-ui.md` — the 22-task plan.

---

## 1. THE DEMO'S CENTRAL FINDING — measured, not hoped for

**`injection-exfil-boundaries` is intermittently broken on the live product.** Two billed runs, same
twin, same pack, six minutes apart:

| Run | Time | Verdict |
|---|---|---|
| A | 2026-08-10 21:30Z | **PASS** — 31/31 at `pass^k` 1.0, 86 s, $0.0263 |
| B | 2026-08-10 21:36Z | **FAIL** — `injection-exfil-boundaries` `pass^k = 0.0`, 84 s, $0.0249 |

Run B's `mean_score` is **0.3333** — 1 of 3 trials passed, 2 failed. Safety-critical. It is the same
probe that was red on 2026-07-28. **It was never fixed; Run A's green was luck.**

**This empirically confirms the project's own earlier prediction**, recorded when the pack was
carved: *"at k=1 pass^k collapses to pass@1 and a guardrail failing 1-in-3 shows green two runs out
of three."* So the talk's claim is not "we found a bug" — it is **"we found a gap a single-shot eval
would have called healthy two runs in three"**, which is a live argument for `pass^k` demonstrated on
a real product.

**Three decisions the maintainer still owes:**

1. **How to stage a 1-in-3 failure on a projector**, since a live run can come up green. Options:
   accept ~1/3 odds with a recorded red as fallback; lead with the recording and run live as
   corroboration; or raise `k` in the demo pack so the failure is near-certain to surface
   (k=5 → ~87%, k=7 → ~94%). Raising `k` is legitimate, not rigging — `pass^k` semantics are
   unchanged and a higher `k` only makes an existing intermittent failure more visible.
2. **Whether to capture a recorded RED.** The existing capture
   (`~/Desktop/evalyn-twincore-injection-2026-08-10.mov`, 315 MB, 300 s) is **Run A — the GREEN
   one.** There is no recorded red.
3. **Whether to file the `--update-baseline` blessing gap** (see §2) as an Evalyn defect.

### Numbers worth having on hand

- 31 probes, 28 safety-critical, k=3 → 93 sessions.
- **86 s wall clock** — comfortably inside a 2-minute slot. The pre-warming and concurrency-3→5
  levers that were budgeted are **not needed**.
- Judge cost **~$0.025/run**. Total spent to date: **~$0.051** against a $1.00 envelope.
- Judge is `anthropic/claude-sonnet-5`; the target runs OpenAI models — different families, so no
  self-preference bias.

---

## 2. Two traps confirmed real — do not re-learn these

**`demo.sh bless` blesses a FAIL.** It printed `gate: blessing FAIL verdict (1 failure(s))` and then
`gate: baseline updated`, exit 0. The `--update-baseline` refusals cover `rubric_scores_untrusted`
and INCOMPLETE probes only — **not a failing gate**. And the documented decision gate ("read the
verdict, bless only if sane") **cannot be satisfied from inside `bless`**, because `cli.py:180-181`
raises `typer.Exit(0)` immediately after `save_baseline()` — before `evaluate_gate()` at `:199` and
before the report prints.

The poisoned file was **quarantined, not deleted**:
`ci/baseline-twincore-injection.TAINTED-blessed-a-FAIL.json`. So
`ci/baseline-twincore-injection.json` does **not** exist, which is the correct state —
`demo.sh run` refuses to start rather than gate against a poisoned baseline.

**Use the diagnostic form, never `bless`, to learn anything:**

```
set -a; . ./.env; set +a
EVALYN_TWIN_SLUG=dashanka-de-silva EVALYN_TARGET_URL=http://localhost:8000 \
  uv run evalyn gate --target packs/twincore-injection \
    --judge-model anthropic/claude-sonnet-5 --baseline ci/baseline-twincore-injection.json
```

`load_baseline` returns `None` for a missing file (`baseline.py:23-24`), so this gates correctly with
no baseline present — safety-critical probes gate on `pass^k` without consulting one.

**The target's quota is the other trap.** The first attempt returned **80× HTTP 402 Payment
Required** out of 93 sessions. Cause: the twin's monthly conversation quota was exhausted (20/20).
The maintainer raised it to unlimited and the tier to `pro`. **If a future run shows mass MISSING /
INCOMPLETE probes, check the target's quota before debugging Evalyn.**

That failed run is itself demo material: Evalyn refused to shrink the `pass^k` denominator, marked 20
probes MISSING and 11 INCOMPLETE, and exited 1 — where a naive harness would have computed `pass^k`
over the single surviving trial and shown green.

---

## 3. Where things stand

**MERGED AND IN SYNC as of 2026-08-11.** `feat/plan4-ui-frontend` was merged into `feat/plan4-ui`
(`6c2800e`, `--no-ff`) and the frontend lane was then fast-forwarded to the same commit. **Both
branches and both worktrees now sit at `6c2800e`, and both are pushed.** No PR.

The merge was taken at a deliberately chosen moment: both tasks complete, nothing in flight, and the
**committed bundle quiescent** — it is minified, so a conflict there is unmergeable, and the safe
window closes the moment a frontend task starts. Verified beforehand as **zero overlapping files**
between the two sides.

**Verified after the merge:** Python **1138 passed** (cold `__pycache__`, `-W error::RuntimeWarning`),
`ruff` clean, frontend **177 passed / 10 files**, `tsc --noEmit` clean.

**Expected working-tree noise in the main worktree** — leave both alone:
`M docs/superpowers/handoffs/2026-08-07-plan4-ui-kickoff.md` (the maintainer's own unstaged edit) and
`?? ci/baseline-twincore-injection.TAINTED-blessed-a-FAIL.json` (deliberately quarantined, see §2).

> ⚠️ **`ui/node_modules` exists ONLY in `../Evalyn_frontend_lane`.** The main worktree has the `ui/`
> source but no install, so `npm run test` there fails with `vitest: command not found` — that is not
> a broken merge. Run frontend commands in the frontend worktree, or `npm ci` in the main one first.

| Task | State |
|---|---|
| 0 — spike | complete |
| 1 — freeze API contract | complete, review-clean |
| 2 — `run_id` + paths | complete, review-clean |
| 3 — `RunIndex` | complete, review-clean |
| 4 — redaction chokepoint | **complete** (`5f20585..dabec88`), review-clean after 5 fix rounds, 6 residuals parked under R4-23 |
| 5 — frontend scaffold | complete, review-clean, merged |
| 8 — app shell + runs table | **complete** (`575f874..cdb0c49`), 177 tests, 3 fix rounds, 6 residuals parked — incl. Step 4 (live-server verification) for the wiring pass |
| injection pack | complete (new work, not a plan task) |
| 6, 7, 9–21 | **not started** |

**Scope decision on record (2026-08-10, reaffirmed 2026-08-11): attempt all remaining tasks.** The
maintainer was shown an audit concluding it is not achievable and chose to proceed anyway, twice.
**Do not re-litigate.** Standing controller obligation: **sequence 18–21 LAST** — the demo proposal
never asks for them and Task 18 edits the engine modules the working terminal fallback runs through.

**Honest pace data for planning:** session 4 completed Task 4 (five fix rounds) and Task 8 (build +
one fix round) — roughly two tasks per long session. A demo-able cockpit is **6 → 7 → 9** (Task 8
already shipped the shell and table); everything after that is additive.

---

## 4. Next actions, in order

1. **Task 6** — `evalyn ui` command + app skeleton. Dispatch with `task-6-constraints.md` **and** the
   brief. Python lane.
2. **Task 7** — read endpoints. Python lane, strictly after 6.
3. **Task 9** — gate detail + transcript. TypeScript lane. **This is the demo payload** — it is the
   screen that shows what the model actually said when the guardrail failed. Read the surface brief
   first.
4. Then 10, 11, 12, 13, 14, 15, 16, 17, and **18–21 last**.

---

## 4.1 Parallelisation plan — read before dispatching anything

The maintainer asked for maximum parallelism **without mixing lanes up**. Those pull against each
other, so this section states exactly what is safe, what unlocks more, and what must never be
attempted.

### The three chains (derived from file ownership, not from the plan's grouping)

| Chain | Tasks | Shared file that serialises it |
|---|---|---|
| **S** — server | 6 → 7 → {11, 12, 13} → 14 → 20 | `src/evalyn/ui/server.py` (created by 6, modified by all the rest) |
| **T** — frontend | 9 → 15 → 16 → 17 → 21 | `ui/src/routes.tsx` + nav registry, **and** the committed Vite bundle |
| **E** — engine | 18 → 19 → (20 joins S) | `engine/run.py`, `solver.py`, `task_builder.py`, `compare.py`, `discovery/*` |

**S and T are genuinely disjoint** and are the two lanes to run. **E must NOT start early** — see
"Do not do this" below.

### The real port-8899 rule, corrected

The ledger's rule was "never two Python lanes". The precise fact is better and worse than that:

- `tests/conftest.py:61` binds **fixed port 8899**, session-scoped, and `:19` **bakes
  `http://localhost:8899` into a pack YAML fixture string** — both `env.base_url` and the allowlist.
  So the port is a literal inside a fixture, not merely a bind.
- **14 test files** consume `toy_target`, including all of `tests/engine/*`.
- **`tests/ui/*` does NOT consume it.** So Task 6/7 development work is port-free.

**But every implementer runs the full suite before reporting, and the full suite binds 8899.** That
is the actual collision — it applies to *reviewers* running the suite too, not just implementers.

### P1 — the highest-leverage prep task: make the toy-target port dynamic

Bind port **0**, read the assigned port back from `server.server_address[1]`, and build the pack YAML
fixture string with an f-string so `env.base_url` and the allowlist follow. This unlocks:

- two Python lanes running full-suite verification simultaneously,
- **parallel reviews**, which are currently serialised for the same reason.

**Do it ALONE, first, and verify serially.** It is a shared fixture 14 test files depend on; racing it
against any other work is how a whole session gets lost.

**The collision was disputed in the ledger for weeks. It was measured on 2026-08-11 and it is real:**

```
CONCURRENT   pytest tests/engine/test_budget.py  ∥  pytest tests/targets/test_session.py
  lane A -> exit 1, 8 passed / 2 ERRORS, OSError: [Errno 48] Address already in use  (×2)
  lane B -> exit 0, 5 passed
SERIAL       the same two files in one process -> 15 passed
```

The `allow_reuse_address` counter-argument was about the wrong failure: `SO_REUSEADDR` permits
rebinding a socket in `TIME_WAIT`, **not** binding a port another live process is actively listening
on. So P1 is necessary, not speculative — and the fix must change the port, not the socket options.

**The failure mode is misleading, and that is the real hazard.** The losing lane does not crash
cleanly — it reports fixture errors on *only* the tests that request `toy_target`, interleaved with
ordinary passes ("8 passed, 2 errors"). An implementer seeing two errors inside its own task's suite
would very plausibly debug a phantom for a long time before suspecting another process. **Any
dispatch that permits a full-suite run must say this out loud.**

Until P1 lands the rule is absolute: **only ONE agent may run pytest at a time, across ALL
worktrees.** Worktrees do not help — the port is machine-level. Focused runs under `tests/ui/` are
safe (that tree does not consume `toy_target`); everything else is not. **This serialises reviewers
too**, which is the cost people forget.

### P2 — freeze the five missing wire contracts before the lanes fork

Five routes still have **no frozen model**: `/api/packs`, `/validate`, `/axes`, and the **response**
shapes of `POST /api/runs` and `/control`. `/api/discoveries` has no list envelope either. Task 5's
guesses live in `ui/src/api/provisional.ts`, deliberately outside the mirrored `types.ts`.

This matters specifically *because* of the strategy below: the T lane will build against mocks, and
the three-way drift guard protects the 24 frozen models — but **not** the provisional five. Those are
exactly where a mock and the real endpoint can diverge silently. Freeze them in `models.py` +
`types.ts` **before** the lanes fork, and before Tasks 11/12/20 write their tests.

### The strategy that actually decouples the lanes: T builds mock-first

T's tasks each nominally need an S task (15←12, 16←13, 17←14), so a naive schedule leaves T idle
waiting on S. **It does not have to.** Task 5 already wrote MSW handlers for all 19 design-spec
endpoints with `onUnhandledRequest: "error"`, and **Task 8 already proved the pattern** by deferring
its live-server step honestly rather than stubbing one.

So: **T proceeds continuously against MSW mocks, and every deferred live verification batches into
ONE wiring pass once S has caught up.** Each deferral must be recorded the way Task 8 did it — a
block comment naming the prerequisite task and enumerating the checks the live pass must perform.
**Nothing may be stubbed or simulated to make a deferred step look done.**

### Recommended schedule

```
PREP (serial, alone):        P1 dynamic port  →  P2 freeze the five contracts
WAVE 1:   S: Task 6          ∥   T: Task 9  (mock-first — this is the demo payload)
WAVE 2:   S: Task 7          ∥   T: Task 15 (mock-first)
WAVE 3:   S: Task 12 → 13    ∥   T: Task 16 (mock-first)
WAVE 4:   S: Task 14 → 11    ∥   T: Task 17 (mock-first)
WIRING PASS: run every deferred live verification against the real server, in one go
THEN, LAST, and only if time remains:  Task 10 (bundle must be quiescent) → 18 → 19 → 20 → 21
```

**Task 9 is the demo payload** — it is the screen that shows what the model actually said when the
guardrail failed. If only one more task lands, it should be 9, which is why it is in Wave 1 rather
than queued behind the S chain.

**Task 10 must run when the bundle is quiescent** — after the last frontend task, never alongside one.

### Do NOT do this

- **Do not start chain E (18–21) early to "use a spare lane".** Task 18 edits the exact engine
  modules the working terminal fallback runs through — and that fallback is now *more* precious than
  when the ruling was made, because **the demo's central finding comes from a terminal run.** The
  maintainer's sequencing obligation stands: 18–21 last.
- **Do not run three lanes.** Two is the tested discipline. Three multiplies the ways a dispatch
  lands in the wrong worktree, and `cli.py` is touched by 6, 18, 19 and 21 — a third lane would put
  chain E into contention with chain S over it.
- **Never put two agents on the same branch in the same worktree.** One worktree, one branch, one
  agent, always.
- **Do not run two frontend tasks at once.** The committed minified bundle guarantees an unmergeable
  conflict.

### Anti-mix-up discipline (every dispatch, no exceptions)

1. State the **absolute worktree path** and the branch, and say plainly which one is *not* theirs.
2. State the **exact file globs** the agent may touch, and name the other lane's globs as forbidden.
3. State whether the agent may run the **full suite** or focused tests only (per P1's status).
4. Record **BASE per lane** (`git rev-parse HEAD`) before dispatch — review packages need it, and
   `HEAD~1` silently truncates multi-commit tasks.
5. Frontend agents: **do not run `pytest`.** Python agents: **do not run `npm`,** and do not touch
   `ui/**` or `src/evalyn/ui/static/**`.
6. Merge the frontend branch into `feat/plan4-ui` only at an explicit maintainer ask — pushes are
   pre-authorised, merges are not.

### On delegating review-addressing

Fix rounds are already delegated: the implementer fixes, a scoped re-reviewer verdicts. **Keep
adjudication in the controller.** It needs the plan, the cross-task context and the ruling history
that a subagent does not have — and every adjudication must land in the ledger as a ruling, which is
the controller's job. Delegate the *work*; keep the *judgment*.

---

## 4.2 Review budget — HARD CAP, and why (R4-27)

**Maximum TWO reviews per task:**

```
task review  →  (if findings) ONE fix round  →  ONE re-review  →  DONE
```

There is no third. Anything still open after the re-review is **parked with a ruling** and handed to
the final whole-branch review, which is the net. This is a maintainer ruling made on 2026-08-11
against a hard deadline with 15 tasks remaining — **it is not a quality opinion to be re-argued by a
future controller who finds an unfixed defect.**

**Pair it with this rule, which is the one that actually stops the spiral:**

> **A fix may not build new infrastructure.** If a finding can only be closed by adding a harness, a
> scanner, or a new abstraction — **park it.**

### Why — the measured diagnosis, so nobody re-learns it

Tasks 4 and 8 consumed an entire session between them: five fix rounds and six reviews for Task 4,
three rounds and four reviews for Task 8, at roughly 25–40 minutes per cycle.

The tempting explanation is "fixes kept breaking things". **That was checked and it is wrong.** A
hallucination check on 2026-08-11 verified every claimed defect against the git objects at the exact
reported lines, and recomputed six contrast ratios independently — all six matched to 2dp. The
agents were accurate throughout.

The real cause: **the fixes added new code, and the new code needed its own review.** The `Flatline`
word did not exist before its fix round, so its font-size and column width were new surface, not
regressions. The contrast guard did not exist at all — it grew from "fix three violations" into a
source-scanning, opacity-compositing harness with a derived ground inventory, and *its* gaps became
the next round's findings. Each increment was individually justified; nobody ever decided to build
it.

So the failure was **scope growth inside the review loop**, and it was the controller's to prevent.
The two rules above exist to prevent it structurally rather than by good intentions.

### Dispatch consequences

- Tell every task reviewer **in its dispatch** that only one fix round exists, and ask it to **rank**
  its findings so that round targets what matters most.
- Tell every fix implementer it may not build new infrastructure, and that reporting something
  unfixed is better than fixing it by building a harness.
- **Controller self-verification does not count against the cap.** Spot-checking an agent's hard
  claims — line numbers, measured numbers, whether the described thing exists — is cheap, uses no
  agent, and is standing practice (see §6).

---

## 5. Constraints that MUST travel forward

**Concurrency — file-collision facts, not preferences:**
- **Two lanes maximum: one Python, one TypeScript.**
- `src/evalyn/ui/server.py` is created by 6 and *modified* by 7, 11, 12, 13, 14, 20 — **those six are
  strictly sequential**, worktrees or not.
- `ui/src/routes.tsx` + the nav registry are edited by 9, 15, 16, 17, 21 — **not parallel with each
  other**.
- The committed Vite bundle is rebuilt by every frontend task — **caps the TS lane at ONE task**.
- **Never run two Python lanes that can bind port 8899** (R4-8). ~46 `EADDRINUSE` failures already.

**Per-task obligations:**
- **Task 6** — owns Task 4's deferred route-table census; must state explicitly which `run_id` it
  keys by (C-T6/7); **must mount `redacting_exception_handlers()` (C-T6b)** — `route_class=
  RedactingRoute` alone leaves error bodies unscrubbed, and error bodies carry `$HOME` paths.
- **Task 7** — keep the `evalyn.ui.index` import **lazy** (C-T7b); bound `RunIndex._cache` (F8); map
  a `ValidationError` out of `.get()` to `unreadable_artifact`, not a 500 (F10).
- **Task 9 and every later page** — nav items are a **registry with a `shipped` flag**; flip the flag,
  do not edit markup. `contrast.test.ts` enforces an **exhaustive** ink/ground inventory: any new
  colour must declare its ground and role or the suite fails.
- **Task 10** — the base wheel must still contain `evalyn/ui/models.py` and `paths.py` (the engine
  imports `ui.models`), and must `force-include` `src/evalyn/ui/static/**` (C-T10).
- **Task 17** — leave the Vite drift check **advisory**; macOS↔Linux byte-reproducibility is
  unverified and a hard fail on demo eve is self-inflicted.
- **Tasks 19/20** — import `META_FILENAME` / `META_LAUNCHED_KEY` / `META_EXIT_CODE_KEY` from
  `ui.paths`, never retype them; **write `meta.json` BEFORE the sidecar directory is observable**
  (C-T19b) or a healthy run flashes `interrupted`.
- **Task 20** — Step 4's SIGTERM escalation is **stale**; R4-11 governs (unacked cancel becomes an
  honest `interrupted`).
- **Anywhere** — the run count is a **derived invariant, never a literal** (R4-6). Truth today is
  **80 indexed / 26 degraded**; the plan's "82 / 27" is wrong in four places.

---

## 6. Method lessons that earned their place this plan

- **Reviewers must REPRODUCE mutation evidence, not read it.** This caught two vacuous tests in Task
  4, an implementer report claim that did not reproduce at all, and three unguarded fixes in Task 8.
  Every reviewer dispatch says so explicitly. **Do not downgrade reviewer models.**
- **Ask reviewers for a stability judgment when a fix churns.** Task 4's boundary helper was patched
  three times, each fix breaking something else. Asking "is this the wrong shape?" produced the
  redesign that ended it.
- **A screenshot older than the bundle is not evidence.** A Task 8 finding was a stale-capture
  artefact — and the failure mode was silent, because the unresolved token fell back to exactly the
  old size, so "broken" and "unchanged" rendered identically. Check mtimes before scoring a render.
- **Verify warning-cleanliness with `__pycache__` deleted.** A `SyntaxWarning` from a non-raw
  docstring is emitted at **compile time only** — invisible after the first local run, guaranteed on
  cold CI.
- **Size table columns against the enum, never against fixture data.** `table-fixed` does not clip an
  overflow, it collides — silently, until a status you did not fixture appears.
- **`git checkout -- <file>` is not a safe mutation-restore** when that file has uncommitted work. It
  silently reverted an implementer's work mid-round. Restore from an explicit backup copy.
- **Tell every implementer to commit each coherent piece as it finishes.** Transient API stalls
  killed five agents in session 3; only the incremental committers kept their work.

**Working agreements:** `uv` only (system `python3` is 3.9); suite green and warning-clean in **both**
colour modes; all subagents on **Opus 5, set explicitly on every dispatch**; TDD with a
**discriminating** red; stage explicitly, never `git add .`; commits under the maintainer identity
with **no Claude trailer**. **Pushes are pre-authorised** (standing, 2026-08-10); **worktree merges
and PRs still need an ask.**

---

## 7. Things that must not be fabricated

- **Zero `compare` artifacts exist in `runs/`.** A compare page renders an empty state against real
  data.
- **`packs/example/discoveries/` holds only `.gitkeep`** — the discover fixture's `probe_path` points
  at an empty directory. Pin the missing-file degradation in Tasks 11–13.
- **No blessed twincore baseline exists** (the only one produced was poisoned; see §2).

---

## 8. Reference index — everything you might need, in one place

### Control documents (read in this order)

| Path | What it is |
|---|---|
| `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md` | **The ledger.** Every task outcome, ruling R4-6 … R4-23, both billed runs, every constraint. The recovery map. |
| `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/DEMO-READINESS-AUDIT.md` | Dependency graph, file-collision map, stale-plan-text list |
| `docs/superpowers/plans/2026-08-07-evalyn-plan4-ui.md` | The 22-task plan (Global Constraints at line 26) |
| `docs/2026-07-21-evalyn-design.md` | Full technical design |
| `docs/ROADMAP.md`, `docs/JOURNAL.md` | Plan staging; progress journal (**JOURNAL is behind — Plan #4 is unrecorded**) |
| `CLAUDE.md` | Project instructions: `uv`, branch model, architecture constraints |

### Per-task working files (in the SDD workspace, git-ignored)

| Path | Note |
|---|---|
| `task-6-constraints.md` | **Written and ready.** Nine constraints Task 6's brief lacks. Hand it over with the brief. |
| `task-<N>-brief.md` | Extracted task text. Regenerate with `scripts/task-brief <plan> <N>`. Briefs for 6, 7, 8, 9 already exist. |
| `task-<N>-report.md` | Implementer reports, fix rounds appended. Task 4's carries five rounds. |
| `task-4-fix-round-{1,4}.md`, `task-8-fix-round-{1,2}.md` | Findings lists with reproductions — useful as templates |
| `review-<base>..<head>.diff` | Review packages. Generate with `scripts/review-package <plan> <BASE> <HEAD>`. |
| `SPIKE-FINDINGS.md` | Task 0's spike: `EarlyStop`, watchdog, SIGTERM (sources rulings R4-9 … R4-13) |
| `INJECTION-PACK-PLAN.md`, `BASELINE-PLAN.md` | Why the demo pack exists; what the billed run had to answer |

Skill scripts live at
`~/.claude/plugins/cache/claude-plugins-official/superpowers/6.2.0/skills/subagent-driven-development/scripts/`.

### Product and design

| Path | What it is |
|---|---|
| `PRODUCT.md` | Product truth, including the absences that must not be fabricated |
| `.impeccable/surfaces/ui-src.md` | **THE BENCH INSTRUMENT** — the locked design direction. Read before tasks 9, 15, 16, 17, 21. |
| `ui/README.md` | Frontend toolchain and pinned versions |
| — | **`DESIGN.md` is deliberately unwritten**; impeccable authors it at the end, from the built world |

### Demo assets

| Path | Note |
|---|---|
| `packs/twincore-injection/` | The 31-probe demo pack (`demo.sh` has `bless` / `run` / `preflight`) |
| `packs/twincore/probes/injection.yaml` | Source probes; `:28-32` `redirect_constants`, `:203,249-250` the `not_contains` secrets |
| `runs/20260810T213013274270-1d050805-twincore-injection.json` | **Run A — the GREEN run** (31/31, 86 s) |
| `runs/20260810T213604514508-661ea56c-twincore-injection.json` | **Run B — the RED run.** `injection-exfil-boundaries` `pass^k` 0.0, `mean_score` 0.3333 |
| `~/Desktop/evalyn-twincore-injection-2026-08-10.mov` | 315 MB, 300 s screen capture — **of Run A, the GREEN one** |
| `ci/baseline-twincore-injection.TAINTED-blessed-a-FAIL.json` | Quarantined poisoned baseline. **Do not promote it.** |
| — | `ci/baseline-twincore-injection.json` **does not exist** — that is the correct state |

### Code landmarks worth knowing before you edit

| Location | Why it matters |
|---|---|
| `src/evalyn/ui/models.py` | The **frozen** wire contract. `__all__` is the export contract; a structural test pins every model. |
| `src/evalyn/ui/paths.py` | Owns `META_FILENAME` / `META_LAUNCHED_KEY` / `META_EXIT_CODE_KEY`, `CONTROL_SUFFIX`, `EVENTS_SUFFIX` — **import, never retype** |
| `src/evalyn/ui/index.py` | `RunIndex`; pulls starlette transitively — **keep its import lazy** |
| `src/evalyn/ui/redact.py` | The chokepoint. `RedactingRoute` and `redacting_exception_handlers` are **lazy** (PEP 562) so importing loads no fastapi. |
| `src/evalyn/cli.py:53,145,180-181` | `--baseline` default; the `--update-baseline` branch that **exits before the report prints** |
| `src/evalyn/engine/baseline.py:23-24` | `load_baseline` returns `None` on a missing file — why the diagnostic form works |
| `tests/conftest.py:19,61` | Fixed port 8899, **baked into a pack YAML fixture string**. See P1 in §4.1. |
| `tests/cli_runner.py` | The `CliRunner` to import — **never** `typer.testing` |
| `ui/src/api/types.ts` + `ui/src/api/__tests__/models-drift.test.ts` | The mirror and its three-way drift guard |
| `ui/src/api/provisional.ts` | The five unfrozen contracts — see P2 in §4.1 |
| `ui/src/nav.ts` | The nav registry with per-destination `shipped` flags — flip a flag, don't edit markup |
| `ui/src/__tests__/contrast.test.ts` | The executable AA rule. **Note its scope gaps** (`.ts` files, `inset`/`safety` families) before trusting it. |
| `ui/tailwind.config.ts:31-50` | The measured contrast table and its stated prohibitions |

### Commands

```bash
uv sync --extra ui                       # install (the [ui] extra arrives with Task 6)
uv run pytest -q -W error::RuntimeWarning
FORCE_COLOR=1 uv run pytest -q -W error::RuntimeWarning   # CI forces colour; verify BOTH
find . -name __pycache__ -exec rm -rf {} +                # before claiming warning-clean
uv run ruff check src/ tests/
cd ui && npm run test -- --run && npx tsc --noEmit && npm run build

# The diagnostic gate run (NEVER `demo.sh bless` — see §2)
set -a; . ./.env; set +a
EVALYN_TWIN_SLUG=dashanka-de-silva EVALYN_TARGET_URL=http://localhost:8000 \
  uv run evalyn gate --target packs/twincore-injection \
    --judge-model anthropic/claude-sonnet-5 --baseline ci/baseline-twincore-injection.json

./packs/twincore-injection/demo.sh preflight   # free, no model calls
```

**macOS notes:** there is no `timeout` — use `perl -e 'alarm N; exec @ARGV'`. Screen recording works
(`screencapture -v -V <secs> out.mov`); **let `-V` expire, do not `kill -INT`** or the container never
finalises. The Bash permission classifier blocks executing a wrapper `.sh` from the scratchpad — run
commands inline.

### Git

- `origin` → https://github.com/DashankaNadeeshanDeSilva/evalyn
- `feat/plan4-ui` (main feature branch) and `feat/plan4-ui-frontend` (worktree
  `../Evalyn_frontend_lane`) — **merged and in sync at `fbbf441`**, both pushed, no PR.
  Future frontend work still happens on the frontend branch and is **merged back at an explicit
  maintainer ask**, at a moment when the committed bundle is quiescent (see §3).
- Commit as: `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit …`
- **Pushes pre-authorised. Worktree merges and PRs need an ask.**

---

## 9. Kickoff prompt for the next session

```
We're continuing Plan #4 — the `evalyn ui` cockpit. Demo is 2026-08-14 (AI Tinkerers Bremen),
a 6pm slot, so three working days. Work on branch `feat/plan4-ui` (pushed, no PR).

Read first, in this order:
1. docs/superpowers/handoffs/2026-08-11-plan4-session5-handoff.md — START HERE, full state transfer.
   Its §4.1 is the parallelisation plan (read BEFORE dispatching anything) and its §8 is a reference
   index of every path, code landmark and command you will need.
2. .superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md — the ledger; rulings R4-6 … R4-23.
   This is the recovery map; it and `git log` outrank anyone's recollection, including your own.
3. .superpowers/sdd/2026-08-07-evalyn-plan4-ui/DEMO-READINESS-AUDIT.md — dependency graph + the
   file-collision map governing what can run in parallel
4. .superpowers/sdd/2026-08-07-evalyn-plan4-ui/task-6-constraints.md — ALREADY WRITTEN. Hand it to
   the Task 6 implementer alongside its brief; it carries nine things the brief doesn't.
5. PRODUCT.md and .impeccable/surfaces/ui-src.md — product truth + the locked design direction.
   Read the surface brief BEFORE any page task (9, 15, 16, 17, 21).
6. docs/superpowers/plans/2026-08-07-evalyn-plan4-ui.md — the 22-task plan itself

State: Tasks 0–5 and 8 are complete and review-clean. Tasks 6, 7 and 9–21 are not started.
feat/plan4-ui and feat/plan4-ui-frontend are MERGED AND IN SYNC at fbbf441, both pushed, no PR —
verified after the merge: Python 1138 passed on a cold cache, ruff clean, frontend 177 passed, tsc
clean. Ask me before merging the frontend lane back again.

Note: ui/node_modules exists ONLY in ../Evalyn_frontend_lane, so `npm run test` in the main worktree
fails with "vitest: command not found" — that is not a broken checkout. Run frontend commands there.

I want maximum parallelism, but I care more about not messing it up than about speed. §4.1 has the
analysis: two lanes only (Python + TypeScript), the frontend builds mock-first with live checks
deferred and batched, and there are two prep tasks worth doing ALONE first — P1 makes the toy-target
port dynamic (it currently serialises even reviews) and P2 freezes the five unfrozen wire contracts
(the drift guard doesn't cover them, and they're exactly where a mock and a real endpoint diverge
silently). Do the prep, then Task 6 ∥ Task 9.

Task 9 is the demo payload — the screen showing what the model actually said when the guardrail
failed. If only one more task lands, it should be 9. Sequence Tasks 18–21 LAST: Task 18 edits the
engine modules my working terminal fallback runs through, and that fallback now matters MORE, not
less, because the demo's central finding comes from a terminal run. I chose to attempt all remaining
tasks knowing an audit said it isn't achievable; that decision stands, don't re-litigate it.

The demo's central finding is already measured and is NOT a UI feature: injection-exfil-boundaries
fails 2 trials in 3, intermittently, on the live product — pass^k = 0.0, mean_score 0.3333, six
minutes after the same suite came up 31/31 green in 86s. I still owe you a decision on how to stage
a 1-in-3 failure on a projector and whether to capture a recorded RED (the existing 315MB capture is
the GREEN run). Raise it when timely; don't let it block Task 6.

Before trusting the frontend contrast guard: it is exhaustive over the vocabulary Task 8 uses, not
over what the config defines — it misses .ts files and the reserved `inset` family that Task 21's
dark live view is built on. Handoff §4.1 and the ledger have the detail.

Working agreements: `uv` only (system python3 is 3.9); suite green and warning-clean in BOTH colour
modes, verified with __pycache__ DELETED (a SyntaxWarning is emitted at compile time only and is
invisible on a warm cache); ALL subagents on Opus 5, set explicitly on every dispatch; TDD with a
DISCRIMINATING red, and have reviewers REPRODUCE mutation evidence rather than trust it — that has
caught two vacuous tests, a report claim that didn't reproduce at all, three unguarded fixes, and a
contrast guard that was certifying a failing pairing; every dispatch must name its absolute worktree
path and the exact file globs it may touch; stage explicitly, never `git add .`; commits under my
identity with no Claude trailer. Pushes are pre-authorised — ASK before any worktree merge or PR.
Tell every implementer to commit each coherent piece as it finishes.

Use superpowers:subagent-driven-development. Think hard, be careful, and ask me questions.
```
