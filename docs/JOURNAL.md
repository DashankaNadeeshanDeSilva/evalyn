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

## Plan #3 — `discover` + flywheel *(not started)*
