# Evalyn — Session Handoff / Context

**Purpose of this file:** let a fresh Claude Code session (started *in this repo*) continue the
Evalyn project with full context, without re-deriving the brainstorming that produced it.
**Source of truth for the design is [`2026-07-21-evalyn-design.md`](./2026-07-21-evalyn-design.md).**
This file is the *orientation layer* around it: origin, decisions, external references, and next step.

---

## 1. What Evalyn is (one paragraph)

Evalyn is a **standalone, open-source, project-agnostic evaluation system for LLM-powered products**.
It does three jobs via one CLI:

- `evalyn discover` — an **intelligent, goal-directed agent** that red-teams/explores a product like
  an adversarial visitor and *finds* failure modes you didn't enumerate.
- `evalyn gate` — a **deterministic, scored regression suite** (CI-friendly, diffs a baseline).
- `evalyn compare` — **blind A/B judging** to decide if a change is measurably better before adopting.

The engine is **generic**; everything product-specific lives in a swappable **target pack**. The
first reference pack is **TwinCore (NiuwnAI)** — the user's own product, which currently has *no
evaluations at all*. That gap is the origin motivation for this project.

## 2. Why this project exists (origin)

The user (Dashanka) is building **TwinCore / NiuwnAI** (a Digital-AI-Twin product) and realized it
ships with **zero evaluations** despite AI behavior being its core. Initial idea: build "a powerful
eval AI agent," possibly adapting the **Nous Hermes agent** harness. Through brainstorming this
became: *don't repurpose a personal-assistant runtime; build a purpose-built eval layer on a proven
eval spine, generic enough to point at any project.*

## 3. Locked decisions (from the brainstorming session)

These were decided explicitly by the user and are **settled** unless the user reopens them:

| # | Decision | Value |
|---|----------|-------|
| D1 | First-version eval scope | **AI behavior only** (the product's conversational agents). Whole-system eval deferred. |
| D2 | Primary jobs | **All three**: discovery/red-team + regression gate + A/B experiments. |
| D3 | Placement | **Separate standalone repo** (this one), reusable across any project / by anyone. |
| D4 | Target environment | Target's **local dev stack** (real LLMs, real data stores, seeded throwaway data). Prod targeting possible but behind explicit safety flags. |
| D5 | Architecture approach | **Purpose-built for evaluation** (not the Hermes chassis). |
| D6 | Ambition | **Open-source from day 1** (public repo, README/docs/license, bring-your-own-keys). |
| D7 | Build vs adopt (the spine) | **Build ON Inspect AI** as the runner/scorer/log backbone; own only the differentiators. |

**Evalyn's novel core (its IP), on top of Inspect:** (a) **target packs** — a contract that drives a
black-box product over live HTTP/SSE; (b) the **adaptive discovery agent**; (c) the **findings →
regression flywheel** (confirmed discoveries auto-emit reproducible probes). Nothing in the eval
landscape provides these three as a unified whole.

## 4. Prior-art decisions (from surveying Awesome-AI-Evaluations-Tools)

Full table is §9 of the design doc. Summary:

- **Build on:** **Inspect AI** (UK AISI) — `Task → Solver → Scorer`, immutable eval-log format, log
  viewer, model provider layer, agent/tool support. This is the dependency.
- **Adopt patterns:** **promptfoo** (red-team *plugin × strategy* two-axis taxonomy → our *objective ×
  strategy* grid); **DeepEval** (**G-Eval** as the Tier-3 rubric-judge method; faithfulness/
  hallucination metric defs); **Giskard OSS** (vulnerability taxonomy → discovery objective priors);
  **LangChain AgentEvals** (trajectory scoring for multi-turn).
- **Ignore:** academic *model* benchmarks (lm-eval-harness, HELM, OpenCompass, LightEval, BIG-bench,
  AlpacaEval) — they benchmark models on leaderboards, not product behavior.
- **Defer:** observability platforms (Langfuse, Phoenix, Opik, Helicone, Evidently) — possible future
  export target; no UI/SaaS in v1.
- **2026-07-22 revision:** the design was reviewed against Anthropic's engineering article
  *[Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)*
  and amended (user-approved). Adopted: capability-vs-regression probe kinds + graduation,
  pass@k/pass^k (pass^k gates safety probes), transcript-vs-outcome grading + optional
  `state.checks`/`reset`/seed-fingerprint pack hooks, `evalyn validate-pack` task-health tooling
  (reference solutions, balanced-set lint, suspect-task flagging), transcript-review discipline
  (agent-blamed vs grader-blamed triage), "grade outcomes not paths" for flywheel-emitted probes,
  and τ-bench-style **simulated-user probes** (schema in v1; runner is nice-to-have, may ship v1.x).

## 5. Design essentials (skim; full detail in the design doc)

- **§1–2 Engine + target packs.** Engine knows *only* the pack contract (how to open a session, send
  a message, read the reply; invariants, probes, rubrics, personas, playbooks, anchors, budget,
  allowlist; optional read-only `state` hooks: outcome `checks`, `seed_fingerprint`, `reset`). Probe
  suite = Inspect `Task`; session driver = `Solver`; scoring tier = `Scorer`; run = Inspect eval log.
  Multi-turn probes are first-class. Probes have `kind: regression|capability` (capability =
  aspirational, never reds the build, graduates when stable) and weighted checks (partial credit);
  a τ-bench-style simulated-user probe type is specced (runner nice-to-have, may ship v1.x).
- **§3 Scoring = 3-tier trust ladder.** Tier 1 deterministic (facts, can hard-fail) → Tier 2 cheap
  classifier judge (must quote evidence or scored `unsure`) → Tier 3 **G-Eval** rubric judge (pinned
  rubric files, judge ≠ generator family, blind order-swapped A/B, self-consistency k=3). **Judge is
  calibrated** against a human-labeled anchor set (≥85% agreement gate). Gate never fails on one
  stochastic flip — fails on *pattern*, quarantines flips. Artifacts record **pass@k and pass^k**
  per probe; **safety-critical probes gate on pass^k** (all samples must pass), not majority vote.
- **§4 Discovery agent.** Goal-directed loop (observe → reason → pursue thread). **objective ×
  strategy** grid. **Trust boundary: the agent PROPOSES, the scoring layer DISPOSES** (a finding is
  real only when §3 confirms it against the transcript — kills false positives). Every confirmed
  finding auto-emits a minimal deterministic probe → the flywheel.
- **§5 Orchestration/cost/safety/CI.** Hard USD ceiling per run (meters target + judge + discovery
  spend), `--dry-run` estimate, caching, model tiers. **Target allowlist** (refuses non-allowlisted
  URLs; prod needs `--i-know-this-is-prod`). Analytics hygiene (tag eval sessions), PII discipline
  (transcripts gitignored). `gate` returns CI exit codes + PR comment; `discover` is nightly/on-demand,
  never a blocking gate. **`evalyn validate-pack`** = task health: graders must pass their reference
  solutions, balanced-set lint (every category needs positive AND negative cases), 0%-pass probes
  flagged as suspect tasks. **Transcript discipline:** reports link sampled transcripts; quarantine
  triage records agent-blamed vs grader-blamed; grader-blamed rate = eval-health meta-metric.
- **§6 TwinCore reference pack.** Seeded from real history (below). **§7 YAGNI scope-outs. §8 success
  criteria. §9 prior-art table.**
- **§10 Feasibility & UI.** (a) Evalyn works for **any** product via target packs — feasibility bands:
  *easy* (conversational HTTP/SSE product = config + content only), *medium* (novel auth/stream = small
  adapter), *harder* (non-conversational or non-HTTP = new session driver). Eval **content** (probes/
  rubrics/anchors) is *always* bespoke per product — that's inherent to evaluation. (b) **v1 has no
  custom dashboard** (deliberate), but the **Inspect log viewer** gives a browser UI for transcripts/
  scores/judge-reasoning for free; interaction is **launch-and-observe**, not live-steer. Custom
  dashboard / Langfuse-Phoenix export are deferred.

## 6. TwinCore facts the pack author will need

The new session will build `packs/twincore/`. Evalyn is **black-box** — it drives TwinCore's **real
HTTP/SSE visitor chat surface**, not internal functions. Key facts (verify against live code when
building the pack):

- **TwinCore repo path:** `/Users/dashankadesilva/Drive/Projects/NiuwnAI/niuwnai-mvp`
  (product = "TwinCore", folder = `niuwnai-mvp`, integration branch = `dev`).
- **The 3 agents:** **Curator** (owner-facing, writes KB, `gpt-5-mini`), **Twin** (visitor-facing,
  first-person, read-only, `gpt-5-mini`), **Guardian** (pre/post-check scope+safety, `gpt-5-nano`).
- **Visitor chat endpoint** is what Evalyn drives. The router streams via `graph.astream` at
  `backend/app/routers/twin.py` (~line 232), SSE, Vercel-AI event format. **Confirm exact route paths,
  session-open flow, and slug handling from the router + frontend before writing `target.yaml`.**
- **Existing 31-case injection suite** (port into `injection.yaml`):
  `backend/tests/live/test_guardian_injection_live.py` — 28 attacks + 3 controls, asserts Guardian
  `action ∈ {block, redirect, allow}`. Structured-field assertions, **not** an LLM judge. Opt-in via
  `pytest -m live`.
- **Known behavioral findings to encode as probes** (from `Docs/AGENT_INTELLIGENCE_FINDINGS.md`):
  - **F-12 / F-5 Guardian over-blocking (P1):** in-scope named-project and AI-identity/META questions
    wrongly redirected as out-of-scope. Recall is good (31/31), **precision** is the problem.
  - **F-5** also once rendered a literal `"null"` reply → the `non-empty` invariant exists for this.
  - **F-4** third-person harsh redirects (persona/tone).
  - **F-6** Twin over-shares contact PII.
  - **F-8** confidence is retrieval-volume-based, not answer-relevance.
- **The already-specified (but unbuilt) eval methodology:** `Docs/AGENT_INTELLIGENCE_UPGRADE_2026-07.md`
  **§7** — ~40-probe set, proposed runner `backend/scripts/eval_twin.py` (never built), 3-layer scoring
  incl. LLM-as-judge blind A/B rubric, adopt-only-if-better gates. Evalyn is the *external, generic*
  realization of this idea. **Read §7 — much of the TwinCore pack content can be lifted from it.**
- **Rubrics source:** `AGENT_INTELLIGENCE_UPGRADE_2026-07.md` §7.3 (groundedness/completeness/persona/
  honesty). **Anchor set:** ~15–20 transcripts from the M7 walkthrough for judge calibration.
- **Cost logging (reference for spend metering):** `backend/app/utils/llm_cost.py` emits one
  `llm_cost node=… model=… …_tokens=… usd=…` INFO line per LLM call (gross/upper-bound).
- **Existing golden pattern to mirror:** `backend/tests/goldens/gap_synthesis/` (JSON fixtures +
  structured DB-state assertions).
- **Note:** TwinCore keeps its in-process `-m live` white-box Guardian suite. Evalyn is complementary
  and black-box — not redundant (one tests the node, the other the shipped product).

## 7. Broader context (from project memory — nice to know, not blocking)

- There is a **three-rung autonomy charter** for a separate proactive agent (Rung 1 ideation/tech-debt
  map; Rung 2 issue-draft/code-quality; Rung 3 PR-review + **eval-harness execution**; Rung 4 excluded).
  Evalyn is essentially the **Rung-3 eval-harness** realized as its own project.
- A July-20 note also floated a broader "System Evaluation Agent" (services/deploy/DB/APIs). That is
  **explicitly deferred** — v1 is AI-behavior only (D1).

## 8. User working preferences (apply in the new session)

- **Git:** commit after each major *verified* development. **All commits under the user's name only,
  no Claude `Co-Authored-By` trailer.** Use `user.name='dashankanadeeshandesilva'`,
  `user.email='dashankadesilva@gmail.com'`. **Never push or open/update a PR without asking first.**
- **Quality over speed;** prefer Opus subagents for heavy work; return conclusions, not file dumps.
- **Verification before completion:** run/exercise before claiming done; evidence before assertions.
- **Scratch/handoff docs** go in temp locations unless asked otherwise (this doc was explicitly asked
  for, so it lives in the repo).
- This is a **fresh separate repo** (`/Users/dashankadesilva/Drive/Projects/Evalyn_eval_agent`), git
  initialized, `.gitignore` present. **Branch convention (user-decided 2026-07-22): for now, work on
  the main worktree and commit all docs to `master`.** Proper branch/PR conventions come later, when
  implementation starts. Not the niuwnai-mvp workflow (no `dev` branch here).

## 9. Repo state right now

- `docs/2026-07-21-evalyn-design.md` — the approved v1 design spec (source of truth).
- `docs/CONTEXT.md` — this file.
- `.gitignore` — runs/, venvs, `__pycache__`, `.env`, `.DS_Store`.
- **No source code yet.** Nothing under `src/`, no `packs/`, no `pyproject.toml`.
- Commits so far: design spec, then the Inspect-AI revision. Both under the user's name.

## 10. Next step

The brainstorming/design phase is **complete and approved**. The next action is to turn the design
into a **phased implementation plan** — invoke the **`superpowers:writing-plans`** skill against the
design doc. Do **not** start coding before the plan exists and the user approves it.

Phase-0 sanity checks — status:
1. **[still open]** Confirm the exact TwinCore visitor chat endpoint(s), session-open flow, and SSE
   event format from the live router + frontend (needed for `target.yaml`). Do this when authoring
   the TwinCore pack.
2. **[done 2026-07-22]** Inspect AI API surface confirmed via a working fit spike (Inspect 0.3.249) —
   see `2026-07-22-inspect-spike-findings.md`. Mapping validated; key finding: reducers are
   task-level, so per-probe pass/fail policy lives in Evalyn's own log-reading gate-diff layer.
3. **[done 2026-07-22]** Name settled: **evalyn** (free on PyPI + CLI). No rename needed.
