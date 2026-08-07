# Plan #4 (`evalyn ui`) — session 2 handoff

**Written:** 2026-08-07, end of the scoping+kickoff session. **Branch: `feat/plan4-ui`** (cut from
`dev` @ `8f3e2de`). **Demo: 2026-08-14.**

---

## 1. What this session did

**Decided the scope** (it was genuinely open), **wrote the spec and the executable plan**, **cut the
branch**, and **executed the first 2 of 22 tasks**.

### Scope — decided, do NOT re-open

The maintainer chose the **maximum** on every axis after being shown the cost:

| Axis | Decision |
|---|---|
| Live scope | **Full cockpit** — browser launch **and** pause / resume / cancel, SSE streaming |
| Launchable modes | **gate + compare + discover** |
| Surfaces | Runs · Run Detail (live) · TranscriptViewer · Launch · Discover findings · Compare scoreboard · Trends · Judge Trust |
| Judge Trust | Read-only over the **shipped** `calibration.json`. **No Cohen's κ.** |
| Packaging | Real `evalyn[ui]` extra, SPA committed to `src/evalyn/ui/static`, wheel packaging, CI drift check |
| Deferred outright | All of 4a; 4b panels/review-queue/promote; 4c transports / `init` / `report.html` |

**Cherry-pick ruling: nothing from 4a/4b/4c enters this plan.** Reasons are recorded in the spec §1
so they are not re-litigated.

**Recorded risk:** this is essentially all of 4d plus the packaging tail plus a first-contact
frontend toolchain, in 7 days, against a Plan #3 baseline of 15 tasks in 5 days. **Not all of it is
expected to land.** The plan is ordered so **every prefix is demo-viable**, with a ranked cut list.

### Artifacts produced

- `docs/superpowers/specs/2026-08-07-evalyn-ui-cockpit-design.md` — the design spec
- `docs/superpowers/plans/2026-08-07-evalyn-plan4-ui.md` — the 22-task executable plan
- both committed on `dev` as **`8f3e2de`** (docs-only exception)
- `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/` — the SDD workspace:
  **`progress.md`** (the ledger — READ THIS FIRST), **`RULINGS.md`** (13 binding rulings),
  `SPIKE-FINDINGS.md`, `task-1-report.md`, briefs, and the review package diff

---

## 2. Where execution stands

| Task | Status |
|---|---|
| **0 — spike** | ✅ complete. No commits by design (R4-0). Findings in `SPIKE-FINDINGS.md`. |
| **1 — freeze API contract** | ⚠️ committed `82baacf` (726 → **777** tests, both colour modes green, ruff clean), but **the review came back spec ❌ / quality NOT approved.** Fix round 1 not started. |
| **2–21** | Not started. |

### First thing next session: Task 1 fix round 1/5

The review is recorded **in full** in the ledger (`progress.md`). Resume the Task 1 implementer if
its context is still live, else dispatch fresh with `task-1-brief.md` + `task-1-report.md` + the
findings verbatim. **1 Critical + 6 Important**, all small — the reviewer estimated the Critical plus
Importants 1–3 at ≤15 lines of `models.py` plus one test.

**The Critical is demo-relevant:** `MetaResponse.runs_dir` is an **absolute filesystem path** exposed
on `/api/meta` — one of exactly two routes the design exempts from redaction. The spec's own pattern
list names home-dir paths, so the single field most likely to contain `/Users/…` is the one field the
chokepoint may not scrub, and the SPA renders it. Drop it, or make it a display-safe label.

**The most consequential Important is I4:** the freeze is *unenforced* for nine models — renaming a
field on `ProbeRow`, `GateVerdict`, `DiscoverySummary`, `ReplayView`, `CheckView`, `CriterionCounts`,
`RedactionMeta`, `MetaResponse` or `HealthResponse` produces **no red at all**. For a task whose
entire purpose is "a later task cannot change a response without failing here", that is the central
gap. Fix is one structural test pinning `{name: (annotation, is_required)}` across every model.

**I2 is structural, not cosmetic:** `redacted: bool` is missing on `RunDetail`, `GateVerdict` and
`Scoreboard`, and because every model is `extra="forbid"` the redaction middleware **cannot add the
key later**.

**What the review verified as good — do not re-check:** fixture safety is clean (the reviewer diffed
both gate fixtures against their `runs/` originals; only `log_path` differs, transcripts come from
the already-public `packs/example/probes/grounding.yaml`, and a regex sweep for email / `/Users/` /
phone / `sk-` shapes finds nothing); the legacy fixture genuinely raises on a real pre-#2a `reducers`
key; compare and discover fixtures genuinely round-trip; import isolation holds; the artifact
dataclasses are untouched.

Branch state: 1 commit ahead of `dev`. Nothing pushed, no PR opened.
**Uncommitted and NOT mine:** `docs/superpowers/handoffs/2026-08-07-plan4-ui-kickoff.md` (−40 lines,
the consumed kickoff-prompt block). Left alone deliberately — it is the maintainer's to own.

---

## 3. The two design rulings everything rests on

**R1 — instrumentation is an explicit `EventSink`, NOT `inspect_ai.hooks`.** Two design agents
disagreed; verified against pinned Inspect source. `@hooks` registers **process-globally**, so it
would fire for every eval in the 726-test suite and destroy the "flag absent ⇒ unchanged behaviour"
proof that protects the terminal fallback.

**R2 — pause/cancel rides `Task(early_stopping=…)`.** `run_gate` is a single blocking `inspect_eval`
with no Evalyn-side trial loop, so the original "poll between trials" had no seam. Inspect provides
one: `schedule_sample(id, epoch)` is **async**, awaited at `_eval/task/run.py:1270` after the sample
semaphore and before solver work.

**Events land as `runs/<run_id>.events.jsonl` siblings** — not a per-run directory. Every existing
filename assertion globs `*.json`, so this is **zero test churn** and avoids a task-sized migration
touching compare and baseline discovery.

---

## 4. What the spike overturned (evidence-backed plan corrections)

- **Q2 CONFIRMED, twice** — an `EarlyStop`ped sample leaves `log.status == "success"`, proven on the
  **real** `build_task` → `run_gate` → `reduce_log_to_probes` path. Cancel design stands;
  `run.py:287` needs no change.
- **Q1 CLEAN, with a discriminating control** — an 8 s block in `schedule_sample` raised nothing, and
  `time_limit=3` did **not** fire during the block but **did** fire in the solver. The sample clock
  starts *after* `schedule_sample` returns.
- **Q3 OVERTURNED Task 20 (R4-11).** SIGTERM leaves the log at `status='started'` — which
  `run_gate:287` **rejects** — and strands a completed, **paid-for** sample in Inspect's buffer,
  outside the log. SIGINT is clean but makes `run.py:286`'s `logs[0]` raise `IndexError`.
  **Cancel is never built on signals.** The control file is the only mechanism; an unacked cancel
  becomes an honest `interrupted` state, not a corrupted log.
- **R4-9:** probe id comes from `state.metadata["id"]`, **not** `state.sample_id` —
  `task_builder.py:104` omits `id=`, so Inspect assigns ordinals. `run.py:183` already does this.
- **R4-12:** "pause" honestly means **"start no new samples"** — in-flight trials finish **and keep
  spending**. UI copy must read "Pause (finishes in-flight trials)". Truthfulness requirement.

---

## 5. Corrections to my own calls (don't repeat them)

- **R4-8 — parallel dispatch is more constrained than I claimed.** I ran Tasks 0 and 1 concurrently
  calling them "disjoint by construction". They are not: the session-scoped `toy_target` fixture
  binds **fixed port 8899**, and the spike was told it could run `examples/toy_target.py` on the same
  port. That likely caused the 46 `EADDRINUSE` errors Task 1 reported. **No further concurrent
  dispatch where either side can bind 8899.** Frontend (Vitest) tasks may still overlap one Python
  task.
- **R4-6 — my "82 runs" was wrong.** `ls runs/ | wc -l` counted the `logs/` dir. Truth: `runs/*.json`
  = **81**, minus `baseline.json` = **80** indexable; 2 discover; **0** compare. Task 3 must assert
  **derived invariants, never a hardcoded count** — a literal reds on a correct implementation the
  moment anyone runs a new eval.

---

## 6. What to do next

1. **Resolve Task 1's review** (see §2), then `Task 1: complete` in the ledger.
2. **Task 2** — `run_id` keyword on `atomic_write_artifact` + `ui/paths.py`. Must **import**
   `models.RUN_ID_RE` / `is_run_id`, not redefine them (R4-7).
3. Then group ‖A (tasks 3, 4, 5, 6), honouring R4-8's port constraint.
4. **★ Task 10 is the safe-demo boundary.** If time gets tight, getting to 10 matters more than
   starting anything past it.

**Working agreements (unchanged):** controller on Fable 5, **all subagents on Opus 5 with
`model: opus` set explicitly**; delegate all implementation; controller rulings to `RULINGS.md`
before each dispatch; TDD with a **discriminating** red; commits automatic under the maintainer
identity with no Claude trailer, staged **explicitly**; **ASK before every push and any PR**; `uv`
only; suite green and warning-clean in **both** colour modes.

---

## 7. Outside this plan, on the demo critical path ⚠️

**There is no committed twincore baseline.** `ci/baseline-example.json` is the only tracked baseline,
and `runs/baseline.json` is **stale and unloadable** (a `reducers` key makes `RunArtifact.from_dict`
raise). The demo's closing beat is "a deliberately regressed prompt turning the baseline diff red"
against NiuwnAI — which today has nothing to diff against. This is **user-gated live spend** and
needs lead time. It is independent of all UI work and should be started regardless of how Plan #4
goes.

**PII hazard, still live:** `packs/twincore/discoveries/discovered-pii-leak-0bf80f3b.yaml` embeds a
real email as a check value. Never move it into `probes/` (tracked, public). The UI's redaction
harvests pack check values as patterns, which catches it **by construction**.
