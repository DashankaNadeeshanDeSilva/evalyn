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
| 7–14 | Tier-2 judge → task builder → run/gate → validate-pack → CLI → e2e | — | ⏳ pending |

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
- [ ] **Task 12 MUST guard:** `{type: invariant}` with `ref=None` silently no-ops; `{type: contains}`
      with `value=None` crashes with `AttributeError` — both reachable via schema-valid malformed
      packs; `validate-pack` is the designated guard. *(carry to Task 12 dispatch)*
- [ ] Tier-1 tests minimal per brief — `contains`/`not_contains` scoring and non-required check
      recording untested; expand when Task 8 wires real probes. *(minor)*
- [ ] `first-person` invariant regex narrow (only `he/she + 4 verbs` — misses `they`, other verbs). *(minor)*

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

Carry-ins from Plan #1 so far: raw-sse single-space fidelity (TwinCore pack may stream SSE);
`extra="forbid"` decision; budget/auth/state consumers for the forward-compat schema fields.

## Plan #3 — `discover` + flywheel *(not started)*
