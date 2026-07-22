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
| **Plan #1** | `gate` (fixed regression tests, pass/fail) | [`superpowers/plans/2026-07-22-evalyn-gate-foundation.md`](./superpowers/plans/2026-07-22-evalyn-gate-foundation.md) | ✅ Plan written — **ready to execute** |
| **Plan #2** | Real product wiring + full-strength judging + `compare` (A/B) + CI | *(not yet written)* | ⏳ Planned (scope below) |
| **Plan #3** | `discover` (problem-hunting agent) + the flywheel | *(not yet written)* | ⏳ Planned (scope below) |

---

## Plan #1 — Gate foundation ✅ *(plan written, ready to build)*

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

## Plan #2 — Make the gate real & trustworthy, plus `compare` ⏳ *(scope only; plan not yet written)*

**Theme:** take the gate from "works on the practice product" to "trusted on the *real* product,"
and add the A/B `compare` job.

**Planned scope:**
1. **Wire the real TwinCore product** as a target pack: confirm its real chat endpoints and stream
   format, and port its real tests from history — the existing 31-case injection suite, plus
   grounding, persona, scope, and PII probes (all seeded from known findings F-4/5/6/8/12).
2. **Tier-3 rubric judge** (the strong AI judge for nuance like tone, completeness, staying in
   character), using the G-Eval method (judge writes its own grading steps first).
3. **Judge calibration harness** + a small **human-labeled anchor set**: prove the AI judge agrees
   with human judgment (≥85%) before we trust it, and re-check on every judge/rubric change.
4. **`compare` (blind A/B)** — the mode that decides which of two versions is better, order-shuffled
   and judged blind, per category, with a flip-means-tie rule.
5. **CI automation** — a GitHub Action that runs `gate` on relevant pull requests, diffs against a
   committed baseline, and posts the summary as a PR comment.

**Deliverable:** the gate runs on the real product with full 3-tier, calibrated scoring; `compare`
produces trustworthy A/B verdicts; CI catches regressions on PRs automatically.

**Note:** this stage is large. When we come to write its plan, we'll likely **split it** (e.g. #2a
real-pack + Tier-3 + calibration; #2b compare + CI). We'll decide then.

---

## Plan #3 — The `discover` agent + the flywheel ⏳ *(scope only; plan not yet written)*

**Theme:** the intelligent, problem-hunting mode — the part that finds failures nobody scripted.

**Planned scope:**
- The **adaptive discovery agent**: a goal-directed loop that explores an *objective × strategy*
  grid (what weakness × how to provoke it), guided by pluggable **personas** and **playbooks**, with
  coverage/novelty tracking so it explores breadth instead of repeating itself, bounded by hard
  step/turn/dollar budgets.
- The **trust boundary**: the agent only *proposes* findings; a finding becomes real only when the
  trustworthy grading layer *independently confirms* it against the transcript (kills false wins).
- The **flywheel**: every confirmed finding auto-emits a minimal, reproducible `gate` test, so the
  regression suite grows itself and never re-forgets a bug.
- Runs **nightly / on-demand — never** as a blocking CI gate (it's non-deterministic and slower).

**Deliverable:** `evalyn discover` autonomously finds at least one *confirmed* problem (validated by
the scoring layer, not self-asserted) and emits a reproducible probe file for it.

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
- Design §3 scoring: Tier-1 & Tier-2 → **Plan #1**; Tier-3 + calibration → **Plan #2**.
- Design §2 `gate` + §5 gate mechanics → **Plan #1**; CI wiring (§5) → **Plan #2**.
- Design §2 `compare` → **Plan #2**.
- Design §4 `discover` + flywheel → **Plan #3**.
- Design §6 TwinCore pack → **Plan #2** (Plan #1 uses the practice pack instead).

---

## Change log

- **2026-07-22** — Roadmap created. Plan #1 (gate foundation) written and ready. Plans #2–#3 scoped
  at high level only. Staging validated by the Inspect fit spike.
