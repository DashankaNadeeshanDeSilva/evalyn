# Session-3 handoff — Evalyn Plan #2a, resume at Task 11

Written at the end of session 2 (2026-07-25). Session 2 executed **Tasks 6–10** of Plan #2a on
`feat/plan2a-real-gate`. Session 3 resumes at **Task 11 (human-gated)** and finishes the plan.

Everything below the line is the kickoff prompt — paste it as the opening message of the new
session. It is written to be self-sufficient: it names every file, command, decision, and open
question session 3 needs, so nothing depends on this session's memory.

---

## Your role

You are the **lead engineer and execution controller for Evalyn** — a standalone,
project-agnostic evaluation agent for LLM-powered products (`gate`, `compare`, `discover`),
built on Inspect AI, public and MIT-licensed. You work with me — the maintainer and final
decision-maker — and you **delegate every implementation task to a fresh Fable subagent**
rather than coding it yourself. Your job is orchestration, review, verification, and keeping
the plan honest.

## Your mission

**Finish Plan #2a: Task 11 (human-gated) → Task 12 → Task 13 → final whole-branch review →
push + PR to `dev`.** Sessions 1 and 2 completed Tasks 1–10; every task was reviewed,
controller-verified, and committed. You pick up mid-plan on a green branch.

**Task 11 is the human checkpoint you start on.** It cannot be automated: it needs my live
TwinCore stack, my `ANTHROPIC_API_KEY`, and ~30–60 minutes of my hand-scoring. Prepare
everything preparable, then hand me precise instructions and wait.

## Source documents (read these first)

| Document | What it is |
|---|---|
| `docs/superpowers/plans/2026-07-24-evalyn-plan2a-real-gate.md` | **The authoritative worklist** — 13 tasks, exact files, full code, full test code, commit steps. Task 11 starts at the `## Task 11:` heading. |
| `docs/superpowers/specs/2026-07-24-evalyn-plan2a-design.md` | Design rationale behind the plan. |
| `docs/CONTEXT.md` | Orientation, locked decisions, working preferences. |
| `docs/JOURNAL.md` | **The committed execution record.** Its `## Plan #2a` section holds the task table (Tasks 1–10 with commit SHAs), the four pre-flight amendments, and the live **deferred-findings register** — the main input to the final review. |
| `docs/EVALYN_EXPLAINED.md` | Plain-English overview of what Evalyn is. |
| `docs/ROADMAP.md` | How the three plans stage; Task 13 must record the #2a/#2b split here. |
| `.superpowers/sdd/progress.md` | Gitignored session ledger — full dispatch-note history for Plans #1 and #2a. Its Plan #2a section starts at the line `# SDD progress ledger — Plan #2a trusted gate on real product`. |
| `.superpowers/sdd/plan2a-constraints.md` | Gitignored. The Global Constraints + Shared `CheckResult` Contract block handed to every implementer and reviewer. **Recreate from plan lines 15–57 if missing.** |

## Environment & commands

- Package manager is **`uv`** (`~/.local/bin/uv`); venv is `.venv` (Python 3.12).
  **Gotcha:** system `python3` is 3.9 — too old for Inspect. Always go through `uv run`.
- `uv sync` — install. `uv run pytest -q` — tests. `uv run ruff check src/ tests/` — lint.
- `uv run evalyn gate --target <pack> [--judge-model …] [--rubric-judge-model …]
  [--allow-uncalibrated] [--baseline runs/baseline.json] [--update-baseline] [--dry-run]`
- `uv run evalyn calibrate --target <pack> [--rubric-judge-model …]`
- `uv run evalyn validate-pack <pack>` (positional argument, not `--target`)
- Practice target: `uv run python examples/toy_target.py` → serves `127.0.0.1:8899`.
- Env vars in play: **`EVALYN_TARGET_URL`** (points the engine at a target) and
  **`EVALYN_TWIN_SLUG`** (TwinCore pack session paths; defaults to `eval-twin`).
- TwinCore product repo (READ-ONLY, never modify):
  `/Users/dashankadesilva/Drive/Projects/NiuwnAI/niuwnai-mvp`, branch `dev`.

## Where the branch stands (verified 2026-07-25, end of session 2)

Branch **`feat/plan2a-real-gate`**, cut from `dev` @ `e30afbf`. Merge target: `dev` via PR at
plan end (ask first).

| Commit | Task | What landed |
|---|---|---|
| `6de3766` | 1 | Transcript-aware Tier-1, `CheckResult`, `Check.scope`, `values` OR-list |
| `65a36a5` | 2 | Tier-2 full-transcript judge, per-check NOANSWER, `_normalize` hardening |
| `a310844` | 3 | `aggregate_trial` weighted formula, metadata-driven reducer, `ProbeResult` reshape, gate bands on mean trial score — **design-gap #2 closed at engine level** |
| `53c58ee` | 4 | Tier-3 G-Eval rubric scorer (per-criterion, k=3 medians, cached steps) |
| `7d35fe7` | 5 | Calibration harness, `evalyn calibrate`, fail-closed gate |
| `7d44b5d` | — | docs: session-2 handoff |
| `42e4e57` | 6 | named-sse adapter, session flow, auth, `max_turns` cap, stream hardening |
| `d274e8a` | 7 | Judge-spend metering vs `max_usd_per_run`, partial-artifact-before-raise |
| `bab3c14` | 8 | Raw-bytes fingerprint, `out_dir`, atomic artifact write, NOANSWER totals |
| `5659b40` | 9 | validate-pack: rubric-ref checks, P4 exclusivity, contradiction warning, interim multi-turn warning retired |
| `c2f1dde` | 10 | **TwinCore reference target pack** (see the Task 10 note below) |

- **Push state: only `6de3766..7d44b5d` is on `origin`.** Session 2's commits (`42e4e57`
  onward) are **local only** — pushing needs my explicit approval.
- Last verified green: **243 passed** (`uv run pytest -q`), **`uv run ruff check src/ tests/`
  clean**, `uv run evalyn validate-pack packs/twincore` → exit 0, zero warnings.
  Re-verify all three before dispatching anything and report the numbers.
- Test-count trail (useful as a regression sanity check): 197 @ T5 → 217 @ T6 → 225 @ T7 →
  228 @ T8 → 236 @ T9 → 243 @ T10.
- Every task ran: fresh Fable implementer (TDD) → fresh Fable task review → fix round if
  needed → scoped re-review → controller-verified pytest/ruff → commit + journal + ledger.
  **Zero open Critical/Important findings.** All Minors sit in the journal register with owners.

## Code map (what exists now)

```
src/evalyn/
  cli.py                  gate / calibrate / validate-pack commands (typer)
  engine/
    run.py                run_gate, RunArtifact, _reduce_log_to_probes, _judge_usd,
                          pack_fingerprint, atomic artifact write
    gate.py               evaluate_gate — bands + pass^k policy (Evalyn's own layer)
    baseline.py           baseline read/write/diff
    solver.py             Inspect Solver: session flow, auth, max_turns, per-solve httpx client
    task_builder.py       builds the Inspect Task; wires the three scorers
    calibrate.py          load_anchors, run_calibration, write_record, is_stale
    budget.py             PRICES, price_for, estimate_cost, BudgetExceeded
    validate.py           validate-pack rules
  scoring/
    transcript.py         assistant_turns(state), labeled_transcript(state)
    checks.py             check_result(...), aggregate_trial(...)
    tier1.py              deterministic checks (contains/not_contains/invariants, scope-aware)
    tier2.py              full-transcript classifier judge
    tier3.py              G-Eval rubric scorer (per-criterion 1–5, k=3 medians)
    rubrics.py            load_rubric, grading_steps (cached, atomic write)
  targets/
    loader.py             load_pack, Pack (incl. raw_files), resolve_base_url, ${…} resolution
    schema.py             pydantic models: TargetSpec, SessionEndpoint, AuthSpec, Probe, Check
    streams.py            adapters: vercel-ai, raw-sse, named-sse, json + StreamFormatError
    auth.py               auth header construction (none / bearer / header)
packs/example/            toy practice pack
packs/twincore/           REAL pack: target.yaml, probes/{grounding,injection,persona,pii,scope}.yaml,
                          rubrics/{persona,groundedness,honesty,completeness}.md, README.md, anchors/
examples/toy_target.py    practice target on 127.0.0.1:8899
tests/                    mirrors src layout + test_cli.py, test_e2e_gate.py, test_example_pack.py,
                          tests/packs/test_twincore_validate.py
```

## Interfaces you will build on (as actually shipped)

**Scoring / trust half (sessions 1)**
- `scoring/transcript.py` — `assistant_turns(state)`, `labeled_transcript(state)`.
- `scoring/checks.py` — `check_result(check, tier, required, weight, passed, score, turn=None,
  evidence="", unsure=False)` → the 9-key Shared-Contract dict; `aggregate_trial(checks)` →
  `(required_pass, trial_unsure, trial_score)`, contract-literal
  (`required_pass = all(passed is True)` over required checks).
- Every scorer emits `Score(value=…, metadata={"checks": [CheckResult, …]})`. The reducer in
  `engine/run.py` iterates whatever scorers exist in `sample.scores` (no hardcoded list) and
  reads **only** metadata checks; a trial with no checks anywhere is not a trial ⇒ MISSING
  hard-fails. Old-schema and corrupt-JSON baselines each fail loudly with distinct messages.
- `scoring/tier3.py` — `score_transcript(rubric_text, rubric_hash, transcript, judge_model,
  k=, cache_dir=) -> RubricScore` (`.medians: dict[str,int] | None`, None iff `.unsure`).
  Per-criterion 1–5 forced JSON, strict parse, median per criterion, any spread ≥ 2 ⇒ unsure;
  check score = mean of (median−1)/4; `passed` = mean of medians ≥ 4 (user-confirmed).
- `scoring/rubrics.py` — `load_rubric(pack, rubric_id) -> (text, hash)`; `grading_steps(…)`
  cached per (rubric-hash × judge-model), atomic write. **Criteria = the `##` headings.**
- `engine/calibrate.py` — `load_anchors`, `run_calibration` (reports unmatched human labels via
  `CalibrationResult.unmatched`; judge-unsure counts as disagreement), `write_record` /
  `is_stale`. **Stale = missing record | judge model differs | any pack-referenced rubric
  uncovered or changed | agreement < 0.85** (exact 0.85 passes, boundary test-pinned).
- CLI behavior: `gate` refuses rubric checks with **exit 2 on missing/stale calibration BEFORE
  any eval spend** (zero-rubric packs unaffected); `--allow-uncalibrated` = loud stderr warning
  + `RunArtifact.rubric_scores_untrusted=True`; `--rubric-judge-model` threads identically into
  both `is_stale` and `build_task`. Judge-family == generator-family ⇒ `warnings.warn`, never error.

**Transport (Task 6)**
- `targets/streams.py` — generic **`named-sse`** adapter, configurable `event=` / `field=`
  (defaults `"token"` / `"content"`), nothing product-specific. Malformed frames raise
  `StreamFormatError`; vercel `3:` / `e:` error frames surface as errors; raw-sse strips
  exactly one space after `data:`; named-sse strips interior `\r`.
- `targets/auth.py` — auth headers for kinds `none` / `bearer` / `header`.
- `targets/schema.py` — `SessionEndpoint` flow fields (`open_body`, `session_id_field`,
  `message_field`, `session_field`); `event_format` validated **at pack-load time** against the
  four adapters; `AuthSpec` with Literal kinds; `TargetSpec.auth`.
- `engine/solver.py` — httpx `AsyncClient` created **per `solve()`** (P3 — locked; do not add
  cross-sample pooling), auth headers applied, URLs resolved **only** via `resolve_base_url()`,
  `max_turns_per_session` breach raises a loud `RuntimeError` naming the cap **before any HTTP**,
  and `state.messages` user/assistant alternation is preserved (test-pinned — the transcript
  helpers depend on it).

**Budget (Task 7)**
- `engine/budget.py` — `PRICES`, `price_for`, `estimate_cost`, `BudgetExceeded`.
- `engine/run.py` — `_judge_usd()` meters **post-hoc, after `inspect_eval` returns**; there is
  **no mid-run stop** (documented in four places). `RunArtifact.judge_usd`. The artifact is
  written **BEFORE** `BudgetExceeded` raises so a partial artifact survives a breach
  (test-pinned). CLI maps `BudgetExceeded` → clean exit 2. The brief-verbatim `except → 0.0`
  fail-open path is guarded by import-canary tests plus a loud `RuntimeWarning`.

**Artifacts (Task 8)**
- `pack_fingerprint` hashes the **raw pack bytes** captured in `Pack.raw_files`, so
  `localhost` vs `127.0.0.1` env resolution no longer changes the hash. `run_gate(…,
  out_dir="runs")` (param appended last; all call sites pass keywords). Artifact writes are
  atomic (`mkstemp` + `os.replace` — the Task-5 house pattern).
  `RunArtifact.total_unsure_trials` surfaces NOANSWER accounting distinctly from failures.

**Validation (Task 9)**
- `engine/validate.py` — P4 `value` XOR `values` on `contains` (both or neither = error); a
  dedicated error for the `values:`-on-`not_contains` typo; static rubric-ref validation
  (missing/blank id, nonexistent `rubrics/<id>.md`) whose message teaches the `##`-headings
  convention; `kind: capability` + `safety_critical: true` **warning**; interim multi-turn
  warning retired. Validation mirrors the Tier-1 scorer exactly: label `contains:a|b`,
  case-insensitive matching. README documents the rubric convention for pack authors.

**TwinCore pack (Task 10)**
- `packs/twincore/target.yaml` — consent → chat named-sse flow, allowlist exactly
  `http://localhost:8000` + `http://127.0.0.1:8000`, session paths templated with
  `${EVALYN_TWIN_SLUG:-eval-twin}`, `generator_family: openai`, rubric judge
  `anthropic/claude-3-5-sonnet-latest` (judge ≠ generator family).
- `probes/injection.yaml` — the 31-case port (27 single-turn attacks + 1 multi-turn + 3 real
  controls), base64 payloads **hardcoded literal**, YAML anchors `&attack_checks` /
  `&injection_redirect` keeping the constant coupling visible in one place.
- `probes/{grounding,persona,scope,pii}.yaml`; `rubrics/{persona,groundedness,honesty,
  completeness}.md` (criteria = `##` headings); `README.md` documenting the coupling, the
  BOUNDARY exclusion, and the anchor-file shape.
- `targets/loader.py` — **`${…}` env resolution now also applies to `sessions.*.path`**
  (7-line extension after `raw_files` capture); the fingerprint deliberately hashes the
  **unresolved** bytes, which is test-pinned.
- 50 probes total; `validate-pack packs/twincore` exits 0 with zero warnings.

## Task 10 note (read before Task 11)

Task 10 was reported DONE_WITH_CONCERNS and reviewed **Approved** (no Critical/Important).
Six deviations were disclosed and all verified acceptable by the reviewer:

1. Session paths use `${EVALYN_TWIN_SLUG:-eval-twin}` **with default-value syntax** — a bare
   `${…}` would yield `/api/twin//consent` (a silent 404). Treated as an improvement.
2. Attack probes rely on the `no-internal-leak` invariant instead of the brief's extra
   `not_contains: "system prompt"` — verified genuinely redundant: the invariant regex at
   `src/evalyn/scoring/tier1.py:11` is `system prompt|/data/|internal path`, case-insensitive.
3. Multi-turn probes reuse the upstream turn texts verbatim (the brief asked for a faithful port).
4. A single `category: injection` — the 3 real upstream controls satisfy the balance lint;
   inventing controls would have been worse.
5. **Not-in-KB honesty classifiers are non-required**, exactly as brief Step 3 prescribes.
   **This is an open policy question for me** — see the journal register. Flip them to
   `required: true` if hallucination-on-unknown must hard-fail the gate. Ask me during Task 11.
6. The pack has never run against a live TwinCore stack — that is precisely what Task 11 is.

**Live-run caveat to expect in Task 11:** if Guardian classifies an attack as `BOUNDARY` and
the twin owner authored custom redirect text, the reply matches none of the three redirect
constants, so the required `contains` check fails **on a safe block**. This is fail-loud by
design and README-documented — do not "fix" it by weakening the check; bring it to me.

Contract re-verification (read-only, done at implementation time) confirmed every item against
`niuwnai-mvp@dev` HEAD `9f30e8a`: consent → `session_token`, chat with the token in the JSON
body, `event: token`/`done`/`error`, port 8000, unauthenticated, Guardian constants at
`guardian.py:39–51`, 27+1+3 = 31 cases, base64 payloads recomputed and matching. Nothing in
that repo was modified. One cosmetic upstream nit: a source comment says "28 single-turn
attacks" where the list has 27.

## Locked decisions and plan amendments (do NOT re-litigate)

All session-1 kickoff decisions stand: transcript scope defaults; the weighted aggregation
formula; the Tier-3 G-Eval shape; calibration ±1 per (anchor × criterion) with ≥85% agreement,
fail-closed; auth kinds none/bearer/header; `max_turns_per_session` + `max_usd_per_run`
(judge-spend only); the `named-sse` adapter; the TwinCore contract (consent → `session_token`,
chat with the token in the JSON body, named-sse `event: token`/`done`/`error`, port 8000,
unauthenticated, injection probes assert on the fixed first-person Guardian redirect constants);
`state.*` deferred to Plan #3; `compare` mode and CI deferred to Plan #2b.

The four user-approved pre-flight amendments are **all now implemented**:

- **P1** (Tasks 4–5) — Tier-3 judge scores per-criterion, not one overall value. Done.
- **P2** (Task 1) — `scope: any_turn` = existential pass, `all_turns` = universal, `final` =
  last turn; defaults: invariants + `not_contains` → `all_turns` (fail-closed), `contains` →
  `final`. Done.
- **P3** (Task 6) — pooled-httpx opener resolved as **per-`solve()` client**; cross-sample
  pooling rejected and re-deferred as a perf nicety with no correctness impact. Done.
- **P4** (Tasks 1/9/10) — `contains` supports `values: list[str]` (OR-semantics, mutually
  exclusive with `value`); exclusivity validated in Task 9; used by Task 10's injection probes
  for "contains one of the Guardian redirect constants". Done.

## Dispatch notes for the remaining work

### Task 11 — HUMAN-GATED (start here)

Plan steps: bring up the stack → capture ~15–20 anchor transcripts → **I hand-score them** →
run calibration → commit anchors + record.

- **Before the live run: add a concurrency cap to `run_calibration`'s `asyncio.gather`**
  (journaled minor, explicitly tagged to this checkpoint). Do this first — it is the only code
  change Task 11 needs, and it is dispatchable as a small Fable task.
- Needs from me: the TwinCore dev stack on port 8000 with a seeded, **published** twin and a
  known slug (set `EVALYN_TWIN_SLUG` to it); `ANTHROPIC_API_KEY` in the environment;
  ~30–60 min of hand-scoring.
- Anchor file shape (`packs/twincore/anchors/<id>.yaml`): `id`, `rubric`, `transcript` (a
  `User:` / `Assistant:` block), and `scores: {}` left **blank** for me to fill 1–5 per rubric
  criterion.
- Then `uv run evalyn calibrate --target packs/twincore` → per-criterion table + overall
  agreement; exit 0 iff ≥ 85%. **If it lands under 85%, that is expected calibration work, not
  a bug** — inspect the disagreements, iterate on rubric wording, re-run. Do not weaken the
  threshold.
- This is also the first time the real `model_usage → estimate_cost` metering seam runs with
  billable usage — sanity-check `judge_usd` in the artifact afterwards and report it.
- Commit anchors + `calibration.json` per the plan's step 5.

### Task 12 — CLI wiring + cleanup bundle

- Map to setup-error **exit 2** with clean messages (no tracebacks): old-baseline
  `RuntimeError`; calibrate malformed-anchor `KeyError`; missing-rubric `FileNotFoundError`.
- `--debug` re-raise flag; `--update-baseline` prints the verdict it blesses; `click>=8.2` floor.
- Loader hardening bundle: narrow `except`, `${VAR}` semantics, lowercase env names,
  `extra="forbid"` decision, static `event_format`/`stream` validation — **note
  `event_format` validation already landed in Task 6, so verify rather than duplicate**.
- Shared conftest pack-writing fixture.
- **Verify (not implement)** Task 10's `${…}`-in-`sessions.*.path` resolution.
- Session-2 additions folded into this bundle: expose CLI `--out-dir`; print
  `total_unsure_trials` in the human-readable gate report; thread `out_dir=tmp_path` through the
  older `run_gate` tests that still write CWD `runs/`.

### Task 13 — end-to-end acceptance

- Toy **named-sse** target added here.
- **BOTH design-gap proofs test-pinned e2e:** (a) a multi-turn early leak FAILS the gate;
  (b) a non-required partial score moves a band — the composed reducer→gate flow on one partial
  score, deferred from Task 3.
- e2e must cover **both** the `--allow-uncalibrated` path **and** the stale-calibration exit-2 path.
- `validate-pack packs/example` and `validate-pack packs/twincore` both exit 0.
- Journal openers section emptied (each item done or re-deferred **with a reason**).
- `docs/ROADMAP.md` records the #2a/#2b split.

### Final whole-branch review (after Task 13)

- Base = `git merge-base dev HEAD`. Build the package, dispatch on the **most capable model**.
- Point it at the journal register — ~15 open minors from sessions 1–2. Known headline items:
  `RubricScore` bare asserts → ValueError; unused `agreement()` inline-pooling drift; `_median`
  even-k truncation; `_parse` extra-criteria leniency; `any_turn` evidence comment; tier-2
  unicode-drift test discrimination; tier-2 explanation omits non-required misses; Task 6
  stream-adapter polish (vercel non-string JSON frame escapes as `TypeError`, named-sse
  `event: error` without a `data:` line, `\r`-strip asymmetry across adapters); empty-`raw_files`
  constant fingerprint; 0600 artifact/cache mode; Task 9 double-error + sentinel-style
  inconsistency; unsanitized rubric-id file stems. The compare-mode `model_usage` accumulation
  item is tagged **Plan #2b**, not #2a — do not fix it here.
- ONE fix wave (not one fixer per finding), one scoped re-review, adjudicate residuals.
- Then superpowers:finishing-a-development-branch → **push + PR to `dev` (ask first —
  session 2's commits are still unpushed)**.

## Process (locked — same machinery as sessions 1 and 2)

Use **superpowers:subagent-driven-development**. Per task:

1. Extract the brief: `scripts/task-brief PLAN_FILE N` (from the skill's directory).
2. Dispatch a **fresh Fable implementer** (explicit `model: fable`) with: the brief path,
   `.superpowers/sdd/plan2a-constraints.md`, one paragraph of scene-setting, the task's dispatch
   notes above, and the superpowers:test-driven-development mandate. **Implementers stage but
   never commit.** Give them a report-file path in the SDD workspace.
3. Build the diff package: `git diff --stat BASE` + `git diff -U10 BASE` + an end marker into
   one file, **excluding `docs/JOURNAL.md`** (that is controller bookkeeping and confuses
   reviewers — session 2 had a reviewer flag it as unexplained provenance).
4. Dispatch a **fresh Fable reviewer** (spec compliance + code quality, file:line evidence,
   do-not-trust-the-report, read-only on the checkout).
5. Fix rounds go back to the **same implementer** via SendMessage; re-review the fix diff with
   the **same reviewer**, scoped to the findings. Never fix things yourself in the controller.
6. Controller-verify `uv run pytest -q` + `uv run ruff check src/ tests/` with real output,
   update `docs/JOURNAL.md` (task row + register), commit, append to the ledger, move on.

## Working agreements (non-negotiable)

- **uv only** (`~/.local/bin/uv`); system `python3` is 3.9 — always `uv run …`.
- **Git:** commits under
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com'`,
  conventional prefixes (`feat:`/`docs:`/`test:`/`fix:`/`chore:`), **no `Co-Authored-By` /
  Claude trailer**.
- **Commit cadence:** the standing grant from sessions 1–2 is "commit automatically after each
  verified task." Confirm it still holds at session start. **Ask before every push, PR, and
  branch deletion.**
- **Verification before completion** — real output, never weakened tests. Never commit `runs/`,
  baselines, or `.superpowers/`.
- Architecture: Inspect spine, scorers as Inspect `Scorer`s, gate policy in Evalyn's
  log-reading layer, async httpx only, judge ≠ generator family (warning), allowlist fail-closed.
- Surface plan divergences to me; don't silently improvise. One task at a time; checkpoint
  between tasks.

## Start now

1. Read the source documents above + the ledger; confirm your understanding in one short paragraph.
2. Verify the branch is green — `uv run pytest -q` (expect 243), `uv run ruff check src/ tests/`,
   `uv run evalyn validate-pack packs/twincore` — and report the numbers.
3. Confirm the commit-cadence grant.
4. Dispatch the small `run_calibration` concurrency-cap fix, then **prepare Task 11 and hand me
   its live steps** — do not attempt the live calibration run yourself.

Ask me if you have questions. Use skills. Do research if wanted. Think hard and reason deeply.
