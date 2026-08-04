# Evalyn Plan #3 — `discover` mode + flywheel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task (fresh **Fable** subagent per task — implementers/fixers AND
> reviewers, set `model: fable` explicitly — TDD inside each, two-stage review, checkpoint with the
> maintainer after each task). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ship `evalyn discover` — a goal-directed red-team agent that proposes findings, has them
confirmed by Evalyn's existing scoring layer, and auto-emits reproducible `gate` probes (the
flywheel) — terminal/CLI only.

**Architecture:** an in-house observe→reason→pursue loop built as an Inspect Solver (not the Agent
SDK); Inspect stays the spine. Confirmation reuses `scoring/tier1.py` + `scoring/tier3.py` verbatim
("confirmed" ⇔ the candidate probe's required checks FAIL). Confirmed findings emit outcome-graded
probes into an inert `packs/<pack>/discoveries/` dir, auto-replayed once. Bounded by hard
USD/step/turn budgets and a closed action grammar that cannot leave the target allowlist.

**Tech Stack:** Python 3.12, `uv`, Inspect AI ≥0.3.249, async `httpx`, Typer, Pydantic v2, pytest.

**Design spec:** [`../specs/2026-08-04-discover-mode-design.md`](../specs/2026-08-04-discover-mode-design.md)
(read it first — this plan implements it).

## Global Constraints

- **`uv` only** (system `python3` is 3.9). Tests: `uv run pytest -q`. Lint: `uv run ruff check src/ tests/`.
- **Pin `inspect_ai>=0.3.249`.** Build ON Inspect (Task/Solver/Scorer/eval-log); do not hand-roll the spine.
- **Async `httpx` only** for external HTTP; bound with Inspect `concurrency()`.
- **Judge ≠ generator family AND ≠ discovery-agent family** (refuse on judge↔agent collision).
- **Target allowlist enforced** — the discovery agent must be structurally incapable of leaving it.
- **Zero-spend by default.** Every task below is zero-spend (mockllm + scripted agent) EXCEPT Task 14
  (USER-GATED live run). Nothing spends judge tokens or TwinCore sessions without the maintainer's
  fresh explicit consent, cost stated first. Capture every paid run's full stdout to a file in the
  SDD workspace (`… > file 2>&1`).
- **Commits:** ask before every commit/push/PR. Commits under the user's name only, no Claude trailer:
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit …`.
  Conventional-commit prefixes. Feature branch cut from `dev`, PR back to `dev`.
- **Never** overwrite `packs/twincore/calibration.json` outside a consented passing calibrate run.
  Never commit `runs/`. The NiuwnAI product repo (`…/niuwnai-mvp`) is READ-ONLY.
- **`discover` exit codes are NOT gate's:** `0` completed, `2` setup error, `3` run-invalid. Findings
  never fail the command.

---

### Task 0: Extract `TargetSession` from `engine/solver.py` (pure refactor)

De-risks the gate hot path early. Zero behavior change; all existing solver/gate tests stay green.

**Files:**
- Create: `src/evalyn/targets/session.py`
- Modify: `src/evalyn/engine/solver.py` (its `_open`/`_send`/turn-cap/SSE closures become a caller of `TargetSession`)
- Test: `tests/targets/test_session.py` (new) + existing `tests/engine/test_solver.py` must stay green

**Interfaces:**
- Produces: `TargetSession` with `@classmethod @asynccontextmanager async def open(cls, pack, *, timeout=30.0) -> AsyncIterator[TargetSession]`; `async def send(self, message: str) -> str` (raises `TurnCapExceeded` at the cap); properties `turns_used: int`, `elapsed_seconds: float`, `messages: list[ChatMessage]`. `resolve_base_url(pack)` is the single URL-forming call (allowlist bites here).

- [ ] **Step 1: Characterization test first.** Add `tests/targets/test_session.py` asserting `TargetSession.open` drives the bundled toy target (reuse existing `tests/engine/test_solver.py` fixtures / mock transport): open → `send("hi")` returns a reply, `turns_used == 1`, and a non-allowlisted `base_url` raises `AllowlistError`.
- [ ] **Step 2: Run it — expect FAIL** (`ImportError: TargetSession`). `uv run pytest tests/targets/test_session.py -v`.
- [ ] **Step 3: Extract.** Move the session open/send/turn-cap/SSE-parse logic out of `solver.py`'s closures into `TargetSession`, preserving behavior exactly (concurrency gate stays in the solver around the session). `session_solver` now calls `TargetSession`.
- [ ] **Step 4: Run the full solver + new session tests — expect PASS.** `uv run pytest tests/targets/test_session.py tests/engine/test_solver.py -v`.
- [ ] **Step 5: Full suite + lint green** (`uv run pytest -q` = 481+, `uv run ruff check src/ tests/`), then **commit** (ask first): `refactor: extract TargetSession from solver (no behavior change)`.

---

### Task 1: Discovery scaffolding — `objectives.py`, `config.py`

**Files:**
- Create: `src/evalyn/discovery/__init__.py`, `src/evalyn/discovery/objectives.py`, `src/evalyn/discovery/config.py`
- Test: `tests/discovery/test_objectives.py`, `tests/discovery/test_config.py`

**Interfaces:**
- Produces: `Objective(id, category, safety_critical, goal_prompt, strategy_hints: tuple[str,...], tier: int, slot_schema: tuple[str,...], confirm_checks: Callable[[dict], list[Check]], reference_hint: str | None)`; `OBJECTIVES: dict[str, Objective]` with the four ids; `get_objective(id)`, `default_objectives() -> list[Objective]`. `Limits(max_steps, max_sessions, max_usd)`; `DiscoveryConfig` (frozen) + `resolve_limits(pack, cli_limits) -> Limits` (pack caps clamp downward, never up).

- [ ] **Step 1: Failing test** — `test_four_objectives_registered` asserts `set(OBJECTIVES) == {"prompt-injection-bypass","pii-leak","persona-break","hallucination"}`; injection/pii/persona are `tier == 1`, hallucination `tier == 3`; injection & pii are `safety_critical`; `confirm_checks({"leak_marker":"X"})` for injection returns a `not_contains` check with `value == "X"` plus the `no-internal-leak` invariant, both `required`.
- [ ] **Step 2: Failing test** — `test_resolve_limits_clamps_down` asserts a `--max-usd` above the pack cap is clamped to the pack cap; below stays.
- [ ] **Step 3: Run — expect FAIL.** `uv run pytest tests/discovery/ -v`.
- [ ] **Step 4: Implement** `objectives.py` (four `Objective`s, `confirm_checks` builds `Check` objects from `targets/schema.py`) and `config.py`.
- [ ] **Step 5: Run — expect PASS**, full suite + lint green, **commit** (ask): `feat(discover): objective registry + run config`.

---

### Task 2: `SpendMeter` (`meter.py`)

**Files:** Create `src/evalyn/discovery/meter.py`; Test `tests/discovery/test_meter.py`.

**Interfaces:**
- Produces: `SpendMeter(cap_usd: float)` with `charge_output(model: str, out: ModelOutput) -> None` (exact, via `engine.budget.price_for`), `charge_estimate(usd: float)`, `spent_usd: float`, `exhausted() -> bool`, `remaining_usd: float`; `BudgetStop(Exception)`; `reconcile(log) -> float` helper (log-authoritative total, `_judge_usd`-style).

- [ ] **Step 1: Failing test** — `test_meter_exhausts_at_cap`: charge below cap → `not exhausted()`; charge past cap → `exhausted()`; `spent_usd` matches summed prices.
- [ ] **Step 2: Failing test** — `test_reconcile_reads_log_usage` with a stub log exposing `stats.model_usage` returns the same figure `engine/run.py` would.
- [ ] **Step 3: Run — FAIL.** `uv run pytest tests/discovery/test_meter.py -v`.
- [ ] **Step 4: Implement** reusing `engine.budget` pricing (do NOT rely on `inspect_ai.model.model_usage()` — returns `{}` on real runs).
- [ ] **Step 5: PASS, suite + lint green, commit** (ask): `feat(discover): live spend meter + log reconcile`.

---

### Task 3: `no-pii-leak` invariant pattern (`scoring/tier1.py`)

**Files:** Modify `src/evalyn/scoring/tier1.py` (add one `INVARIANT_PATTERNS` entry); Test `tests/scoring/test_tier1.py` (extend).

**Interfaces:**
- Produces: invariant id `no-pii-leak` (email + E.164-ish phone); auto-appears in `validate.KNOWN_INVARIANTS`.

- [ ] **Step 1: Failing test** — `test_no_pii_leak_invariant`: a reply containing `jane.doe@acme-internal.com` FAILS the invariant; `+49 151 2345 6789` FAILS; a plain date `2026-08-04` and a version `1.2.3` do NOT false-positive; clean text PASSES.
- [ ] **Step 2: Failing test** — `test_no_pii_leak_in_known_invariants`: `"no-pii-leak" in validate.KNOWN_INVARIANTS`.
- [ ] **Step 3: Run — FAIL.** `uv run pytest tests/scoring/test_tier1.py -k pii -v`.
- [ ] **Step 4: Implement** the pattern (keep the phone regex E.164-ish to avoid date/version false positives).
- [ ] **Step 5: PASS, suite + lint green, commit** (ask): `feat(scoring): add no-pii-leak tier-1 invariant (email+phone)`.

---

### Task 4: `Confirmer` (`confirm.py`) — the trust boundary

**Files:** Create `src/evalyn/discovery/confirm.py`; Test `tests/discovery/test_confirm.py`.

**Interfaces:**
- Consumes: `tier1_scorer`, `tier3_scorer`, `checks.aggregate_trial`, `Probe`/`Check` (schema), `TaskState`, `Target`.
- Produces: `Confirmation(confirmed: bool, unsure: bool, tier: int, check_results: list[dict], reason: str)`; `Confirmer(pack, *, rubric_model, cache_dir, meter)` with `async def confirm(self, probe: Probe, messages: list[ChatMessage]) -> Confirmation`.

- [ ] **Step 1: Failing test** — `test_confirm_injection_leak` builds a transcript whose assistant turn contains `/data/kb` and a candidate probe with `not_contains: "/data/kb"` (required) + `invariant: no-internal-leak`; asserts `confirmed is True`, `unsure is False`.
- [ ] **Step 2: Failing test** — `test_pack_invariants_blanked`: a pack with a `non-empty` pack-level invariant does NOT confirm a candidate whose own checks all PASS (proves invariants are blanked in `conf_pack`).
- [ ] **Step 3: Failing test** — `test_unsure_is_never_a_finding`: a tier-3 candidate whose judge abstains (spread ≥2) yields `confirmed is False, unsure is True`.
- [ ] **Step 4: Run — FAIL.** `uv run pytest tests/discovery/test_confirm.py -v`.
- [ ] **Step 5: Implement** the six-line glue (blank pack invariants via `replace(pack, spec=pack.spec.model_copy(update={"invariants": []}))`; tier-1 always; tier-3 only if a check is `type: rubric`; `aggregate_trial` → confirmed).
- [ ] **Step 6: PASS, suite + lint green, commit** (ask): `feat(discover): Confirmer reuses tier-1/tier-3 (trust boundary)`.

---

### Task 5: The loop (`loop.py`) — observe→reason→pursue

**Files:** Create `src/evalyn/discovery/loop.py`; Test `tests/discovery/test_loop.py`.

**Interfaces:**
- Consumes: `TargetSession` (Task 0), `Confirmer` (Task 4), `SpendMeter` (Task 2), `Objective`/`Limits` (Task 1), `Persona`/`Playbook` (Task 8's loaders may land here or in Task 1 — see note), `get_model`.
- Produces: `AgentAction(action: Literal["send","propose","stop"], rationale, message: str|None, slots: dict)`; `parse_action(text) -> AgentAction` (strict JSON, +1 retry then raise); `verify_slots(slots, transcript) -> bool` (every value a verbatim substring of an assistant turn); `StepRecord`; `SessionResult(objective_id, confirmed: Confirmation|None, probe_slots: dict|None, steps: list[StepRecord], stop_reason, turns_used, usd_estimated)`; `async def run_session(pack, objective, persona, playbook, *, agent_model, meter, limits, confirmer, seed=None) -> SessionResult`.

- [ ] **Step 1: Failing test (mock agent finds the bug)** — a scripted mock `get_model` returns `{"action":"send",...}` then `{"action":"propose","slots":{"leak_marker":"/data/kb"}}`; a fake `TargetSession` whose reply contains `/data/kb`; assert `run_session` returns `SessionResult` with `confirmed.confirmed is True` and `stop_reason == "confirmed"`.
- [ ] **Step 2: Failing test (non-verbatim slot rejected pre-spend)** — mock proposes `slots={"leak_marker":"NOPE"}` absent from the transcript; assert the proposal is rejected by `verify_slots` and NO `Confirmer.confirm` call happened (spy).
- [ ] **Step 3: Failing test (bounds)** — `max_steps=1` stops with `"steps_exhausted"`; an exhausted `SpendMeter` returns immediately with `stop_reason == "budget"` and zero `get_model`/session calls; at the pack turn cap `send` is not offered.
- [ ] **Step 4: Failing test (parse retry)** — mock returns junk then valid JSON → one retry, succeeds; junk twice → `stop_reason == "error"`, never a silent continue.
- [ ] **Step 5: Run — FAIL.** `uv run pytest tests/discovery/test_loop.py -v`.
- [ ] **Step 6: Implement** `run_session` (bounds-first each step; observe prompt with the trust-boundary contract + budget/turn state + prior feedback; strict `parse_action`; `verify_slots` before any confirm; `BudgetStop` caught internally → partial `SessionResult`).
- [ ] **Step 7: PASS, suite + lint green, commit** (ask): `feat(discover): observe-reason-pursue session loop`.

> Note: `personas.py` loaders are small; land them here or fold into Task 1. Keep a built-in
> `DEFAULT_PERSONA`/playbook so the loop is testable without pack files.

---

### Task 6: Emission + dedup (`emit.py`, `dedup.py`)

**Files:** Create `src/evalyn/discovery/emit.py`, `src/evalyn/discovery/dedup.py`; Test `tests/discovery/test_emit.py`, `tests/discovery/test_dedup.py`.

**Interfaces:**
- Consumes: `Probe`/`Check` schema, `Objective`, `SessionResult`.
- Produces: `candidate_probe(objective, slots, turns, *, reference_hint) -> Probe`; `probe_yaml(probe, *, provenance: dict) -> str` (header comments + one-entry YAML list); `stage_probe(pack, probe, yaml_text, *, staging_dir=None) -> Path` (default `pack.root/"discoveries"`, atomic temp-then-rename); `_assert_outcome_graded(probe) -> None` (raises on `type: contains` or non-pattern/rubric/verbatim values); `DuplicateFlag(probe_id, reason, score)`; `scan_duplicates(candidate, existing) -> DuplicateFlag|None`; `load_prior_discoveries(staging_dir) -> list[Probe]` (warn+skip unparseable).

- [ ] **Step 1: Failing test** — `test_emitted_probe_is_schema_valid_and_outcome_graded`: `candidate_probe` for injection yields a `Probe` that `Probe.model_validate` accepts; `kind == "regression"`; safety-critical → `samples == 3`, required check present; `_assert_outcome_graded` passes; a probe with a `contains` check RAISES.
- [ ] **Step 2: Failing test** — `test_stage_probe_writes_inert_yaml`: file lands under `<pack>/discoveries/`, round-trips via `yaml.safe_load`, and `load_pack` does NOT pick it up (glob excludes `discoveries/`).
- [ ] **Step 3: Failing test** — `test_scan_duplicates_flags`: a candidate sharing category + a required-check signature + turn Jaccard ≥0.6 with an existing probe returns a `DuplicateFlag` naming that probe; a distinct candidate returns `None`. Never suppresses.
- [ ] **Step 4: Run — FAIL.** `uv run pytest tests/discovery/test_emit.py tests/discovery/test_dedup.py -v`.
- [ ] **Step 5: Implement** emission (outcome-graded assertion, provenance header comments) + deterministic dedup (stdlib only).
- [ ] **Step 6: PASS, suite + lint green, commit** (ask): `feat(discover): outcome-graded probe emission + deterministic dedup flag`.

---

### Task 7: Replay-once (`replay.py`)

**Files:** Create `src/evalyn/discovery/replay.py`; Modify `src/evalyn/engine/run.py` (expose `reduce_log_to_probes`, keep `_reduce_log_to_probes` alias); Test `tests/discovery/test_replay.py`.

**Interfaces:**
- Consumes: `validate_pack`, `build_task`, `inspect_eval`, `reduce_log_to_probes`, `Probe`.
- Produces: `ReplayResult(reproduced: bool, trials: int, pass_k: float, checks: list[dict], log_path: str)`; `async def replay_staged_probe(pack, staged: Path, *, judge_model, rubric_model, cache_dir, log_dir) -> ReplayResult`.

- [ ] **Step 1: Failing test** — `test_replay_reproduces_planted_failure`: stage a probe whose required check fails against the toy target (mockllm/deterministic), replay → `reproduced is True`, `trials >= 1`, `pass_k == 0.0`.
- [ ] **Step 2: Failing test** — `test_replay_reads_bytes_from_disk`: replay validates the exact staged file (`Probe.model_validate(yaml.safe_load(path)[0])`) and runs `validate_pack` on the one-probe pack (a bad `reference` fails fast before eval).
- [ ] **Step 3: Run — FAIL.** `uv run pytest tests/discovery/test_replay.py -v`.
- [ ] **Step 4: Implement** replay (read-back → `validate_pack` → `build_task` → `inspect_eval` → `reduce_log_to_probes`; reproduced ⇔ `trials>=1 and pass_k==0.0`).
- [ ] **Step 5: PASS, suite + lint green, commit** (ask): `feat(discover): auto-replay staged probe via gate machinery`.

---

### Task 8: Solver + task + orchestrator (`solver.py`, `task_builder.py`, `run.py`, `personas.py`)

**Files:** Create `src/evalyn/discovery/solver.py`, `src/evalyn/discovery/task_builder.py`, `src/evalyn/discovery/run.py`, `src/evalyn/discovery/personas.py`; Test `tests/discovery/test_run.py`, `tests/discovery/test_personas.py`.

**Interfaces:**
- Consumes: everything above.
- Produces: `discovery_solver(...)` (`@solver`; one Sample = one hunt; writes `SessionResult` to `store["evalyn:discovery_session"]`); `build_discovery_task(pack, cfg) -> Task` (dataset of hunts, **no scorer**, `fail_on_error=False`); `Finding(objective_id, confirmed, probe_path, replay: ReplayResult, duplicate_of, duplicate_reason)`; `DiscoveryArtifact(...)`; `async def run_discovery(pack, cfg) -> DiscoveryArtifact`; `write_discovery_artifact(artifact, out_dir) -> Path` (atomic `runs/<stamp>-<uuid>-<slug>-discover.json`); `render_discovery_report(artifact) -> str`; `load_personas`, `load_playbooks`, `DEFAULT_PERSONA`.

- [ ] **Step 1: Failing test (Store round-trip)** — `discovery_solver` on a scripted hunt writes a `SessionResult` recoverable from the eval log sample's store (mirror `tests` for `evalyn:session_seconds`).
- [ ] **Step 2: Failing test (orchestrator end-to-end, mockllm)** — `run_discovery` on the toy pack with a scripted agent produces a `DiscoveryArtifact` with ≥1 `Finding`, each with a staged `probe_path` and a `ReplayResult`; artifact written atomically to `runs/`.
- [ ] **Step 3: Failing test (budget → partial)** — a tiny cap yields a completed artifact with a partial flag/banner and NO exception.
- [ ] **Step 4: Run — FAIL.** `uv run pytest tests/discovery/test_run.py -v`.
- [ ] **Step 5: Implement** solver/task/orchestrator + persona loaders; artifact write BEFORE any raise; post-hoc reconcile via meter/log; report renders findings + replay verdicts + duplicate flags + budget banner.
- [ ] **Step 6: PASS, suite + lint green, commit** (ask): `feat(discover): solver + task + orchestrator + report`.

---

### Task 9: Family rule — `family_warnings(discovery_model=…)`

**Files:** Modify `src/evalyn/engine/task_builder.py`; Test `tests/engine/test_task_builder.py` (extend).

**Interfaces:**
- Produces: `family_warnings(pack, *, judge_model, rubric_model, discovery_model=None) -> list[str]` — existing entries preserved; two new when `discovery_model` given: discovery↔judge same family (REFUSE-class message), discovery↔generator same family (WARN-class message). `build_task` still calls it and `warnings.warn`s each string.

- [ ] **Step 1: Failing test** — `test_family_warns_discovery_vs_generator`: `discovery_model` and generator same family → a warn-class string present; `test_family_refuses_discovery_vs_judge`: discovery & rubric judge same family → a refuse-class string present (distinguishable prefix for the CLI to turn into exit 2).
- [ ] **Step 2: Failing test** — existing `build_task` family tests still pass unchanged.
- [ ] **Step 3: Run — FAIL.** `uv run pytest tests/engine/test_task_builder.py -k family -v`.
- [ ] **Step 4: Implement** the two additional entries with a stable refuse/warn prefix convention.
- [ ] **Step 5: PASS, suite + lint green, commit** (ask): `feat(discover): extend family-parity check to the discovery agent`.

---

### Task 10: CLI `discover` subcommand

**Files:** Modify `src/evalyn/cli.py` (new `@app.command()` `discover`); Modify `pyproject.toml` (add `openai`); Test `tests/test_cli.py` (extend) + `tests/discovery/test_cli_discover.py`.

**Interfaces:**
- Consumes: `run_discovery`, `load_pack`, `resolve_base_url`, `validate_pack`, `family_warnings`, `is_stale`.
- Produces: the `discover` command with flags from spec §8; preflight mirroring `gate`; exit codes `0`/`2`/`3`.

- [ ] **Step 1: Failing test (dry-run)** — `CliRunner` `discover --target packs/example --dry-run` exits 0 and prints objectives × personas, caps, resolved target, staging dir; zero model/HTTP calls.
- [ ] **Step 2: Failing test (family refuse)** — same agent+judge family without `--allow-family-collision` exits 2; with the flag, proceeds.
- [ ] **Step 3: Failing test (tier-3 staleness gate)** — selecting `hallucination` on an uncalibrated pack exits 2; `--allow-uncalibrated` proceeds with a banner; selecting only deterministic objectives does NOT trigger the staleness gate.
- [ ] **Step 4: Failing test (exit codes)** — a completed run (findings or none) exits 0; every-session-errored exits 3.
- [ ] **Step 5: Run — FAIL.** `uv run pytest tests/discovery/test_cli_discover.py -v`.
- [ ] **Step 6: Implement** the command + preflight; add `openai` to `pyproject.toml` and `uv sync`.
- [ ] **Step 7: PASS, suite + lint green, commit** (ask): `feat(cli): evalyn discover subcommand`.

---

### Task 11: Toy-pack weaknesses + persona/playbook

**Files:** Modify `examples/toy_target.py` (planted weaknesses behind `TOY_DISCOVERY_WEAKNESSES`); Create `packs/example/personas/curious-auditor.md`, `packs/example/playbooks/trust-then-pivot.md`, `packs/example/discoveries/.gitkeep`; Modify `.github/workflows/*` CI self-test env (`TOY_DISCOVERY_WEAKNESSES=0`); Test `tests/test_example_pack.py` (extend) + `tests/discovery/test_toy_weaknesses.py`.

**Interfaces:**
- Produces: four planted weaknesses (spec §10) reachable only by adaptive probing, disjoint from every existing probe turn; gated OFF in CI so `ci/baseline-example.json` never moves.

- [ ] **Step 1: Failing test** — `test_toy_weaknesses_flag_off_matches_baseline`: with `TOY_DISCOVERY_WEAKNESSES=0`, a gate run on the toy still matches `ci/baseline-example.json` (baseline unchanged).
- [ ] **Step 2: Failing test** — `test_planted_injection_reachable`: with the flag on, a ≥2-turn session containing "verbatim"/"configuration"/"audit" leaks an internal marker; a 1-turn message does not (proves it's the trust-pivot the static probes miss).
- [ ] **Step 3: Failing test** — `test_planted_pii_and_persona`: "email"/"contact" volunteers a fake email+phone; "who is <owner>" replies third-person.
- [ ] **Step 4: Run — FAIL.** `uv run pytest tests/discovery/test_toy_weaknesses.py -v`.
- [ ] **Step 5: Implement** the planted branches (do NOT touch `packs/example/target.yaml` `invariants:`; keep triggers disjoint from existing probe turns) + persona/playbook files + set the CI env var.
- [ ] **Step 6: PASS, suite + lint green, `uv run evalyn validate-pack packs/example` exit 0, commit** (ask): `feat(discover): toy-target planted weaknesses + persona/playbook (CI-gated off)`.

---

### Task 12: End-to-end zero-spend acceptance

**Files:** Test `tests/discovery/test_e2e_discover.py`.

**Interfaces:** Consumes the whole stack; asserts the spec §12 success bar with zero spend.

- [ ] **Step 1: Failing test** — `test_discover_toy_end_to_end`: with weaknesses ON and a scripted/mockllm agent that adaptively hits the 3 deterministic planted bugs, `run_discovery` yields ≥1 confirmed finding and ≥1 emitted probe whose `ReplayResult.reproduced is True`; the emitted probe file loads via `Probe.model_validate`; the run exits 0.
- [ ] **Step 2: Failing test** — `test_adopted_probe_reds_gate`: move a staged probe into `probes/`, run `gate` → it now FAILS (the flywheel closes). Then remove it (leave the pack clean).
- [ ] **Step 3: Run — FAIL, then implement any glue exposed**, **Step 4: PASS**, full suite + lint green, **commit** (ask): `test(discover): end-to-end flywheel acceptance (zero spend)`.

---

### Task 13: Docs, roadmap, version, register

**Files:** Modify `docs/EVALYN_EXPLAINED.md` (fix the "automatically" → human-review discrepancy, spec §14), `docs/CI_ADOPTION.md` (discover-findings → human-triage note), `docs/ROADMAP.md` (Plan #3 status ✅ + change-log entry), `docs/JOURNAL.md` (per-task entries + register close-out), `pyproject.toml` (version bump, e.g. `v0.4.0`).

- [ ] **Step 1:** Correct `EVALYN_EXPLAINED.md` §8/glossary: confirmed findings become gate tests **after human review** (inert staging dir + hand-adopt), not "automatically".
- [ ] **Step 2:** Add the `CI_ADOPTION.md` note; update ROADMAP status + change-log; write `JOURNAL.md` entries; bump the version.
- [ ] **Step 3:** `uv run pytest -q` + `uv run ruff check src/ tests/` green; both packs `validate-pack` exit 0. **Commit** (ask): `docs: Plan #3 discover delivered — explainer fix, roadmap, vX.Y.0`.

---

### Task 14: USER-GATED live TwinCore pre-run (demo material)

**Not run until the maintainer consents with a cost statement.** Real sessions + real judge spend.

**Files:** capture stdout to the SDD workspace; NO calibration.json overwrite; NO `runs/` commit.

- [ ] **Step 1 (prep, zero-spend):** verify `packs/twincore` has the confirming checks — injection
  `no-internal-leak` invariant, `pii` probes, `first-person` invariant, calibrated `groundedness`
  rubric (fresh calibration). Report any gap to the maintainer.
- [ ] **Step 2 (GATE):** present the estimated cost (≈ sessions × turns + judge tokens for the
  hallucination objective) and get fresh explicit consent.
- [ ] **Step 3 (consented run):** `uv run evalyn discover --target packs/twincore --objective … --max-usd <cap> > <sdd>/twincore-discover.stdout 2>&1`; all four objectives; capture full stdout.
- [ ] **Step 4:** review findings with the maintainer; keep artifacts local (gitignored `runs/`); the emitted probes stay in `discoveries/` for human triage. This is the demo's pre-baked TwinCore material.

---

## Acceptance (whole plan — mirrors spec §12)

- `evalyn discover` on the toy target finds ≥1 confirmed problem and emits ≥1 reproducible probe
  (replay REPRODUCED); adopting it reds `gate` (flywheel closes).
- Agent structurally cannot leave the allowlist; budget stop → partial report, exit 0.
- Confirmation reuses existing scorers verbatim; unsure never a finding.
- `discover` never in the CI blocking path; toy baseline unchanged with `TOY_DISCOVERY_WEAKNESSES=0`.
- Full suite green (481 → grows), ruff clean, both packs `validate-pack` exit 0.

## Self-review (writing-plans)

- **Spec coverage:** every spec §3 decision maps to a task (engine→T1/5; objectives→T1; trust
  boundary→T4; family rule→T9; flywheel/emission→T6; replay→T7; dedup→T6; bounds/budget→T2/5;
  exit codes→T10; toy demo→T11; success bar→T12; docs/EXPLAINED fix→T13; live TwinCore→T14). The
  `TargetSession` extraction (arch §4.2) is T0.
- **Placeholders:** none — every task carries concrete signatures, representative test assertions,
  and exact run/commit commands. Implementers use TDD (RED shown first) per subagent-driven-development.
- **Type consistency:** `Objective`/`Confirmation`/`SessionResult`/`Finding`/`ReplayResult`/
  `DiscoveryArtifact` names and fields are used consistently across T1→T12; `reduce_log_to_probes`
  (T7) matches the rename in `engine/run.py`; `family_warnings` signature (T9) matches the CLI use (T10).
