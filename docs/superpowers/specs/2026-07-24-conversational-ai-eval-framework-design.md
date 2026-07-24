# Conversational AI Evaluation Framework — Design Spec

**Date:** 2026-07-24
**Status:** Approved design, pre-implementation
**Working name:** TBD — referred to as "the framework" / CLI placeholder `evaltool` throughout.
**Note:** This is a fresh, standalone design. It deliberately does NOT build on or assume the
existing Evalyn codebase.

---

## 1. What this is

An **open-source, vendor-neutral framework for evaluating conversational AI systems** — production
chatbots and agentic systems alike. A Python library + CLI that an engineer can install and run
against their own system in ~10 minutes.

**Core loop:**

1. Describe **scenarios** (simulated user persona + goal + expectations), not hand-written scripts.
2. A **simulator** drives real multi-turn conversations against the target system, *k* times per
   scenario (agents are stochastic — single runs lie).
3. A **tiered scoring pipeline** judges transcripts: deterministic checks → rubric LLM judges →
   panel escalation, with calibration against human labels and explicit abstention.
4. An **honest report**: pass^k reliability, per-dimension quality scores, judge confidence and
   agreement stats, CI exit code.

**Two differentiators** (chosen because no open tool ships them together, per landscape research
§2):

- **Deep conversation simulation** — persona-driven, goal-driven, deliberately non-cooperative
  user simulators; research-grade multi-turn rigor (τ-bench lineage) packaged for product
  engineers rather than safety researchers.
- **Trustworthy judging** — rubric judges with built-in calibration workflows, judge panels,
  confidence + abstention. "Who judges the judge" as a first-class feature.

**Locked product decisions** (from brainstorming session 2026-07-24):

| Decision | Choice |
|---|---|
| Product form | Open-source framework (library + CLI); engineer is primary user |
| Eval surface v1 | Offline simulation (CI-friendly); production traces later (v2+) |
| Access model | Black-box core (send messages ⇄ get replies) + optional trace enrichment |
| Target interfaces v1 | HTTP/streaming endpoint + Python callable |
| Differentiators | Simulation depth + judging trust (everything else is supporting) |
| Success bar | Credible OSS launch: pip-install → trustworthy report in 10 minutes |
| Spine | Purpose-built conversation-native core (NOT Inspect AI, NOT pytest plugin) |

---

## 2. Landscape context (July 2026) — why these choices

Condensed from the research run 2026-07-24 (web research agent; sources at end of that report):

- **Consolidation:** OpenAI Evals shuts down Nov 2026; Humanloop dead (team → Anthropic);
  Promptfoo acquired by OpenAI (Mar 2026, stays OSS); Langfuse → ClickHouse; TruLens → Snowflake.
  Practitioners actively fear lock-in ⇒ **genuine vendor-neutrality is a selling point**.
- **Two-tool norm:** teams cobble a code-first CI eval framework (DeepEval, Ragas, Promptfoo)
  plus a trace/observability platform (Langfuse, Phoenix, LangSmith). Only Braintrust unifies —
  closed SaaS.
- **Multi-turn is table stakes but shallow:** ICLR 2026 result — LLMs lose ~39% accuracy
  multi-turn vs single-turn. Real depth (τ²-bench dual-control, non-cooperative simulators,
  pass^k) lives in research frameworks (Inspect AI); product tools offer shallow simulation.
- **Judge trust unsolved in tooling:** calibration/juries/abstention research exists (PoLL,
  RubricEval, conformal abstention, cascaded selective evaluation) but no open tool ships
  calibration workflows or agreement stats.
- **Eval rot is the #1 practitioner complaint:** golden sets decay as products change; nobody
  automates production-failure → test-case well.

**Methods a credible 2026 tool must have** (research synthesis): user simulation with
non-cooperative personas; pass^k reliability reporting; trajectory + step-level scoring when
traces exist; rubric judges with binary/small-ordinal verdicts; judge panels + calibration +
abstention; OTel-compatible trace story (even if deferred); offline-gate discipline (baselines,
regression rules); conversation-level metric vocabulary (goal completion, coherence, instruction
retention, role adherence, repair).

**Rejected spine alternatives:**

- *Inspect AI (UK AISI):* battle-tested rigor, but sample-centric data model — multi-turn
  simulation and per-turn judging swim against its grain; heavy dependency; research/safety
  identity vs our product-engineer audience; our reporting ambitions live outside it anyway.
- *pytest plugin (DeepEval's path):* familiar DX, free CI semantics, but pytest's synchronous
  test-function model fights long-running simulated conversations, k-repeat sampling, cost
  budgets, and cross-run calibration state. DeepEval owns that niche; we'd be a worse DeepEval
  instead of a different thing. A thin pytest adapter ON TOP of our core is cheap later.

---

## 3. Core concepts & data model

Seven nouns. The **Transcript** is the center of gravity — conversation-first, not sample-first.

### 3.1 Target

The system under test, behind a minimal adapter protocol:

```python
class TargetAdapter(Protocol):
    async def send(self, conversation: Conversation) -> Reply: ...
    # Reply = content + optional TraceEvent list + latency/usage metadata
```

- **`HTTPTarget`** — OpenAI-compatible chat APIs, custom REST, SSE streaming. Config: base URL,
  headers/auth, request/response mapping (JSONPath-style extraction for custom schemas), stream
  format.
- **`PythonTarget`** — any in-process `async callable(conversation) -> reply` or agent object.
  Cheapest 5-minute on-ramp; naturally yields trace events (tool calls) for framework-embedded
  agents (LangGraph, Agent SDK wrappers are convenience sugar, not dependencies).
- **Trace events are optional enrichment**: if a Reply carries `trace: list[TraceEvent]`
  (tool calls with name/args/result, retrieval events, agent steps), trajectory-level scorers
  activate. Absent → pure black-box, everything else still works. **Graceful degradation is a
  hard design rule.**

```python
@dataclass
class TraceEvent:
    kind: Literal["tool_call", "retrieval", "agent_step", "custom"]
    name: str
    args: dict | None
    result: str | None
    error: str | None
    ts_offset_ms: int
```

### 3.2 Persona

A simulated user's identity. Fields:

- `name`, `traits` (free text: "impatient small-business owner, non-native English speaker")
- `tone` (formal / casual / terse / verbose)
- `knowledge: dict[str, str]` — **knowledge inventory**: facts the user knows. The simulator may
  only disclose an item when conversationally warranted (asked for it, or naturally relevant).
  What the persona does NOT know is as important as what it knows (realistic underspecification).
- `behavior: cooperative | underspecified | distracted | frustrated | adversarial` — the
  benevolence-bias control (see §4).
- Ships with a preset library (research-grounded archetypes); users define their own in YAML.

### 3.3 Scenario

The unit of testing. YAML for the common case, Python for the complex case — identical object
model either way.

```yaml
# scenarios/refund_no_order_number.yaml
id: refund-no-order-number
tags: [billing, safety:pii]
persona: presets/frustrated_underspecified   # or inline persona block
goal: >
  Get a refund for a damaged blender ordered last month. User does NOT know
  the order number; knows the email used (knowledge inventory).
environment:                  # facts about the world, given to simulator & judges
  order_number: "A-10442"     # exists but user doesn't know it
  policy: "refunds within 30 days with proof of purchase"
max_turns: 12
trials: 4                     # k; suite default if omitted
expectations:
  checks:                     # Tier 1 — deterministic
    - never_says: {pattern: "(?i)credit card number", scope: all_turns}
    - tool_called: {name: lookup_order, args_match: {email: "*"}}   # only if traces exist
    - max_cost_usd: 0.50
  rubrics:                    # Tier 2/3 — judged dimensions
    - goal_completion: {gate: required, threshold: pass}
    - coherence: {}
    - instruction_retention: {}
    - role_adherence: {persona_of_target: "polite support agent, never legal advice"}
perturbations: [typos: light, topic_drift: once]
```

- **`checks`** = deterministic (Tier 1). **`rubrics`** = LLM-judged (Tier 2/3).
- `tags` drive gate policy (e.g., anything tagged `safety:*` gates on pass^k).
- **Dual-control readiness:** schema reserves `user_tools:` (tools the *simulated user* can
  invoke, τ²-bench style) — parsed and validated from v1, implemented post-v1. Schema-now
  avoids a breaking change later.

### 3.4 Trial & Transcript

- **Trial** = one simulated conversation of a scenario. `k` trials per scenario (default 4).
- **Transcript** = ordered turns: `role, content, ts, latency_ms, usage(tokens/cost),
  trace: [TraceEvent]`, plus conversation-level: `stop_reason: goal_met | user_gave_up |
  max_turns | target_error`, simulator's per-turn `goal_progress: met | partial | blocked`
  annotations, total cost/latency.
- Transcripts are **immutable artifacts**: re-scoring never re-simulates (cache by scenario
  hash + seed + target config hash).

### 3.5 Verdict

Output of scoring one trial:

```python
@dataclass
class DimensionVerdict:
    dimension: str                  # "goal_completion", "coherence", ...
    verdict: Literal["pass", "fail", "abstained", "errored"]
    score: float | None             # small-ordinal mapped to [0,1] when applicable
    confidence: float | None        # judge self-consistency / panel agreement
    tier: Literal[1, 2, 3]          # which tier produced the final verdict
    rationale: str                  # judge reasoning or check detail
    evidence_turns: list[int]       # turn indices the verdict anchors to
```

**Abstention is a first-class verdict** — excluded from pass-rate denominators, routed to the
review queue (§6.4), never counted as a silent guess.

### 3.6 Run

All scenarios × k trials. Persisted as `runs/<timestamp>/`:

- `manifest.json` — target config hash, simulator/judge model IDs + versions, seeds, prompt
  hashes, framework version, git SHA of the suite. **Reproducibility contract.**
- `transcripts.jsonl`, `verdicts.jsonl` — one object per line, diffable.
- `report.html` — self-contained (no CDN), drill-down.
- `review_queue.jsonl` — abstained/failed items awaiting human labels.

---

## 4. Simulation engine

An LLM plays the user, conditioned on persona + goal + environment. Design rules:

1. **Benevolence-bias control.** The known failure of naive simulators: they volunteer
   information real users withhold. Mitigations:
   - Simulator prompt receives the **knowledge inventory** with an explicit disclosure rule:
     reveal an item only when asked or clearly conversationally warranted.
   - `behavior` policies change the interaction contract: `underspecified` opens vague and
     answers minimally; `distracted` injects topic changes; `frustrated` escalates tone on
     unhelpful replies; `adversarial` probes boundaries (scope for v1: mild social pressure,
     NOT jailbreak automation — that's Promptfoo's lane).

2. **Structured goal-state tracking.** Each simulator turn emits JSON alongside the message:
   `{message, goal_progress: met|partial|blocked, wants_to_stop: bool, stop_reason?}`.
   Conversation ends on: goal met, user gives up (patience is a persona parameter), or
   `max_turns`. The stop reason feeds scoring directly ("did the user have to give up?" is
   itself signal).

3. **Perturbation dials** (scenario- or suite-level): `typos: off|light|heavy`,
   `topic_drift: never|once|recurring`, `self_contradiction: bool` (user changes a stated fact
   mid-conversation — tests target's repair behavior), `goal_shift: bool` (mid-conversation goal
   change — MultiChallenge-style instruction-retention stressor). Implemented as prompt-level
   injections into the simulator, logged per turn so judges can distinguish user noise from
   target failure.

4. **Model independence.** Simulator model family is configurable, independent of both judge and
   target families. Default: capable-but-cheap tier. One simulator LLM call per user turn.

5. **Determinism & cost.** Seeded sampling where provider supports it; all prompts + configs
   hashed into the manifest; per-run **cost budget with hard abort** (partial results clearly
   marked); transcript cache keyed by (scenario hash, seed, target config hash).

**Out of scope v1** (schema-ready where noted): dual-control user tools (`user_tools`, §3.3);
voice/audio; multi-party conversations; adaptive adversarial attack agents (GOAT/Crescendo
class).

---

## 5. Scoring & judging pipeline

Three tiers, cheapest first, per transcript. Tier flow:

```
Transcript ─→ Tier 1 checks ─(hard fail: short-circuit)─→ Verdict(fail, tier=1)
                 │ pass
                 ▼
             Tier 2 rubric judges (one judge per dimension)
                 │ confident verdict ─→ Verdict(tier=2)
                 │ low confidence / near gate threshold
                 ▼
             Tier 3 panel (3 diverse judge families, majority vote)
                 │ agreement ─→ Verdict(tier=3)
                 │ persistent disagreement
                 ▼
             ABSTAIN → review queue (needs_human)
```

### 5.1 Tier 1 — deterministic checks (free, instant)

- Content: `never_says` / `must_say` regex/substring, scanned across **all turns** (not just the
  final reply — leaks in turn 2 count).
- Trace (when events exist): `tool_called` (name, args pattern), `tool_not_called`
  (forbidden tools), arg validity, call ordering.
- Structural: turn count bounds, per-turn latency ceiling, cost ceiling, stream well-formedness.
- A tier-1 **hard failure short-circuits** — no judge tokens spent on a transcript that leaked a
  credit card. (Checks can be marked `severity: hard | soft`; soft failures record but don't
  short-circuit.)

### 5.2 Tier 2 — rubric judges

- One LLM judge call per rubric dimension per transcript. G-Eval-lineage prompt structure:
  explicit rubric text, forced reasoning-then-verdict, **binary or small-ordinal (≤4-point)
  verdicts** — Likert 1–10 is noise per the research.
- Built-in dimension library (each a versioned rubric file, overridable):
  `goal_completion`, `coherence`, `instruction_retention`, `knowledge_retention`,
  `role_adherence`, `tone`, `groundedness` (vs `environment` facts), `repair` (recovery after
  user contradiction/correction), `efficiency` (goal met without needless turns).
- Bias mitigations: evidence-turn citation required; verbosity guard in rubric; judge model
  family ≠ target model family **enforced with a loud warning** (override flag exists).
- Judge self-confidence estimated via N=2 sampled self-consistency on cheap dimensions, single
  call + logprob-free heuristics otherwise (exact mechanism per dimension, tuned during
  implementation; the contract is: every tier-2 verdict carries `confidence`).

### 5.3 Tier 3 — panel escalation

- Triggers: tier-2 confidence below threshold, OR verdict lands near a gating threshold
  (borderline), OR dimension is tagged `panel: always` in the scenario.
- Panel = 3 judges from **diverse model families** (PoLL finding: disjoint small-model panels
  beat single large judges and cancel self-preference bias). Majority vote; disagreement
  recorded as reduced confidence.
- Persistent disagreement (no majority, or majority with low aggregate confidence) →
  **abstention**, routed to review queue. Abstained verdicts are excluded from pass-rate
  denominators and surfaced prominently in the report.

### 5.4 Calibration workflow (`evaltool calibrate`) — the trust layer

- Input: human-labeled transcripts ("anchors"). The labeling CLI (`evaltool review`, §6.4)
  produces them; a starter flow guides labeling ~20 transcripts per dimension.
- Measures **judge–human agreement per dimension**: Cohen's κ (binary) / weighted κ
  (small-ordinal). Report per dimension: κ, raw agreement %, confusion table, worst
  disagreements (linked to transcripts).
- **Certification gate:** a dimension whose κ < threshold (default 0.6) is marked *uncalibrated*;
  the run report badges its scores as untrusted, and gate policy can refuse to gate on
  uncalibrated dimensions. The tool tells you *which* rubric needs work before you trust CI on
  it.
- Anchors are versioned files in the suite repo; rubric edits invalidate certification
  (rubric hash recorded with κ) — recalibrate after rubric changes. Our own repo eats this dog
  food (§9).

### 5.5 Aggregation honesty

- Per scenario: report **pass@1 AND pass^k** (pass^k = all k trials pass — τ-bench finding:
  GPT-4o 61% pass@1 → 25% pass^8; single-run scores overstate reliability).
- Safety-tagged scenarios (`safety:*`) gate on **pass^k** by default.
- Suite-level dimension scores come with variance across trials (k gives real spread) and
  confidence intervals; judged metrics always display adjacent judge-agreement stats.

---

## 6. Reporting, CI & the feedback loop

### 6.1 CLI surface (v1)

```
evaltool init                 # scaffold suite + demo MockTarget, runs out of the box
evaltool run suite/ [--gate baseline.json] [--budget 5.00] [--trials 4]
evaltool diff runs/A runs/B   # per-scenario deltas with CIs
evaltool calibrate suite/     # judge-agreement report + certification
evaltool review runs/<ts>/    # step through review queue, label, promote
evaltool validate suite/      # schema check scenarios/personas/rubrics, no LLM calls
```

### 6.2 Reports

- **Terminal:** live progress; final table — scenario × {pass@1, pass^k, dimensions, cost,
  latency, abstentions}.
- **HTML (self-contained, no CDN):** drill-down: suite → scenario → k trials → transcript with
  per-turn annotations (which turn a judge cited as evidence, where a check fired, perturbation
  injection points). This is the launch demo artifact.
- **JSONL:** everything machine-readable for downstream tooling.

### 6.3 CI gating

- `--gate` evaluates an explicit **gate policy** (config, not convention):

```yaml
# gate.yaml
required_scenarios: [refund-*, safety-*]
dimension_gates: {goal_completion: {min_pass_rate: 0.9}, role_adherence: {min_pass_rate: 0.95}}
safety_rule: {tags: ["safety:*"], require: pass_all_trials}     # pass^k
regression_rule: {vs: baseline.json, max_drop: 0.05}            # decay can't slip through
uncalibrated_dimensions: warn | block
error_budget: {max_errored_trial_fraction: 0.1}                 # else run refuses to gate
```

- Exit codes distinguish: `0` pass · `1` quality gate failed · `2` run invalid (error budget
  exceeded, budget abort) · `3` config error. **"Quality failed" ≠ "run broken"** — CI must
  never confuse them.
- GitHub Action wrapper ships day one.

### 6.4 Review queue — the eval-rot answer

- Abstained + failed trials land in `review_queue.jsonl`.
- `evaltool review` steps through them in the terminal: shows transcript + judge rationale,
  human enters label + note.
- Each labeled item can be **promoted** in one command to:
  - a **calibration anchor** (improves/certifies judges), or
  - a **new scenario** seeded from the real failure (goal + persona sketch auto-drafted from
    the transcript, human edits).
- Datasets, rubrics, anchors, personas: all **versioned files in git** — eval evolution is
  code-reviewed like code. No hidden state, no SaaS dependency.

---

## 7. Extensibility

Four plugin points — Python protocols + entry-point registration
(`[project.entry-points."evaltool.plugins"]`):

| Protocol | Purpose | v1 built-ins |
|---|---|---|
| `TargetAdapter` | talk to systems under test | HTTP(+SSE), PythonCallable, MockTarget |
| `Check` | deterministic tier-1 checks | content/trace/structural set (§5.1) |
| `Judge` | rubric dimensions / judge backends | rubric-judge over any LiteLLM-style provider |
| `Reporter` | output formats | terminal, HTML, JSONL (JUnit XML, Slack, OTel export later) |

**The OTel bridge lives here (v2+):** a future `TraceIngestor` maps `gen_ai.*` /
OpenInference spans into our `TraceEvent`/`Transcript` schema, so the **same scorers, rubrics,
calibration, and gate policies run on ingested production traces** as on simulated
conversations. This is the offline→online unification story — deferred, but architecturally
paid for by keeping Transcript the universal substrate.

**Model access:** all LLM calls (simulator, judges) go through one thin async provider layer
(async `httpx`; provider-agnostic; no LangChain dependency — neutrality is strategy, and heavy
deps are how neutrality dies).

---

## 8. Error handling — trustworthy under failure

| Failure | Handling |
|---|---|
| Target timeout / 5xx / malformed stream | Trial marked `errored`, NEVER `failed`. Configurable retry w/ backoff. Infra noise must not pollute quality metrics. |
| Errored-trial fraction > budget | Run refuses to gate; exit code 2 ("run invalid" ≠ "quality failed"). |
| Simulator/judge API failure | Bounded retries → abstention. **Never a silent default score.** |
| Cost budget exceeded | Graceful abort; partial results persisted and clearly badged partial; exit 2. |
| Scenario/config schema errors | Fail fast at `validate`/startup with file+line diagnostics, before any LLM spend. |
| Judge output unparseable | One re-ask with format reminder → abstention. Parsed with strict schema, not regex scraping. |

---

## 9. Testing the framework itself

- **Unit tests:** recorded/mock LLM responses; zero live LLM calls in CI.
- **`MockTarget`:** scripted conversational failure modes (forgets instructions, leaks a secret
  on turn n, calls wrong tool, infinite clarification loop). Doubles as our integration-test
  fixture AND the user's `evaltool init` demo — first run works with no API keys against
  MockTarget + a mock judge, so time-to-first-report is minutes.
- **Meta-eval suite (dog food):** judge rubric prompts are tested against a small labeled
  transcript corpus pinned in the repo; a rubric/prompt change that drops κ below threshold
  **fails our own CI**. The calibration machinery (§5.4) is the test harness.
- **Integration tests:** full loop (simulate → score → report → gate) against MockTarget.
- **Live smoke suite** (manual/nightly, not CI): tiny run against real providers to catch API
  drift.

---

## 10. Scope ledger

### v1 (launch)

Simulation engine (personas, knowledge inventory, behavior policies, perturbations, goal
tracking) · HTTP + Python targets · trace-event enrichment · Tier 1/2/3 scoring · dimension
library · calibration workflow + certification · pass@1/pass^k · terminal + HTML + JSONL
reports · gate policy + GitHub Action · diff · review queue + promotion · MockTarget +
no-API-key first run · plugin protocols.

### v2+ roadmap (explicitly deferred, in rough priority order)

1. **Local web UI** — run launcher, live run control, interactive report exploration
   (user-requested headline v2 item). Groundwork already paid: runs are JSONL + manifest a
   local server can render.
2. **Dual-control scenarios** — `user_tools` implementation (τ²-bench regime).
3. **OTel/OpenInference trace ingestion** — production-trace evaluation on the same metric
   definitions (`TraceIngestor`).
4. **pytest adapter** — thin layer exposing scenarios as tests.
5. Trained/local judge models as `Judge` backends; conformal abstention upgrades.
6. Adaptive adversarial simulation (GOAT-class) — only if it doesn't dilute the neutral-eval
   identity.
7. Voice/audio targets; multi-party conversations.

### Non-goals

Observability/APM platform · prompt-management/registry · hosted SaaS (nothing in the design may
*require* a server) · jailbreak-attack research tool · framework-specific (LangChain etc.)
coupling in the core.

---

## 11. Open questions for the implementation plan

1. Package/CLI name (working placeholder `evaltool`).
2. Exact judge-confidence mechanism per dimension (§5.2 contract fixed; mechanism tuned during
   implementation).
3. Default model choices per role (simulator/judge tiers) and the provider-layer shape.
4. HTML report implementation approach (static template + embedded JSON vs small JS bundle).
5. Python floor (3.11 vs 3.12) and packaging (`uv`-first assumed).

---

## 12. Decision log

| # | Decision | Why |
|---|---|---|
| D1 | Open-source framework, engineer-first | Adoption path; community; hosted layer possible later |
| D2 | Offline simulation before production traces | Clear v1 scope; CI-friendly; demo-able standalone |
| D3 | Black-box core + optional trace enrichment | Universal applicability + agentic depth when available; graceful degradation |
| D4 | Differentiators: simulation depth + judge trust | The two least-served gaps in the 2026 landscape; they compose (sim generates, judges score) |
| D5 | HTTP + Python callable targets in v1 | Covers most real systems + 5-minute on-ramp |
| D6 | Credible-OSS-launch success bar | Scoping discipline: polish the 10-minute path over feature breadth |
| D7 | Purpose-built core; no Inspect, no pytest spine | Conversation-native data model IS the product; tiny dep footprint IS the neutrality story |
| D8 | Binary/small-ordinal judge verdicts only | Likert 1–10 is noise (research consensus) |
| D9 | Abstention excluded from pass rates | Honest metrics; silent guessing is how judges lose trust |
| D10 | `errored` ≠ `failed`; run-invalid ≠ gate-fail | Infra noise must never masquerade as quality signal |
| D11 | Transcripts immutable; re-score without re-simulate | Cost control; reproducibility; enables future trace ingestion |
| D12 | Everything versioned in git, no hidden state | Eval evolution code-reviewed; no SaaS dependency |
| D13 | Web UI deferred to v2 (user decision) | v1 stays CLI-first; JSONL+manifest groundwork suffices |
