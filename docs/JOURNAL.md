# Evalyn — Progress Journal

**What this doc is:** the durable, committed record of execution — what was built, what was
found along the way, and what we deliberately deferred. Updated at every task completion and
at plan boundaries. (The gitignored `.superpowers/sdd/progress.md` is the session-recovery
scratch ledger; **this** file is the source of truth for issues to revisit.)

**How to use it:** before starting any task or plan, scan *Open items* for anything tagged to
it. At each plan's final review, triage that plan's deferred findings: fix, re-defer with a
reason, or close.

---

## Plan #1 — Gate foundation (`feat/gate-foundation`, cut from `dev`)

Plan doc: [`superpowers/plans/2026-07-22-evalyn-gate-foundation.md`](./superpowers/plans/2026-07-22-evalyn-gate-foundation.md)
Execution: subagent-driven (fresh implementer per task → task review → fixes → user checkpoint).

### Task status

| Task | What | Commits | Status |
|------|------|---------|--------|
| 1 | Project scaffold (pyproject, package, CLI stub) | `54820fe` | ✅ done, review clean |
| 2 | Pack schema models (pydantic v2) | `85bc5e5` | ✅ done, review clean |
| 3 | Pack loader (env resolution + allowlist) | `6c0e40a`, `fcf72fd` (tests fix), `7fb6253` (dup-id fix) | ✅ done, review clean after fixes |
| 4 | Stream adapters (vercel-ai / raw-sse / json) | `37dfffb` | ✅ done, review clean |
| 5 | Session solver (live HTTP/SSE, multi-turn) + toy target promoted | `649579e` | ✅ done, Opus review clean |
| 6 | Tier-1 deterministic scorer (invariants + checks) | `c85d0f5` | ✅ done, Opus review clean |
| 7 | Tier-2 classifier judge (evidence-or-unsure) | `659164f`, `8316ad6` (safeguard fixes) | ✅ done, Opus review clean after fixes |
| 8 | Task builder (probes → Inspect Task, pass@k/pass^k reducers) | `a75f8d2` | ✅ done, Opus review clean |
| 9 | Example reference pack (balanced injection + grounding + invariants) | `54aa199` | ✅ done, Opus review clean (zero findings) |
| 10 | Run orchestration + self-contained artifact (A1/A2 applied) | `2cf4888` | ✅ done, Fable review clean |
| 11 | Gate-diff/reporter + baseline (the crux: per-probe policy) | `d09be27`, `d6220d2` (test fix) | ✅ done, Fable review clean after fix |
| 12 | validate-pack (malformed-check guards, solvability, balance lint) | `a870e21` | ✅ done, Fable review clean |
| 13 | CLI wiring (`gate` / `validate-pack`, CI exit codes 0/1/2) | `52ef5f0` | ✅ done, Fable review clean |
| 14 | End-to-end gate + full-suite green (DoD met) | `51a4eba` | ✅ done, Fable review clean |

**Plan #1 definition of done: MET (2026-07-23, controller-verified).** 69/69 tests, ruff clean,
`validate-pack` exit 0; acceptance run showed pass^k catching the flaky injection guard live
(`SAFETY injection-trust-pivot: pass^k=0.0` → exit 1) — the milestone behavior from the spike,
now shipping end-to-end. Amendments A1/A2/A3 all closed.

### Final whole-branch reviews (2026-07-23) — verdict: **merge WITH FIXES**

Two independent final reviews ran over the full branch diff (base `93483c6` = merge-base with
`dev`): a Fable senior review (with open-items triage) and `/code-review high`. No Critical
findings; architecture coherent; all global constraints verified branch-wide (no blocking HTTP,
no committed artifacts, commits clean). Full reports: `.superpowers/sdd/` task outputs.

**PRE-MERGE FIX BUNDLE: APPLIED ✅ (2026-07-23, commit `6a98f40`).** One Fable fixer subagent,
TDD per fix, one commit; Fable review verified all 10 items with file:line evidence — zero
Critical/Important findings. Controller-verified acceptance: **80/80 tests** (69 + 11 new),
`ruff check src/ tests/` both clean, `validate-pack packs/example` exit 0.

1. [x] Tests lint trio: `uv run ruff check tests --fix` (+ manual: split E401 in
       `tests/test_smoke.py`; F401 `pytest` in `tests/engine/test_solver.py`; F401 `INCORRECT`
       in `tests/scoring/test_tier2.py` — consumed by fix 2, don't delete).
2. [x] Tier-2 INCORRECT-path test: judge returns `{"verdict": false, "evidence": <real substring>}`
       vs `expect: true` → asserts `INCORRECT` (`tests/scoring/test_tier2.py`).
3. [x] `validate.py`: empty/whitespace `value` on contains/not_contains = error (harmonize with
       question's `.strip()` guard) + test.
4. [x] Mock-judge trap: README quickstart sentence (mockllm ⇒ classifier checks fail closed,
       pass real `--judge-model`) + CLI `warning:` line when judge starts with "mockllm" AND pack
       has classifier checks (verdict-neutral) + tests (warning present/absent).
5. [x] `loader.py`: `yaml.safe_load(...) or {}` so empty target.yaml → existing
       "invalid target.yaml" PackError, not AttributeError + test.
6. [x] `schema.py`: `Probe.samples` → `Field(default=1, ge=1)` + test (samples: 0 → PackError
       via loader).
7. [x] `loader.py`: glob `*.yaml` AND `*.yml` (sorted union) + test.
8. [x] `run.py`: after `inspect_eval`, non-"success" log status → raise RuntimeError naming
       status (CLI's existing except → exit 2) + engine-level test. CLI untouched by this fix.
9. [x] `solver.py` `_open`: missing `session_id` key in open response → clear RuntimeError,
       never silent `""` + test.
10. [x] `validate.py`: error if `spec.sessions` lacks `"open"` or `"message"` (solver
        hard-requires both) + test.

Review minors from the fix-bundle review (deferred, polish-level → Plan #2 openers): fix-8 test's
`match="error"` is loose (pin to `"did not succeed"`); fix-9 test's stream-path guard only covers
SSE (diagnostic-only weakness); mockllm warning also prints on `--dry-run` (deliberate,
unspecified behavior choice).

**Triage outcomes applied to the register** (verdicts from the final review):
- CLOSED with evidence: missing `probes/` dir (fails loudly both paths); schema-test gap (covered
  at loader layer); empty-reducers carry (shipped+pinned); trials-field decision (key-label per
  A1); pack-hash/baseline-only carries (shipped as CLI warnings); `test_cli_help_runs` coupling
  (works as designed); budget-unenforced finding (= approved A3 forward-compat).
- MUST-FIX: bundle items above. Everything else: DEFER → Plan #2 openers below.

### PR #1 review fixes (2026-07-23, commit `ca025e9`) — review-verdict set APPLIED ✅

The user's separate-session `/code-review high` on PR #1 returned 10 findings, verdict "merge
with fixes". User approved the **review-verdict set** scope; one Fable fixer (TDD), Fable
review Approved (0 Critical/Important). Controller-verified: **92/92 tests**, ruff clean,
validate-pack exit 0 (with intended interim warning on `injection-trust-pivot`).

1. [x] **#2+#4 (fail-closed hole):** `gate` now runs `validate_pack` before evaluating (incl.
       `--dry-run`) — errors → stderr + exit 2; warnings print (stdout, matching validate-pack)
       without aborting. This also closes the Plan #2 opener "gate auto-runs validate-pack".
2. [x] **#1 interim guard:** validate-pack warns on multi-turn `safety_critical` probes
       (final-reply-only scoring until Plan #2 transcript scoring).
3. [x] **#6 observability:** all-errored capability probe renders "no scored trials — all trials
       errored or unscored" instead of `pass^k=None`; verdict-neutral, counterfactual test
       unmodified.
4. [x] **#5 evidence robustness:** tier-2 evidence match now normalizes (casefold/punctuation/
       whitespace) with ≥0.6 token-overlap fallback; empty-evidence ⇒ NOANSWER safeguard
       byte-identical; fabrication still fails closed.
5. [x] **#3/#7/#9 docs:** budget fields, `Check.weight`/non-required semantics marked
       declarative-only (Plan #2) in schema + README; README notes pack-max epochs call-volume.

Tracked (not fixed, per approved scope): #8 fingerprint-over-env (existing Plan #2 opener),
#9 per-probe epochs (beyond docs note), #10 pooled httpx client (added to openers below).
New review minors → Plan #2 openers: token-overlap stopword/min-floor hardening + unicode-aware
punctuation strip in tier-2 `_normalize`; shared conftest fixture for pack-writing test helpers.

### Plan #1 MERGED ✅ (2026-07-23)

PR #1 merged to `dev` (merge commit `d4ce297`) after the re-review (`/code-review med`) returned
"all resolved — good to merge". Feature branch `feat/gate-foundation` deleted (local + remote).
Post-merge `dev` verified: 92/92 tests, ruff clean. Re-review's one non-blocker added to Plan #2
openers (tier1 null-`value` defense-in-depth).

### Pre-flight plan amendments (user-approved 2026-07-23)

- **A1 (Task 10):** per-probe reducer keys/values are computed from the **actual number of
  trials collected**, not the probe's declared `samples` (Task 8 runs every probe at the
  pack-wide max epoch count, so declared `samples` can disagree with reality).
- **A2 (Tasks 8/13/14 tests):** strengthen three weak plan-mandated assertions — drop the
  always-true `or "mean" in reducers` branch; e2e/CLI tests must not blindly accept
  `exit_code in (0, 1)`; compare against Inspect's `CORRECT` constant, not the magic string `"C"`.
- **A3 (Tasks 2/9):** `auth` / `budget` / `state` schema fields are **deliberate forward-compat**
  (consumers arrive in Plan #2) — kept, not defects.
- Verified empirically: `Epochs(k, [pass_at(k), pass_k(k), "mean"])` works on `inspect_ai 0.3.249`.

### Audits (user-requested Opus re-checks of the cheap-tier implementations)

- **Tasks 1–3:** SOUND. Byte-identical to briefs; allowlist is fail-closed (no bypass
  constructible: exact membership, no normalization tricks). One Important fixed on the spot
  (duplicate probe ids — see `7fb6253`); one Important closed structurally (see Task-5
  contracts below).
- **Task 4:** SOUND. The implementer's `.lstrip()` deviation was hand-traced and confirmed a
  **genuine fix for a bug in the plan's own sample code** (the brief's `.strip()` fails the
  brief's own test). vercel-ai unescaping robust (escaped quotes / newlines / unicode);
  empty SSE lines and `event:`/`id:` fields handled.

### Binding contracts for Task 5 (session solver) — from the audits

1. Resolve the target URL **only** via `resolve_base_url()`; never read `env["base_url"]` raw
   (keeps allowlist enforcement structural).
2. `parse_stream` is sync/batch: buffer the httpx stream (`[l async for l in resp.aiter_lines()]`)
   before calling it — never pass the async iterator.
3. `json` event format = **JSONL** (one object per line), per the Task 4 brief; the toy target
   emits vercel-ai frames.
4. Surface malformed/error streams as **transport failures**, not empty replies (an empty reply
   would be scored as a bad answer, masking the real cause).

### Open items — deferred findings register

Triage at the Plan #1 final whole-branch review unless tagged later.

**Loader / schema (Tasks 2–3):**
- [ ] Broad `except Exception` around `model_validate` — narrow to `pydantic.ValidationError`
      so real bugs aren't rewrapped as `PackError`. *(minor)*
- [ ] Empty `target.yaml` → `AttributeError` instead of `PackError` (contract leak). *(minor)*
- [ ] Missing `probes/` dir → silent empty probe list; undocumented. *(minor)*
- [ ] Bare `${VAR}` with unset var resolves to `""` silently (fail-closed via allowlist, but
      confusing). `${VAR:-default}` also ignores shell set-but-empty semantics. *(minor)*
- [ ] Env-var regex is uppercase-only (`[A-Z0-9_]+`) — lowercase refs silently unresolved;
      widen or document. *(minor)*
- [ ] No `extra="forbid"` on schema models — typo'd pack YAML keys pass silently. Consider at
      `validate-pack` (Task 12) or Plan #2. *(minor)*
- [ ] No cross-field validation on `Check` (`ref` for invariant, `question`/`expect` for
      classifier, …) and `ref` not checked against invariant ids — presumed deferred to
      `validate-pack` (Task 12); **Task 8's scorer must handle missing fields defensively**. *(info)*
- [ ] Schema tests are happy-path only (no `ValidationError` case). *(minor)*

**Stream adapters (Task 4):**
- [ ] Malformed frames raise raw `JSONDecodeError` (and valid-but-wrong-type frames like `0:5`
      raise `TypeError`) instead of `StreamFormatError`. *(minor)*
- [ ] raw-sse `.lstrip()` strips ALL leading whitespace — SSE spec strips exactly one space, so
      leading-space tokens lose word boundaries on the plain-text path. Revisit before any real
      product uses raw-sse plain text (Plan #2 / TwinCore pack). *(minor)*
- [ ] Interior `\r` survives on raw-sse if CRLF isn't normalized upstream. *(minor)*
- [ ] Mid-stream vercel-ai error frames (`3:`/`e:`) silently dropped. Related to Task-5
      contract #4. *(minor)*
- [ ] Final `.strip()` trims genuine leading/trailing reply whitespace — scorer-fidelity
      question. *(minor)*
- [ ] Adapter tests are happy-path only (no escaping/unicode/CRLF/malformed-frame cases). *(minor)*

**Session solver (Task 5):**
- [ ] Unused `import pytest` in `tests/engine/test_solver.py` (brief-verbatim; `ruff` scopes to
      `src/` only). *(minor)*
- [ ] `state.metadata["turns"]` raw key access — `KeyError` instead of a domain error on
      non-conforming samples. *(minor)*
- Note: solver honors audit contracts 1/2/4 (allowlist-only URL, buffer-then-parse, errors via
  `raise_for_status`); minipack allowlist gained `http://127.0.0.1:8899` (necessary + minimal,
  reviewer-verified).

**Tier-1 scorer (Task 6):**
- [x] ~~Task 12 MUST guard: malformed checks (`ref=None` no-op, `value=None` crash)~~ — **CLOSED in
      Task 12** (`a870e21`): all 4 guards (missing ref, dangling ref, missing value incl.
      not_contains, missing question) with falsifiability-verified tests.
- [ ] Tier-1 tests minimal per brief — `contains`/`not_contains` scoring and non-required check
      recording untested; expand when Task 8 wires real probes. *(minor)*
- [ ] `first-person` invariant regex narrow (only `he/she + 4 verbs` — misses `they`, other verbs). *(minor)*

**Tier-2 judge (Task 7):**
- Plan amendments (user-approved, FIXED in `8316ad6`): evidence guard no longer trusts empty
  evidence (design safeguard restored — empty/absent evidence ⇒ `NOANSWER`); `expect: None`
  (pydantic `model_dump` shape) normalized to `True` instead of silently flipping verdicts.
- [ ] No test exercises the verdict-≠-expect → `INCORRECT` path (unused `INCORRECT` import,
      F401 if `tests/` linted). *(minor)*

**Run orchestration (Task 10):**
- [ ] **Task 11 MUST handle:** empty `reducers` on a `ProbeResult` (probe absent from log — e.g.
      all trials errored before scoring) is a HARD FAILURE for gate policy, never a pass.
      *(carry to Task 11 dispatch)*
- [ ] Task 11 decision: add explicit `ProbeResult.trials` field (actual count) vs. key-label-only;
      note `from_dict` is strict — schema additions break older-artifact reads. *(carry to Task 11)*
- [ ] Artifact filename has second resolution — same-second runs overwrite (plan-mandated naming);
      add sub-second/uniquifier later. *(minor)*
- [ ] Artifact write is non-atomic and CWD-relative (`Path("runs")` hardcoded, brief-mandated);
      `out_dir` param is the follow-up. *(minor)*

**Gate-diff / baseline (Task 11):**
- [ ] **Task 13/14 SHOULD surface:** gate never compares `current.pack_hash` vs `baseline.pack_hash`
      (pack drift undetected); probes present in baseline but absent from current artifact are
      silently invisible (loop is over current only). *(carry to Task 13/14 dispatches)*
- [ ] Asymmetric mean lookup: current side prefix-matches, baseline side exact-matches `"mean"` —
      unify before any `mean_*` reducer exists. *(minor)*
- [ ] Band boundary `>` has no drop==band test; float fuzz at exact boundary. *(minor)*
- Note: 8-scenario policy trace verified; capability-never-reds (incl. empty reducers) test-pinned
  with counterfactual; implementer fixed a brief bug (empty-reducer non-safety probes silently
  passed) + 2 latent `_min_over_scorers` bugs.

**validate-pack (Task 12):**
- [ ] `value: ""` passes the contains guard while `question: ""` is caught (`.strip()`
      inconsistency between the two added guards) — one-line harmonization. *(minor)*
- [ ] `KNOWN_INVARIANTS` captured at import time — revisit if invariants become pack-extensible
      (Plan #2+). *(info)*

**CLI (Task 13):**
- Carry-notes CLOSED at CLI level: pack-hash drift + baseline-only probes surface as `warning:`
  lines (verdict-neutral, tested); gate.py untouched.
- [ ] Broad `except Exception` → exit 2 hides engine tracebacks (plan-mandated) — add a
      `--debug`/re-raise flag later for diagnosability. *(minor)*
- [ ] Allowlist exit-2 test lacks the `setup error` stderr assertion (asymmetric with run-error
      test). *(minor)*
- [ ] stderr assertions require `click>=8.2` (installed: 8.2.1) — consider a pyproject floor to
      guard against downgrade. *(minor)*

**E2E (Task 14):**
- [ ] `EVALYN_BIN` assumes console script beside `sys.executable` — confusing failure outside the
      project venv; add `shutil.which` fallback or clear assert. *(minor)*
- [ ] Fixed port 8899 in the shared fixture — stale toy-target process fails suite setup loudly.
      *(minor, pre-existing)*

**Misc:**
- [ ] `tests/test_smoke.py:1` combined import (`E401`) — only matters if `tests/` enters lint
      scope. *(minor)*
- [ ] `test_cli_help_runs` requires the package installed in the venv (couples to the `uv sync`
      workflow). *(info)*

### Decisions log

- 2026-07-23 — Branch `feat/gate-foundation` (in-place, no worktree). Merge target: `dev` via PR.
- 2026-07-23 — Subagent model policy (user, escalated in three steps during Tasks 4–5): **Opus
  for all subagents** from Task 6 onward — implementers, fixers, task reviewers, final review.
  (Task 5 itself: Sonnet implementer + Opus reviewer.)
- 2026-07-23 — This journal created; updated at every task completion.

---

## Plan #2 — Real product wiring + Tier-3 + `compare` *(not started)*

### ⚠️ Design gaps deferred from Plan #1 — MUST be addressed in Plan #2 (user decision 2026-07-23)

1. **Scorers only see the FINAL assistant reply** (`state.output.completion`): a leak in an
   earlier turn of a multi-turn probe followed by a benign closing turn passes the safety gate.
   The solver records all turns in `state.messages`; no scorer reads them. Fix = transcript
   scoring (walk all assistant turns) — belongs with Tier-3/real-product scoring work. The
   shipped example pack scores correctly today only because its attack lands on the final turn.
2. **Weighted / non-required check semantics are unimplemented**: `schema.Check.weight` and the
   "non-required contributes weighted score" promise (schema.py) affect nothing — tier1 records
   non-required checks in metadata only; tier2 fails on any classifier mismatch regardless of
   `required`. Consequence: the example grounding probe can never trigger the regression band.

### Other Plan #2 openers (from the final branch reviews)

- ~~`gate` auto-runs validate-pack before evaluating~~ — **DONE in `ca025e9`** (PR #1 review fixes).
- Pooled httpx client for the solver (fresh `AsyncClient` per `solve()` today — no connection
  reuse across samples/epochs; PR #1 review #10).
- Tier-2 evidence-match hardening: stopword filter / min-token floor on the 0.6 token-overlap
  fallback; unicode-aware punctuation strip in `_normalize` (PR #1 review minors).
- Shared conftest fixture for pack-writing test helpers (`tests/test_cli.py` vs
  `tests/engine/test_validate.py` near-duplication).
- Tier-1 null-`value` defense-in-depth: the `chk["value"]` access in tier1 is unreachable via
  `gate` (validate-pack runs first) but unguarded on any other entry path — one-line guard
  (PR #1 re-review non-blocker).
- Artifact records NOANSWER counts distinctly, so judge-infra failure ≠ product failure.
- `pack_fingerprint` over raw pack bytes (today it hashes resolved env — localhost vs 127.0.0.1
  flips the hash → spurious staleness warnings).
- `out_dir` param for artifacts (atomic write; fixes CWD-relative `runs/` + test pollution).
- Adapter-hardening bundle: malformed frames → `StreamFormatError`; vercel error frames (`3:`/`e:`)
  surfaced; raw-sse single-space (not lstrip) fidelity; interior `\r`; whitespace-fidelity
  decision; adapter edge-case tests.
- Loader hardening: narrow `except Exception`; `${VAR}` set-but-empty semantics; lowercase env
  names; `extra="forbid"` decision; validate `event_format`/`stream` values statically.
- validate-pack warns on `kind: capability` + `safety_critical: true` (contradictory combo).
- CLI `--debug` (re-raise instead of swallowed traceback); `--update-baseline` prints the verdict
  it is blessing; `click>=8.2` floor.
- pyproject metadata (license/readme/authors/urls) before any PyPI publish.
- Carry-ins already tagged: TwinCore raw-sse fidelity; budget/auth/state consumers (A3).

---

## Plan #2a — Trusted gate on the real product (`feat/plan2a-real-gate`, cut from `dev` @ `e30afbf`)

Plan doc: [`superpowers/plans/2026-07-24-evalyn-plan2a-real-gate.md`](./superpowers/plans/2026-07-24-evalyn-plan2a-real-gate.md)
Spec: [`superpowers/specs/2026-07-24-evalyn-plan2a-design.md`](./superpowers/specs/2026-07-24-evalyn-plan2a-design.md)
Execution: subagent-driven (Fable implementer + Fable reviewer per task); commits automatic
per verified task (user, 2026-07-24); push/PR ask-first.

### Pre-flight plan amendments (user-approved 2026-07-24)

- **P1 (Tasks 4+5):** Tier-3 judge emits **per-criterion** 1–5 scores per rubric (plan's
  single-overall-score prompt corrected); check score = mean of normalized criteria;
  calibration agreement per (anchor × criterion) as specced.
- **P2 (Task 1):** `scope` semantics per spec — `any_turn` = existential pass, `all_turns` =
  universal, `final` = last turn; defaults: invariants/`not_contains` → `all_turns`
  (fail-closed), `contains` → `final`. (Plan's helper + docstring had `any_turn` ≡ `all_turns`.)
- **P3 (Task 6):** pooled-httpx opener resolved as per-`solve()` client — re-deferred
  (perf nicety, no correctness impact; Inspect sample-parallelism makes run-scoped sharing
  invasive).
- **P4 (Tasks 1/9/10):** `contains` checks gain `values: list[str]` (OR-semantics, mutually
  exclusive with `value`; exclusivity validated in Task 9) so injection probes can assert
  "contains one of the Guardian redirect constants" as locked.

### Task status

| Task | What | Commits | Status |
|------|------|---------|--------|
| 1 | Transcript access + scope-aware Tier-1 + `CheckResult` (P2+P4 applied) | `6de3766` | ✅ done, Fable review clean (0 findings above Minor) |
| 2 | Tier-2 full-transcript judge + CheckResults + per-check NOANSWER (+ evidence-vs-assistant-turns-only, `_normalize` hardening riders) | `65a36a5` | ✅ done, Fable review clean after 1 fix round (floor-branch test) |
| 3 | `aggregate_trial` (locked weighted formula) + metadata-driven reducer + `ProbeResult` reshape + gate bands on mean trial score — **design-gap #2 closed at engine level** | `a310844` | ✅ done, Fable review clean after 1 fix round (contract-literal `required_pass`, den==0 pin, corrupt-JSON diagnosis) |
| 4 | Tier-3 G-Eval rubric scorer (P1 per-criterion 1–5, k=3 medians, spread≥2 ⇒ unsure, cached steps, hash recorded, family-match warning) | `53c58ee` | ✅ done, Fable review clean (0 findings above Minor) |
| 5 | Calibration harness + `evalyn calibrate` + fail-closed gate (±1 per anchor×criterion, ≥85%, locked staleness incl. sub-threshold-record rejection, `--allow-uncalibrated` loud + untrusted-marked, steps-cache atomic write + pre-warm) | `7d35fe7` | ✅ done, Fable review clean after 1 fix round (unmatched-label reporting + exact-0.85 boundary pins) |
| 6 | Solver + adapters: generic `named-sse` (configurable event/field), flexible session flow (`open_body`/`session_id_field`/`message_field`/`session_field`), auth headers (none/bearer/header), `max_turns_per_session` loud transport error, stream hardening (`StreamFormatError` on malformed frames, vercel `3:`/`e:` surfaced, raw-sse one-space fidelity, named-sse `\r` strip) — P3 per-`solve()` client applied | `42e4e57` | ✅ done, Fable review clean (0 findings above Minor) |
| 7 | Budget: `engine/budget.py` (prices, `estimate_cost`, `BudgetExceeded`), post-hoc judge-spend metering via Inspect `model_usage`, `RunArtifact.judge_usd`, artifact written before raise, CLI budget exit 2; fix round added fail-open guards (import canary tests + `RuntimeWarning` "budget cap not enforced" in the except branch) | `d274e8a` | ✅ done, Fable review clean after 1 fix round (fail-open `_judge_usd` guarded) |
| 8 | Artifact hardening: fingerprint over raw pack bytes (`Pack.raw_files`, env-independent — localhost vs 127.0.0.1 same hash), `out_dir` param, atomic `mkstemp`+`os.replace` artifact write, `RunArtifact.total_unsure_trials` surfaced; Task-7 write-before-raise ordering preserved | `bab3c14` | ✅ done, Fable review clean (0 findings above Minor) |
| 9 | validate-pack extensions: P4 `value` XOR `values` exclusivity (incl. dedicated `not_contains`+`values` typo error), static rubric-ref validation (missing id / nonexistent `rubrics/<id>.md`, message + README teach `##`-heading criteria), `contains:a\|b` label parity verified against tier1 scorer, capability+safety_critical contradiction warning, interim multi-turn warning retired (substring RED-verified against real output first) | `5659b40` | ✅ done, Fable review clean (0 findings above Minor) |
| 10 | TwinCore reference pack: `packs/twincore/` (consent+chat named-sse target, 31-case injection port with literal base64, grounding/persona/scope/pii probes, 4 rubrics, README), loader `${…}` resolution in `sessions.*.path`, allowlist localhost+127.0.0.1:8000; contract re-verified against `niuwnai-mvp@dev` `9f30e8a` | `c2f1dde` | ✅ done, Fable review clean (0 findings above Minor; 6 disclosed deviations all verified acceptable) |
| 11 | **Human-gated calibration checkpoint:** `run_calibration` concurrency cap (semaphore, default 4) pre-flight; 20 anchors captured live (slug `evalyn`, 12 from a contained capture incident + 8 supervised) and human-scored; judge `claude-3-5-sonnet-latest` found RETIRED (404) → user-approved successor `anthropic/claude-sonnet-5`; 5 calibration runs with 4 rubric-wording iterations (60%→75%→78%→82.5%→**88% PASS**, threshold 85%) + user re-assessed 2 groundedness labels; `calibration.json` committed | `6107596` + `ab53694` | ✅ done — judge calibrated at 88% (35/40 within ±1) |
| 12 | CLI wiring + cleanup bundle: `--debug` re-raise on all exit-2 paths, exit-2 mappings (old-schema baseline `RuntimeError`, malformed-anchor `KeyError`→`PackError` at source, missing-rubric `FileNotFoundError`), `--update-baseline` echoes verdict, `--out-dir` threads `run_gate(out_dir=…)`, `total_unsure_trials` printed when nonzero; loader hardening (`ValidationError`-narrowed, `${VAR:-}` set-but-empty semantics, lowercase env names, `extra="forbid"` + typo'd-key tests, `load_anchors` unbroken); PRICES `claude-sonnet-5` entry (retired key kept); `anthropic>=0.120` + `click>=8.2` in pyproject (survives `uv sync`); shared `minimal_pack`/`minimal_pack_with_probe` conftest fixtures; older tests threaded `out_dir=tmp_path` | this commit | ✅ done, Fable review clean (0 findings above Minor; verify-only items confirmed: Task 6 `event_format` validator, Task 10 `${…}` session-path test pins) |

**Session handoff (2026-07-25):** Tasks 1–5 built in session 1 (this record); Tasks 6–13 continue
in a fresh session — kickoff prompt in
[`2026-07-25-handoff-plan2a-task6.md`](./2026-07-25-handoff-plan2a-task6.md).

### Deferred findings register (Plan #2a)

- [ ] `schema.py` `weight` docstring still says "not yet used in scoring" — stale once Task 1
      propagates weight into CheckResults; rewrite in Task 3. *(minor, tagged Task 3)*
- [ ] `_eval_over_turns` with empty `turns` vacuously passes `all_turns`/`final` — unreachable
      today (tier1 falls back to `[completion]`), but callers added in Tasks 2/4 must keep the
      non-empty guarantee. *(minor, tagged Tasks 2/4 dispatches)*
- [x] ~~`not_contains` + `values` typo silently ignored until Task 9's exclusivity validation~~ —
      **CLOSED in Task 9** (dedicated error + dedicated test, reviewer-verified).
- [ ] `any_turn` failure evidence picks the last turn's string (arbitrary but harmless) — add
      a comment. *(minor)*
- [x] ~~Multi-value check label convention `contains:a|b` — confirm validate-pack reporting
      uses the same convention~~ — **CLOSED in Task 9** (label + case-insensitivity parity
      reviewer-verified against tier1.py).
- [ ] Tier-2 unicode-drift test passes under old code too (0.6-overlap fallback at exactly 3/5)
      — regression pin only; a discriminating case would pin the unicode strip itself. *(minor)*
- [ ] Tier-2 `explanation` string omits non-required misses ("all classifier checks passed"
      while metadata records a miss) — plan-mandated reference code, cosmetic; metadata is
      authoritative. *(minor)*
- [x] ~~INTERIM: `run.py` gates per-epoch on `Score.value == CORRECT`~~ — **CLOSED in Task 3**
      (reviewer-verified: `CORRECT` import removed, reducer reads only metadata CheckResults,
      tests prove `Score.value` is ignored).
- [x] ~~Old-baseline RuntimeError surfaces via typer traceback~~ — **CLOSED in Task 12**
      (exit-2 mapping + `--debug` re-raise, test-pinned).
- [ ] Design-gap #2 pin is two engine tests in composition (reducer partial score; gate band
      flip) — the single composed e2e flow lands in Task 13. *(tagged Task 13)*
- [ ] `schema.py` `weight` docstring — **CLOSED in Task 3** (rewritten with real semantics,
      required docstring too). Left here for the record; strike at final review.
- [x] ~~`rubric: None` fails loud only at scoring time — static rubric-ref validation +
      `##`-headings docs~~ — **CLOSED in Task 9** (validate-pack errors + README note).
- [x] ~~`grading_steps` cache write non-atomic~~ — **CLOSED in Task 5** (atomic
      `mkstemp`+`os.replace` write + calibrate pre-warms once per rubric; both test-pinned).
- [ ] `RubricScore.score/.passed` guard with bare `assert` (vanishes under `-O`) — raise
      ValueError instead. *(minor, final review)*
- [ ] `_median` int-truncates .5 at even k (irrelevant at k=3); `_parse` tolerates extra
      unlisted criteria (undocumented leniency). *(minor)*
- [x] ~~Calibrate CLI: malformed anchor raw KeyError; missing rubric FileNotFoundError
      traceback~~ — **CLOSED in Task 12** (KeyError wrapped as `PackError` in `load_anchors`
      itself so library callers benefit too; both mapped to exit 2, tested at unit + CLI level).
- [x] `run_calibration` `asyncio.gather` has no concurrency cap — **CLOSED in Task 11 pre-flight**
      (keyword-only `max_concurrency: int = 4`, semaphore around the awaited judge call,
      `< 1` → ValueError before any work; reviewer-verified discriminating tests).
- [ ] Task 11 pre-flight test polish (review minors): cap assertions use `<= cap` where the
      deterministic rendezvous saturates exactly (`== cap` would also catch over-serialization);
      ValueError-before-any-work is enforced by code placement but not test-pinned (stubs never
      asserted untouched). *(minor, final review)*
- [ ] `agreement()` public function unused by `run_calibration` (inline pooling; only
      `_within_one` shared) — dead-path drift risk. *(minor, final review)*
- [ ] Task 6 stream-adapter polish (all brief-verbatim code): vercel-ai valid-JSON
      non-string frame (`0:123`) escapes as `TypeError` at join instead of
      `StreamFormatError`; named-sse `event: error` with no `data:` line silently ignored;
      `\r`-strip exists only in named-sse branch (raw-sse/vercel/json leave trailing `\r`
      on CRLF streams); raw-sse joins multi-line `data:` without `\n` (pre-existing).
      *(minor, later hardening pass / final review)*
- [ ] Task 6 test style: `_custom_flow_seen` module-level mutable global in
      `test_solver.py`; dead `or {}` on `open_body`. *(minor)*
- [ ] Inspect's no-arg `init_model_usage()` does not clear a non-empty usage dict — a second
      `inspect_eval` in one process inherits run 1's accumulated spend, so `judge_usd` would
      double-count. Irrelevant for CLI `gate` (one run/process); MUST be handled for `compare`.
      *(minor here, tagged Plan #2b compare)*
- [ ] Budget test polish: over-cap test couples to the example pack's implicit default cap
      (5.0); no-fallback canary assumes empty `model_usage()` context (ordering-sensitive) and
      `caught == []` trips on any unrelated warning; CLI budget test mildly circular (fake
      raises the message it asserts). *(minor)*
- [ ] `_judge_usd` fail-open posture retained by design (brief-verbatim `except → 0.0`), now
      guarded by import-canary tests + loud `RuntimeWarning`; real `model_usage → estimate_cost`
      seam still never exercised with real billable usage (mockllm reports none). *(minor,
      final review / Task 11 live run will exercise it)*
- [ ] Hand-built `Pack` with empty `raw_files` hashes to one constant fingerprint (two
      different in-memory packs false-match) — only reachable outside `load_pack`; a
      warn/raise on empty `raw_files` would be fail-closed. *(minor, final review)*
- [x] ~~Older `run_gate` tests write CWD `runs/`~~ — **CLOSED in Task 12** (`out_dir=tmp_path`
      threaded through test_budget.py, test_e2e_gate.py, test_run.py).
- [ ] Atomic-write house pattern leaves artifacts/caches mode 0600 (mkstemp default, not
      umask) — style observation, applies to rubrics.py cache too. *(minor)*
- [x] ~~Task 8 flagged: CLI `--out-dir` not exposed; gate report doesn't print
      `total_unsure_trials`~~ — **CLOSED in Task 12** (both landed, test-pinned incl.
      omitted-at-zero behavior).
- [x] **USER DECISION RESOLVED (2026-07-25, session 3):** TwinCore not-in-KB honesty
      classifiers **stay non-required** — score-weighted, band-moving, but a single flaky
      Tier-2 judge call cannot hard-fail the gate. Revisit after the first live runs show
      judge reliability.
- [ ] **Groundedness judge lacks the ground (user design note, Task 11):** the transcript-only
      Tier-3 judge cannot verify claims against the seeded KB — calibration passed via rubric
      wording ("precise, mutually consistent numbers = band 4"), but the structural fix is to
      inject a condensed KB fact sheet into the groundedness judge's context (hash it with the
      rubric so staleness catches edits). *(enhancement, defer: Plan #2b / final-review triage)*
- [x] ~~PRICES lacks explicit `claude-sonnet-5` entry~~ — **CLOSED in Task 12**
      (`"claude-sonnet-5": (0.003, 0.015)` added, retired key kept; test asserts on PRICES
      directly since `_DEFAULT` equals the same tuple).
- [x] ~~`anthropic` package venv-only, dropped by `uv sync`~~ — **CLOSED in Task 12**
      (`anthropic>=0.120` as a plain dependency; controller-verified surviving `uv sync`).
- [ ] Calibration observed k=3 judge sampling noise of ±1 agreement band on untouched rubrics
      (completeness 100→80→100 across runs) — passed at 88% with margin, but consider k or
      per-criterion sample count if future packs land near the threshold. *(minor, final review)*
- [ ] Guardian `BOUNDARY` classification is a live-run flakiness source: if Guardian classifies
      an attack as BOUNDARY and the twin owner authored custom redirect text, the reply matches
      none of the three redirect constants and the required `contains` fails on a *safe* block.
      Fail-loud by design and README-documented; expect it as a possible Task 11 surprise.
- [ ] Guardian redirect constants live in 3 places in the pack (`&attack_checks` anchor, the
      duplicated inline list in `injection-exfil-boundaries`, README quotes) — a constant change
      is a 3-site edit, not 1. *(minor)*
- [ ] `tests/packs/test_twincore_validate.py` assumes repo-root cwd (`PACK = "packs/twincore"`)
      — anchor via `Path(__file__).parents[2]`. *(minor; was tagged Task 12 but not in its
      dispatched scope — re-deferred to final review)*
- [ ] `pii-direct-ask-contact` is the only pack probe with neither a rubric check nor a
      `first-person` invariant, unlike its siblings — confirm deliberate. *(minor)*
- [ ] Task 9 polish: `not_contains`+`values`-without-`value` emits two errors for one
      mistake; `values` sentinel checks mix `is not None` vs truthy between sections;
      README "Also… Also" phrasing; rubric ids used as file stems unsanitized (path-ish
      ids like `../x` resolve outside `rubrics/` — pre-existing). *(minor)*
- [ ] Task 12 review minors: `load_anchors` malformed-anchor error message says anchors need
      `scores` but a missing `scores` never raises (handled downstream as skipped) — message
      overstates; and a non-dict `scores` (e.g. `scores: "high"`) still escapes as a raw
      `ValueError`/`TypeError` traceback (only `KeyError` is wrapped). *(minor, final review)*
- [ ] Task 12 test polish: cramped one-line formatting at migrated `minimal_pack` call sites
      (test_validate.py); `minimal_pack` factory hardcodes `tmp_path / "pack"` + `mkdir()` so a
      second call in one test would fail — fine today, decide `exist_ok`/comment if reuse grows.
      *(minor)*
- [ ] `stream:` field has NO static validator (only `event_format` does) — a typo like
      `stream: ssse` silently degrades to non-streaming. Pre-existing omission discovered during
      Task 12's verify step, correctly not patched there (verify-only note). *(minor, final
      review triage — candidate quick fix or Plan #2b)*
- [ ] `anthropic>=0.120` floor is tight for PyPI consumers (pinned to the venv-validated
      version) — loosen before a public PyPI cut. *(minor, pre-release checklist)*

## Plan #3 — `discover` + flywheel *(not started)*
