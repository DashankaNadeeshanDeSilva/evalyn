# Evalyn Plan #2a — Design spec: trusted gate on the real product

**Date:** 2026-07-24
**Status:** Approved design (brainstormed + user-locked 2026-07-24), pre-plan
**Scope authority:** [`docs/ROADMAP.md`](../../ROADMAP.md) § Plan #2 (this spec covers the **#2a** half)
**Predecessor:** Plan #1 gate foundation — merged to `dev` (PR #1, `d4ce297`), released v0.1.0

---

## 0. Scope and split

Plan #2 is split (user decision 2026-07-24):

- **#2a (this spec, this session):** TwinCore real-product target pack + transcript scoring +
  weighted-check semantics + Tier-3 G-Eval rubric judge + judge-calibration harness +
  `auth`/`budget` consumers + the full Plan-#2 openers backlog from `docs/JOURNAL.md`.
- **#2b (separate plan, fresh session after #2a merges):** blind `compare` (A/B) + CI automation
  (GitHub Action, PR comment). Not covered here beyond noting the Tier-3/calibration machinery
  built in #2a is its foundation.

Deliverable of #2a: **`evalyn gate --target packs/twincore` runs the real product with full
3-tier, calibrated, transcript-aware scoring** and a trustworthy verdict.

All Plan #1 architecture constraints carry forward unchanged: Inspect AI spine
(`inspect_ai>=0.3.249`), per-probe gate policy in Evalyn's gate-diff layer, async `httpx` only,
judge ≠ generator family, allowlist enforced fail-closed.

---

## 1. Transcript scoring (design-gap fix #1 — fail-closed defaults)

Today every scorer reads only `state.output.completion`; a leak in an earlier turn of a
multi-turn probe passes the gate. Fix — scorers become transcript-aware with **fail-closed
defaults by check type**:

1. **Tier-1 invariants** and **`not_contains` checks** scan **every assistant turn** in
   `state.messages`. Any violating turn fails the check for that trial; the artifact records
   which turn (index + excerpt).
2. **`contains` checks** keep final-reply semantics by default (they assert the eventual
   answer).
3. **Tier-2 and Tier-3 judge checks** receive the **full labeled transcript** (all turns,
   role-labeled) instead of only the final reply, and return one whole-transcript verdict.
   Tier-2 evidence quoting: the quoted span may come from any assistant turn.
4. New optional per-check field **`scope: final | any_turn | all_turns`** overrides the
   default. (`any_turn` = check passes if any assistant turn satisfies it; `all_turns` = must
   hold on every assistant turn; `final` = last assistant turn only.)

Aggregation: per-turn failures collapse into that trial's check verdict; **pass@k / pass^k
across trials is unchanged**. Safety-critical probes still gate on pass^k.

Consequence: the interim `validate-pack` warning on multi-turn `safety_critical` probes
(added in `ca025e9`) is **retired** when this lands.

## 2. Weighted / non-required check semantics (design-gap fix #2 — implement)

`Check.weight` and `required: false` become real, uniformly across tiers 1/2/3:

- Per trial: **any required-check failure → trial score `0.0` (fail).**
- If all required checks pass: **trial score = Σ(wᵢ × scoreᵢ) / Σ(wᵢ)** over non-required
  checks — binary checks contribute 0/1, rubric checks contribute their normalized 0–1 score.
  A probe with no non-required checks scores `1.0`.
- A **non-required** tier-2 classifier mismatch lowers the score instead of failing the trial
  (today it fails regardless of `required`).
- **Safety probes gate on pass^k of the binary required verdict, exactly as today.**
- Quality probes feed **mean trial score** into the existing band-vs-baseline comparison in
  gate-diff — the bands finally receive real (non-binary) inputs.

Schema docs and README drop the "declarative-only (Plan #2)" labels.

## 3. Tier-3 rubric judge (G-Eval)

New check type: `type: rubric`, `rubric: <id>` referencing a **pack-authored markdown rubric**
in `packs/<pack>/rubrics/`. Rubrics are always human-written, pinned, and hashed (hash recorded
in the run artifact). G-Eval's "generated" element is only the intermediate grading steps —
never the rubric.

- **Two-phase G-Eval:** (1) the judge expands the rubric into explicit evaluation steps —
  generated once per (rubric-hash × judge-model), cached, and embedded in the artifact for
  reproducibility; (2) the judge scores the full labeled transcript against those steps.
- **Scale:** 1–5 integer per criterion, forced JSON output with per-criterion justification,
  normalized to 0–1 for aggregation.
- **Self-consistency:** k=3 samples, **median** verdict; spread ≥ 2 points → the check is
  scored `unsure` (surfaced and counted via NOANSWER accounting, never averaged away; judge
  infra failure ≠ product failure).
- **Default posture:** rubric checks are `required: false` — they contribute weighted score
  and ride the baseline bands rather than hard-gating. A pack may mark one `required: true`
  consciously.
- **Judge-model policy:** the pack declares the tier-3 judge model and the target's model
  family. Engine **warns** (not errors) when judge family == generator family. CLI override:
  `--rubric-judge-model`. TwinCore is GPT-powered → default judge is a Claude model.

## 4. Judge calibration harness (fail-closed)

- **Anchors:** `packs/<pack>/anchors/*.yaml` — each anchor = full labeled transcript +
  rubric id + **human** 1–5 score per criterion + optional note. Human labels only; an LLM
  never authors them (that would calibrate the judge against a judge).
- **Agreement metric:** judge-vs-human within **±1 point** on the 1–5 scale, computed per
  (anchor × criterion); overall agreement must be **≥ 85%**.
- **New CLI command:** `evalyn calibrate --target <pack>` — runs the tier-3 judge over all
  anchors, prints a per-criterion agreement table, writes a **committed calibration record**
  into the pack (rubric hashes + judge model + agreement + date), exit 0/1.
- **Enforcement (fail-closed):** `gate` refuses to run rubric checks — setup error, exit 2 —
  when the calibration record is **missing or stale** (any rubric hash or the judge model
  differs from the record). Escape hatch `--allow-uncalibrated` downgrades to a loud warning
  and marks rubric scores untrusted in the artifact.

**Human dependency (planned as an explicit user task):** Claude captures ~15–20 fresh anchor
transcripts from the live TwinCore dev stack (probe definitions and "what good looks like"
from `E2E_WALKTHROUGH_M7.md` — the M7 doc holds hand-scored rubric *labels* but never
persisted the verbatim transcripts, so transcripts must be captured anew), formats them into
anchor YAMLs with blank score fields; **the user hand-scores 1–5 per criterion** (~30–60 min).
Only the final "calibration green on the real pack" acceptance step waits on those labels.

## 5. `auth` / `budget` consumers (A3 fields become real)

- **Auth (minimal):** `kind: none | bearer | header`; the solver applies the declared
  header/token to every request. TwinCore uses `none`, but the consumer exists and is tested.
  Cookie/OAuth flows stay out until a pack needs them.
- **Budget:**
  - `max_turns_per_session` — enforced in the solver: hard stop surfaced as a transport-level
    error (never a silent empty reply).
  - `max_usd_per_run` — meters **Evalyn's own judge spend** (tier-2 + tier-3 calls, via
    Inspect's usage accounting priced from a small static price table). Ceiling hit →
    graceful stop + partial artifact, never a surprise bill. **Target-side spend metering
    stays deferred** (roadmap already defers it; black-box targets rarely expose usage).
- **State (`checks` / `seed_fingerprint` / `reset`): stays declarative-only, re-deferred to
  Plan #3** with this documented reason: TwinCore's Twin is read-only, so there is no real
  consumer to exercise honestly; building it against nothing violates the working-software
  staging rule.

## 6. TwinCore target pack (`packs/twincore/`)

All facts below verified against the TwinCore repo
(`/Users/dashankadesilva/Drive/Projects/NiuwnAI/niuwnai-mvp`, branch `dev`) by recon on
2026-07-24. Re-verify at implementation time against the live code.

### 6.1 Target contract

- **Session open:** `POST /api/twin/{slug}/consent`, body `{"consent": true}` → response
  field `session_token` (Redis-backed, TTL 2h). Distinct failure statuses: 402 (owner monthly
  limit), 404 (unknown/unpublished slug).
- **Message:** `POST /api/twin/{slug}/chat`, body `{"message": <str 1..5000>,
  "session_token": <str>}` — the session token rides **in the JSON body** (not path, not
  header, not cookie). 401 = expired/invalid session; 429 = rate limit (30 msg/60s per
  session — harmless: every probe opens a fresh session); 503 = agent unavailable. The
  solver surfaces these as transport failures, never as empty replies.
- **Stream format — new adapter `named-sse`:** TwinCore emits named-event SSE
  (`event: token\ndata: {"type":"token","content":"..."}` frames; terminal `event: done`;
  mid-stream `event: error` must surface as a stream error). None of the three shipped
  adapters parse this. The adapter is **generic** (configurable event name + JSON field to
  extract), not TwinCore-specific — this is the design doc's "medium band" case arriving on
  schedule.
- **Pack-contract/solver extensions required:** configurable open-request body, configurable
  response field name for the session id, configurable message body shape (where the message
  text and session token are placed).
- **Auth:** `none`. **Base URL:** backend serves on port 8000 → allowlist
  `http://localhost:8000` + `http://127.0.0.1:8000`.

### 6.2 Probe suites (seeded from real history)

- **`injection.yaml` — port of the 31-case suite** (`backend/tests/live/
  test_guardian_injection_live.py`: 27 single-turn attacks + 1 multi-turn attack + 3
  controls; categories: direct, base64, unicode/leet, delimiter, role-play, scope, harmful,
  meta/exfil, translate, multi-turn, controls). **Black-box constraint (verified):**
  Guardian's block/redirect/allow verdict never reaches the SSE client — redirect text
  arrives as ordinary `token` frames with HTTP 200. **Porting design:** for the
  OUT_OF_SCOPE / INJECTION / HARMFUL categories the redirect text is a fixed first-person
  constant used verbatim (`guardian.py:39-51`), so attacks get a **required tier-1
  contains-one-of-the-redirect-constants check** plus the leak invariants (deterministic,
  free); the 3 controls and BOUNDARY-flavored cases (owner-customizable text) get a
  **tier-2 classifier check** ("substantive answer, not a deflection?"). If TwinCore edits
  the constants the probes fail loudly and the pack gets updated — intentional coupling,
  documented in the pack README. Base64 payloads are **hardcoded** in the YAML (the pytest
  suite computes them at runtime).
- **`grounding.yaml`** — factual/honesty probes vs the seeded real-CV KB; not-in-KB
  questions must acknowledge the gap (hallucination stays 0). Rubric + classifier checks.
- **`persona.yaml`** — first-person fidelity, AI-identity/META handling (F-5), tone / no
  third-person harsh redirects (F-4).
- **`scope.yaml`** — in-scope named-project questions answered, not over-blocked (F-12);
  true out-of-scope redirected.
- **`pii.yaml`** — contact info only when directly asked (F-6).
- All five findings are FIXED in TwinCore today → these probes are **`kind: regression`**
  (encode behavior the product now gets right). Aspirational behaviors (e.g. F-8
  relevance-based confidence nuances) may be added as `kind: capability`.

### 6.3 Rubrics and anchors

- **Rubrics** (from `Docs/AGENT_INTELLIGENCE_UPGRADE_2026-07.md` §7.3): **groundedness,
  completeness, persona, honesty-about-gaps** — four pinned markdown files.
- **Anchors:** ~15–20 fresh transcripts captured against the live dev stack (see §4),
  hand-scored by the user.
- **Invariants:** `first-person`, `no-internal-leak`, `non-empty` (the F-5 literal-"null"
  bug).

### 6.4 Acceptance dependency

Gate/calibration acceptance runs require the TwinCore dev stack running locally (user-assisted
step; `make`-based uvicorn on port 8000 with seeded twin + published slug).

## 7. Openers backlog — all ride along

Every Plan-#2 opener from `docs/JOURNAL.md` lands in #2a, attached as riders to the task
already touching that code:

| Rider | Rides on |
|---|---|
| Adapter-hardening bundle (malformed frames → `StreamFormatError`; vercel error frames surfaced; raw-sse single-space fidelity; interior `\r`; whitespace-fidelity decision; edge-case tests) + `named-sse` adapter + pooled httpx client | solver/stream task |
| Tier-2 normalization hardening (stopwords/min-floor, unicode punctuation) + tier-1 null-`value` guard | transcript-scoring task |
| `pack_fingerprint` over raw pack bytes; `out_dir` param + atomic artifact writes; NOANSWER accounting | artifact task |
| validate-pack lint: `kind: capability` + `safety_critical: true` contradiction warning | validate-pack/rubric-checks task |
| CLI `--debug` (re-raise), `--update-baseline` prints the verdict it blesses, `click>=8.2` floor, loader-hardening bundle (narrow `except`, `${VAR}` semantics, lowercase env names, `extra="forbid"` decision, static `event_format`/`stream` validation), shared conftest pack-writing fixture, two loose-test polish items (pin fix-8 `match`, fix-9 non-SSE guard note) | one standalone cleanup task |

## 8. Out of scope for #2a

- `compare` and CI automation (→ #2b).
- `state.*` consumers (→ Plan #3, reason in §5).
- Target-side spend metering; cookie/OAuth auth flows; simulated-user probe runner.
- Any TwinCore-repo code changes (Evalyn stays black-box; TwinCore keeps its in-process
  `-m live` suite).

## 9. Acceptance criteria (#2a definition of done)

1. Full test suite + `ruff` green (real output shown), `validate-pack packs/example` and
   `validate-pack packs/twincore` exit 0.
2. Multi-turn early-leak counterexample: a probe whose leak lands on a non-final turn is
   **caught** (test-pinned) — the design-gap #1 hole is demonstrably closed.
3. A non-required check mismatch produces a partial trial score that moves the baseline band
   comparison (test-pinned) — design-gap #2 demonstrably closed.
4. `evalyn calibrate --target packs/twincore` produces a committed calibration record with
   ≥ 85% agreement on the user-labeled anchors; `gate` demonstrably refuses rubric checks
   (exit 2) when the record is stale.
5. `evalyn gate --target packs/twincore` runs the full suite (31-case injection + grounding +
   persona + scope + pii) against the live dev stack with correct exit-code behavior and a
   self-contained artifact recording rubric hashes, judge model, per-turn violation data,
   pass@k/pass^k, and judge spend.
6. Budget: `max_turns_per_session` and `max_usd_per_run` (own-judge-spend) enforcement each
   demonstrated by a test.
7. `docs/JOURNAL.md` Plan-#2 openers section emptied (each item done or explicitly re-deferred
   with a reason); ROADMAP updated to record the #2a/#2b split.

## 10. Execution (locked machinery)

Feature branch off `dev` (`feat/plan2a-real-gate` or similar) → superpowers:subagent-driven
development (fresh Fable implementer per task, TDD inside every implementer, Fable task
reviews) → journal updated at every task completion → final whole-branch review →
finishing-a-development-branch. Commits under the user's name only; ask before any push/PR.
