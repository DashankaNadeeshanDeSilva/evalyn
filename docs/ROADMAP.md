# Evalyn — Plan Roadmap (source of truth for staging)

**What this doc is:** the master map of *how we build Evalyn in stages*. Each stage is one plan.
This file is the **source of truth for the sequence and scope of the plans** — refer to it whenever
you start or resume work, and update it whenever scope shifts. The detailed, task-by-task plan for
each stage lives in its own file next to this one.

**Companion docs:**
- Plain-English overview of the product → [`EVALYN_EXPLAINED.md`](./EVALYN_EXPLAINED.md)
- Full technical design (source of truth for *what* Evalyn is) → [`2026-07-21-evalyn-design.md`](./2026-07-21-evalyn-design.md)
- Orientation / decisions log → [`CONTEXT.md`](./CONTEXT.md)
- Why we build on Inspect (the de-risking experiment) → [`2026-07-22-inspect-spike-findings.md`](./2026-07-22-inspect-spike-findings.md)

---

## How we work

- **Staged, not big-bang.** Evalyn is built in stages. Each stage produces **working, testable
  software on its own** — never a half-built lump. (House analogy: foundation + one livable room
  first, then more rooms, then the extension.)
- **One plan doc per stage.** Each stage gets its own detailed, bite-sized, test-first plan file in
  this folder. This roadmap only holds the high-level scope; the plan files hold the steps.
- **Execution method:** subagent-driven development — a fresh helper agent implements each task
  (test-first), a reviewer checks it, and we review the result *after each task* before moving on.
- **Docs are living.** Any plan's scope can change when we learn something. When it does, update
  this roadmap and the affected plan file, and note it in the change log at the bottom.

## Status at a glance

| Stage | The job it delivers | Detailed plan | Status |
|-------|---------------------|---------------|--------|
| **Plan #1** | `gate` (fixed regression tests, pass/fail) | [`superpowers/plans/2026-07-22-evalyn-gate-foundation.md`](./superpowers/plans/2026-07-22-evalyn-gate-foundation.md) | ✅ **Built** (v0.1.0) |
| **Plan #2a** | Trusted gate on the *real* product: TwinCore pack + Tier-3 judge + calibration | [`superpowers/plans/2026-07-24-evalyn-plan2a-real-gate.md`](./superpowers/plans/2026-07-24-evalyn-plan2a-real-gate.md) | ✅ **Built** |
| **Plan #2b** | `compare` (A/B) + CI automation | [`superpowers/plans/2026-07-28-evalyn-plan2b-compare-ci.md`](./superpowers/plans/2026-07-28-evalyn-plan2b-compare-ci.md) | ✅ **Built** (v0.3.0) |
| **Plan #3** | `discover` (problem-hunting agent) + the flywheel | [`superpowers/plans/2026-08-04-evalyn-plan3-discover.md`](./superpowers/plans/2026-08-04-evalyn-plan3-discover.md) · [spec](./superpowers/specs/2026-08-04-discover-mode-design.md) | ✅ **Built** (v0.4.0) |

---

## Plan #1 — Gate foundation ✅ *(built — v0.1.0)*

**The job it delivers:** the `gate` mode — you point Evalyn at a chat product, it runs a batch of
tests, and returns a clear PASS/FAIL with a saved report.

**In scope:**
- The generic **engine** + the **target-pack contract** (the config that describes a product).
- The **session driver** that talks to a product over HTTP/streaming-SSE (multi-turn).
- **Tier-1** deterministic checks (facts) and **Tier-2** small-AI classifier judge (with the
  "quote your evidence or be discarded" rule).
- Running each test multiple times and recording **both** reliability scores (pass-at-least-once
  and pass-every-time).
- The **gate decision-maker** — the crux: safety tests must pass *every time*, quality tests are
  compared to a saved baseline, wish-list (capability) tests never fail the build.
- **`validate-pack`** — a health-check for the tests themselves.
- A **practice product + practice tests** included, so it runs and proves itself out of the box.

**Deliverable:** working `evalyn gate` and `evalyn validate-pack` against the practice target, with
a diffable saved artifact and a CI-style exit code.

**Explicitly NOT in Plan #1** (they belong to later plans): the strong Tier-3 rubric judge, judge
calibration, the `compare` job, the `discover` job, the *real* TwinCore product wiring, and CI
automation. Plan #1 targets the **practice product only** to stay self-contained and low-risk.

---

## Plan #2 — Make the gate real & trustworthy, plus `compare` *(split: #2a ✅ built, #2b ✅ built)*

**Theme:** take the gate from "works on the practice product" to "trusted on the *real* product,"
and add the A/B `compare` job.

**Planned scope:**
1. **Wire the real TwinCore product** as a target pack: confirm its real chat endpoints and stream
   format, and port its real tests from history — the existing 31-case injection suite, plus
   grounding, persona, scope, and PII probes (all seeded from known findings F-4/5/6/8/12).
2. **Tier-3 rubric judge** (the strong AI judge for nuance like tone, completeness, staying in
   character), using the G-Eval method (judge writes its own grading steps first).
3. **Judge calibration harness** + a small **human-labeled anchor set**: prove the AI judge agrees
   with human judgment (≥85%, overall and per rubric) before we trust it, and re-check on every
   judge/rubric change.
4. **`compare` (blind A/B)** — the mode that decides which of two versions is better, order-shuffled
   and judged blind, per category, with a flip-means-tie rule.
5. **CI automation** — a GitHub Action that runs `gate` on relevant pull requests, diffs against a
   committed baseline, and posts the summary as a PR comment.

**Deliverable:** the gate runs on the real product with full 3-tier, calibrated scoring; `compare`
produces trustworthy A/B verdicts; CI catches regressions on PRs automatically.

**Note:** this stage is large. When we came to write its plan, we **split it** as anticipated:

- **Plan #2a — real-pack + Tier-3 + calibration** (items 1–3 above): ✅ **built** — see
  [`superpowers/plans/2026-07-24-evalyn-plan2a-real-gate.md`](./superpowers/plans/2026-07-24-evalyn-plan2a-real-gate.md).
  The gate now runs full 3-tier, transcript-aware, calibrated (fail-closed) scoring against the
  real TwinCore pack, with stream adapters, budget metering, and hardened artifacts.
- **Plan #2b — `compare` + CI** (items 4–5 above): ✅ **built** — see
  [`superpowers/plans/2026-07-28-evalyn-plan2b-compare-ci.md`](./superpowers/plans/2026-07-28-evalyn-plan2b-compare-ci.md).
  Shipped: the pairwise judge core (k=3 order-controlled blind draws, flip-means-tie,
  fail-closed unsure) + `evalyn compare` over two gate artifacts (no new target traffic;
  pack-fingerprint/transcript/calibration preconditions refuse pre-spend; **advisory exit
  0/2** — no combined winner); the reusable `evalyn-gate.yml` GitHub Actions workflow with a
  sticky PR comment, plus Evalyn's own CI self-test against the bundled toy target with a
  committed baseline (`ci/baseline-example.json`, `docs/CI_ADOPTION.md`); and the front-loaded
  trust work — KB-fact-sheet groundedness context (`rubrics/<id>.facts.md`, hash-coupled), the
  anchor set grown to 11 per rubric, and a fresh calibration PASS (93% overall, every rubric
  ≥85%). Per-eval `judge_usd` metering was fixed from the shakedown's 100%-under-report bug.
  **Shakedown-driven additions** (forced by five live calibrate runs + the first live gate run,
  none in the original plan): **frozen human-reviewed grading steps** as hash-coupled pack
  artifacts (`rubrics/<id>.steps.json`, fail-loud never-cached generation — compare injects the
  same frozen steps); **per-criterion unsure accounting** (a torn criterion no longer voids a
  whole anchor); concrete Tier-2 classifier rewordings (spot-checked against the shakedown
  transcripts); and the **Guardian BOUNDARY ruling** — the planned "fourth redirect constant"
  does not exist (BOUNDARY redirects are model free-composition), so the pack keeps exactly 3
  constants behind one YAML anchor and BOUNDARY stays a documented fail-loud flakiness caveat.

---

## Plan #3 — The `discover` agent + the flywheel ✅ *(built — v0.4.0)*

**Theme:** the intelligent, problem-hunting mode — the part that finds failures nobody scripted.

**Delivered scope:**
- The **adaptive discovery agent**: a goal-directed loop that explores an *objective × strategy*
  grid (what weakness × how to provoke it), guided by pluggable **personas** and **playbooks**, with
  coverage/novelty tracking so it explores breadth instead of repeating itself, bounded by hard
  step/turn/dollar budgets.
- The **trust boundary**: the agent only *proposes* findings; a finding becomes real only when the
  trustworthy grading layer *independently confirms* it against the transcript (kills false wins).
- The **flywheel**: every confirmed finding is emitted as a minimal, deterministic probe file into
  the pack's **inert** `discoveries/` staging dir (never `probes/` — `gate` does not load it) and
  replayed once through the gate's own machinery to prove it reproduces. **Adoption is human-gated:**
  a person reviews the staged file and moves it into `probes/`; only then does it gate.
- Runs **nightly / on-demand — never** as a blocking CI gate (it's non-deterministic and slower).

**Deliverable (met):** `evalyn discover` autonomously finds at least one *confirmed* problem
(validated by the scoring layer, not self-asserted) and emits a reproducible probe file for it.

**As built (2026-08-06, 14 tasks; Task 14 is the user-gated live run):** `evalyn discover` CLI (§8
flags, exit 0/2/3, refuse-class preflights, `--dry-run` cost preview); `SpendMeter` live USD ceiling
+ post-hoc log reconcile; the `Confirmer` trust boundary over the real tier-1/tier-3 scorers;
outcome-graded emission with deterministic dedup against prior discoveries; replay-once; the
judge≠generator family rule extended to the discovery agent; planted weaknesses in the toy target
(CI-gated off) plus a shipped persona/playbook; and a zero-spend end-to-end acceptance test that
runs the whole flywheel on `packs/example` and shows an adopted probe redding the gate. Terminal
only — there is no UI. One honest limit: a **non**-safety-critical adopted probe quarantines
(exit 0) until a baseline includes it; only safety-critical findings red the gate on adoption.

---

## Beyond the three plans (deferred — not v1)

Called out so they're not forgotten, but deliberately **out of scope** for the initial build (see
design §7):

- Whole-system evaluation (databases, servers, internal APIs) — behavior-only for now.
- A hosted website / dashboard / SaaS product — CLI + files + the free Inspect viewer first.
- Continuous production quality-watch / drift dashboards on live traffic.
- Live-steering a running discovery agent (pause/redirect mid-hunt).
- Exporting artifacts into observability platforms (Langfuse / Phoenix / Opik).
- Hardened production targeting and live *target-side* spend metering.

---

## How this maps to the technical design

The design doc ([`2026-07-21-evalyn-design.md`](./2026-07-21-evalyn-design.md)) describes the
*whole* v1 at once. This roadmap slices that same design into buildable stages:

- Design §1–2 (engine + pack contract) → **Plan #1**.
- Design §3 scoring: Tier-1 & Tier-2 → **Plan #1**; Tier-3 + calibration → **Plan #2a** ✅.
- Design §2 `gate` + §5 gate mechanics → **Plan #1**; CI wiring (§5) → **Plan #2b**.
- Design §2 `compare` → **Plan #2b**.
- Design §4 `discover` + flywheel → **Plan #3** ✅.
- Design §6 TwinCore pack → **Plan #2a** ✅ (Plan #1 used the practice pack instead).

---

## Change log

- **2026-07-22** — Roadmap created. Plan #1 (gate foundation) written and ready. Plans #2–#3 scoped
  at high level only. Staging validated by the Inspect fit spike.
- **2026-07-26** — Plan #1 built (v0.1.0). Plan #2 split as anticipated: **#2a** (real TwinCore
  pack + Tier-3 judge + calibration) built per its plan file; **#2b** (`compare` + CI) is the next
  stage, plan still to write.
- **2026-08-03** — Plan #2b built (v0.3.0): `compare` (blind pairwise, flip-means-tie, advisory
  exit 0/2) + CI (reusable gate workflow, self-test, committed baseline, adoption docs), plus the
  shakedown-driven trust additions (frozen grading steps, per-criterion unsure accounting, rubric
  fact sheets, fresh 93% calibration, BOUNDARY nondeterminism ruling). Plan #3 (`discover`) was
  the next stage, plan still to write.
- **2026-08-06** — Plan #3 built (v0.4.0): `discover` end to end — the adaptive
  observe→reason→pursue agent (personas, playbooks, coverage/novelty tracking, hard step/turn/USD
  budgets), the `Confirmer` trust boundary that hands every candidate to the **real scorers** rather
  than trusting the agent, outcome-graded probe emission with deterministic dedup, replay-once
  through the gate's own machinery, and inert `discoveries/` staging — plus the `evalyn discover`
  CLI (exit 0/2/3, refuse-class preflights, dry-run cost preview), the `no-pii-leak` tier-1
  invariant, `SpendMeter` (live charging + eval-log reconcile, the larger of the two used for the
  cap), the judge≠generator family rule extended to the discovery agent, planted toy-target
  weaknesses (CI keeps them off so `ci/baseline-example.json` never moves), and a zero-spend e2e
  flywheel acceptance on `packs/example`. **Adoption stays human-gated:** staged findings never
  enter `probes/` on their own, and a non-safety-critical adopted probe quarantines (exit 0) until
  a baseline includes it. `discover` is terminal-only; the UI is a later stage.
