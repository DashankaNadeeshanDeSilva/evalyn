# Plan #3 `discover` — session handoff & kickoff (resume at Task 8b)

**Written:** 2026-08-05, at the close of Task 8a. **Branch:** `feat/plan3-discover`
(cut from `dev` @ `6d6753d`). **Nothing is pushed.**

This document is the complete state transfer for a fresh session. Read it, then read the four
source-of-truth docs it points at. **Do not re-plan** — the design and plan are ratified, and every
open decision has already been ruled on in writing.

---

## 1. Where things stand

**Tasks 0–7 complete and 8a complete** (each reviewed clean; most needed one fix round).
**Task 8b is next.** Tasks 9–14 remain.

Task 8 was **split by controller ruling R8-0** into:
- **8a** — `solver.py` + `task_builder.py` + `tests/discovery/test_personas.py` ✅ **done**
- **8b** — `run.py`: the orchestrator ⏳ **next up**

**Controller-verified at the pause — real output, not claims:**

```
uv run pytest -q -W error::RuntimeWarning   → 647 passed   (branch started at 481; 595 last session)
uv run ruff check src/ tests/               → All checks passed!
uv run evalyn validate-pack packs/example   → exit 0
uv run evalyn validate-pack packs/twincore  → exit 0
git status                                  → clean
```

**HEAD is `9075d37`.** Task 8a's fix round was re-reviewed and closed clean before this handoff was
written — there is no owed re-review. 20 commits on the branch.

Commits on the branch this session (oldest first):

| Commit | Subject |
|---|---|
| `7e4851e` | feat(discover): outcome-graded probe emission + deterministic dedup flag |
| `06844cd` | fix(discover): neutralise every YAML comment break in provenance headers |
| `2475de5` | docs: Plan #3 journal checkpoint — Task 6 complete |
| `4f12a0a` | feat(discover): auto-replay staged probe via gate machinery |
| `3a5481e` | fix(discover): always return a reconcilable log path from replay |
| `5df93ea` | docs: Plan #3 journal checkpoint — Task 7 complete |
| `f6e776f` | feat(discover): discovery solver + task builder (one sample = one hunt) |
| `9075d37` | fix(discover): warn when a tier-3 hunt has no rubric judge configured |
| *(this handoff + journal checkpoint)* | docs: Plan #3 journal checkpoint — Task 8a complete |

## 2. Read these first (in this order)

1. `docs/superpowers/plans/2026-08-04-evalyn-plan3-discover.md` — **the plan you execute.** Task 8
   onward. Global Constraints at the top bind every task.
2. `docs/superpowers/specs/2026-08-04-discover-mode-design.md` — the ratified design (§6
   confirmation table, §7 emission/dedup/replay/orchestration, §8 CLI surface, §10 toy weaknesses,
   §12 success bar).
3. `docs/JOURNAL.md` → **Plan #3 section** — the committed record: task table, what the reviews
   caught, and the full deferred-findings register. Source of truth for open items.
4. `.superpowers/sdd/2026-08-04-evalyn-plan3-discover/` — the SDD workspace: `progress.md` (the
   recovery ledger — **append, do not restart**), pre-extracted task briefs 6–13, per-task
   controller-rulings files, and implementer reports.

**The controller-rulings files are load-bearing** — they carry decisions the plan does not:
`task-6-controller-rulings.md`, `task-7-controller-rulings.md`, **`task-8-controller-rulings.md`
(R8-0 … R8-17 — read this in full before dispatching 8b).**

## 3. What exists now — established interfaces (do NOT re-derive)

Package `src/evalyn/discovery/`:

- **`objectives.py`** — `OBJECTIVES` (read-only mapping; code-owned so a pack cannot forge a
  confirming check), `get_objective`, `default_objectives`. Four ids:
  `prompt-injection-bypass`, `pii-leak`, `persona-break` (tier 1), `hallucination` (tier 3).
- **`config.py`** — `Limits(max_steps, max_sessions, max_usd, max_turns)`, `CliLimits` (all-optional
  — **Task 10 must construct this**), `resolve_limits(pack, cli_limits)` clamping downward only,
  frozen `DiscoveryConfig`.
- **`meter.py`** — `SpendMeter(cap_usd)`: `charge_output` (usage-less output charges a pessimistic
  16k/4k estimate, **not** 0), `charge_estimate`, `spent_usd`, `exhausted()` (`>=`),
  `remaining_usd`, `BudgetStop`, `reconcile(log)` — **takes a log OBJECT, not a path.**
- **`confirm.py`** — `Confirmer(pack, *, rubric_model, cache_dir, meter)`; requires a meter when
  `rubric_model` is set. `async confirm(probe, messages) -> Confirmation(confirmed, unsure, tier,
  check_results, reason)`. `tier3_confirmation_usd(model, n)` is the charge helper.
- **`loop.py`** — `AgentAction`, `parse_action` (strict JSON, one retry then stop; **no code-fence
  stripping**), `verify_slots`, `StepRecord`, `SessionResult(objective_id, confirmed, probe_slots,
  steps, stop_reason, turns_used, usd_estimated, error, persona_id, playbook_id)`,
  `async run_session(pack, objective, persona, playbook, *, agent_model, meter, limits, confirmer,
  seed=None)`.
- **`personas.py`** — `Persona`, `Playbook`, `load_personas`, `load_playbooks`, `DEFAULT_PERSONA`,
  `DEFAULT_PLAYBOOK`.
- **`emit.py` (Task 6)** — `candidate_probe(objective, slots, turns, *, reference_hint=None)` —
  **THE single definition**, called by both `loop.py` (confirming) and staging (emission);
  id = `discovered-{objective.id}-{sha256_8}`; `samples=3` iff safety-critical;
  `_assert_outcome_graded` runs *inside* it, raising `ValueError`.
  `answered_user_turns(transcript)` drops unanswered orphan user turns.
  `probe_yaml(probe, *, provenance)`, `stage_probe(pack, probe, yaml_text, *, staging_dir=None)`
  (atomic same-dir temp + `os.replace`), `load_prior_discoveries(staging_dir)` (warn+skip
  unparseable, emits `RuntimeWarning`).
- **`dedup.py` (Task 6)** — `DuplicateFlag`, `scan_duplicates(candidate, existing)`: strict
  conjunction of same category + required-check signature overlap + turn Jaccard ≥ 0.6. Advisory,
  **never suppresses**.
- **`replay.py` (Task 7)** — `ReplayResult(reproduced, trials, pass_k, checks, log_path, reason)`,
  `async replay_staged_probe(pack, staged: Path, *, judge_model, rubric_model, cache_dir, log_dir)`.
  Order: read **bytes off disk** → `Probe.model_validate` → `replace(pack, probes=[staged])` →
  `validate_pack` → `build_task` → `inspect_eval` (via `asyncio.to_thread`) →
  `reduce_log_to_probes`. **Reproduced ⇔ `trials >= 1 and pass_k == 0.0`.** Pack invariants are
  **NOT** blanked (deliberately unlike `confirm.py`). `log_path` may be a **directory**.
- **`solver.py` + `task_builder.py` (Task 8a)** — `discovery_solver(...)` awaits `run_session`
  **inside the sample** (this is what makes agent spend land in the log), inside
  `concurrency("evalyn-target-http", pack.spec.concurrency)` — a verbatim match with
  `engine/solver.py`. `session_from_store(value) -> SessionResult | None`.
  `build_discovery_task(pack, cfg, *, meter, ...)`: **no scorer**, `fail_on_error=False`,
  round-robin dataset, store key `evalyn:discovery_session`.

Changed existing modules:

- **`src/evalyn/targets/session.py`** — `TargetSession`, the **only** target driver.
  `resolve_base_url` is called inside `open()` — the allowlist bites there.
- **`src/evalyn/scoring/tier1.py`** — `no-pii-leak` invariant (email + E.164-ish phone).
- **`src/evalyn/engine/run.py`** — now exposes public `reduce_log_to_probes`, `_reduce_log_to_probes`
  alias retained.

## 4. The invariants that govern everything

1. **The agent PROPOSES, the scoring layer DISPOSES.** "Confirmed" ⇔ the candidate probe's required
   checks FAIL against the transcript via the *real* tier-1/tier-3 scorers. **Unsure is never a
   finding.** Confirmation blanks pack-level invariants so what confirms and what gets emitted are
   the same artifact; **replay deliberately does not** (it asks "does this red the gate as
   written?").
2. **Containment is structural, not policed.** Closed action enum (`send`/`propose`/`stop`), `send`
   takes only a `str`, no URL/file/shell tool. `loop.py` imports no
   httpx/requests/urllib/socket/subprocess and a test guards it. **Do not widen this.**
3. **One definition of the candidate probe.** `emit.candidate_probe`. A second definition is an
   automatic review failure — it is how confirming and emitting silently diverge.
4. **Zero spend through Task 13.** Task 14 is USER-GATED.

## 5. Task 8b — your next task, and its obligations

**Scope:** `src/evalyn/discovery/run.py` — `Finding(objective_id, confirmed, probe_path, replay,
duplicate_of, duplicate_reason)`, `DiscoveryArtifact`, `async run_discovery(pack, cfg)`,
`write_discovery_artifact(artifact, out_dir)` (atomic `runs/<stamp>-<uuid>-<slug>-discover.json`),
`render_discovery_report(artifact)`. The plan's Task 8 **Steps 2–3**. Tests: `tests/discovery/test_run.py`.

**Read `task-8-controller-rulings.md` in full.** The rulings binding 8b:

- **R8-3** — replay of a tier-3 probe spends real judge money. Reconcile every replay log into the
  meter; **skip replay when the meter is exhausted** and record `replay: skipped (budget)`.
  Pass `judge_model` **explicitly** (see the fabricated-`reproduced` trap in §6).
- **R8-4** — widen `emit._C0_CONTROLS` to the complement of PyYAML's printable set. 8b is what wires
  agent-influenced text into provenance, making a latent defect live.
- **R8-5** — the artifact is written **before** any raise. A budget stop yields a partial report and
  exit 0, never a traceback.
- **R8-13** — reuse `run_gate`'s atomic artifact writer; do not duplicate it.
- **R8-14** — record **both** live (`meter.spent_usd`) and reconciled USD as separate fields and use
  the **larger** for the banner/cap decision. Never sum (double-counts); never let a reconciled
  figure silently replace a higher live one.
- **R8-15** — give each replay its **own log directory** (`<log_root>/replay-<probe_id>/`), because
  `log_path` may be a directory and a shared dir would double-count earlier replays' logs.
- **R8-16** — the judge/generator family rule is **Task 9's**, not 8b's. Do not build it in `run.py`.
- **R8-17** — a sample that errors *outside* the solver leaves **no** store entry; count it toward
  the error total. Matters for Task 10's exit 3.
- **R8-2** — `render_discovery_report` must surface `stop_reason == "error"` **counts prominently**,
  and `DiscoveryArtifact` must carry the count as a structured field.
- **R8-7** — no test may mutate `packs/example/` in the working tree; use tmp copies.

**R8-1 is ANSWERED — do not re-investigate.** A controller spike measured it on `inspect_ai`
0.3.249: `get_model()` calls issued **inside a Solver body** ARE recorded in `log.stats.model_usage`,
keyed by their own model name with correct totals, and mirrored at `log.samples[0].model_usage`.
Task 8a confirmed the same in the real solver. **The condition:** reconciliation only covers calls
made inside *the eval whose log you pass* — the hunt log carries **agent** spend, each replay log
carries **judge** spend. Both must be reconciled; they are different logs. `meter.reconcile` had
zero call sites before 8b — you are its first consumer.
**Caveat that must survive into the docstring:** mockllm synthesizes usage, so this proves the
plumbing, not that a real provider populates `ModelOutput.usage`. If one omits it, the log inherits
the omission and `reconcile` **under-reports silently** while the live meter **over-charges loudly**.

## 6. Traps carried into 8b (each is real and currently unreachable — which is why they'd be missed)

- **Fabricated `reproduced=True`:** `replay_staged_probe`'s `judge_model` defaults to
  `mockllm/model` while `rubric_model` defaults to the pack's real judge. A *required* judge-graded
  check answered by a mock judge returns `unsure` → `required_pass=False` → `pass_k == 0.0` →
  `reproduced=True` **fabricated**. Unreachable today only because tier-2 is deliberately excluded.
  **Pass `judge_model` explicitly.**
- **Flaky findings are indistinguishable:** `ReplayResult` carries no `pass_at_k`/`expected_trials`,
  so for a `samples: 3` probe (what Task 6 emits for safety-critical objectives) `reproduced=True`
  covers both "failed 3/3" and "failed 1/3". Spec §7 asks the caller to flag flaky.
- **Rubric objective with no judge goes dark:** fixed in 8a as a warning in `build_discovery_task`;
  **Task 10 must make it a refuse-class CLI preflight (exit 2)**, consistent with the existing
  tier-3 staleness gate.
- **The trust boundary is not yet proven end-to-end through the solver.** Every 8a test uses a spy
  confirmer, so `stop_reason == "confirmed"` is spy-supplied, not scorer-supplied. **8b and Task 12
  must prove a finding confirmed by the real scorers.**
- **The session cap drops hunts silently.** `plan_hunts` drops whole objectives when
  `max_sessions < len(objectives)` — the operator selects four, two run, nothing says so. R8-12's
  round-robin fixed the distribution, not the silence. **Task 10's preflight** should print "cap
  dropped objectives X, Y", alongside making the rubric-judge warning a refuse-class exit 2.

Every other open item, per task, is in `docs/JOURNAL.md` → Plan #3 → *Open items*, and in the ledger.

## 7. Working agreements (non-negotiable)

- **Subagent model: Opus 5**, set explicitly on **every** dispatch — implementers, fixers AND
  reviewers. An omitted `model` silently inherits the session's.
- **Execution method:** superpowers:subagent-driven-development — one fresh subagent per task, TDD
  with discriminating RED shown first, two-stage review, fix rounds capped at 5. Never dispatch two
  implementers in parallel (commit races). Hand subagents **files** (briefs, rulings, review
  packages), never pasted history.
- **A bare `ModuleNotFoundError` is weak RED evidence.** Every task so far has been required to show
  its tests genuinely discriminate — via mutation checks or an inverted stub. **Keep that bar**; it
  is what caught the non-discriminating YAML test in Task 6.
- **Write controller rulings to a file before dispatching** a task, and point both the implementer
  and the reviewer at it. This is what made the reviews sharp — reviewers verify against the rulings.
- **Commits happen automatically** under the maintainer's identity, no Claude trailer:
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit …`
  Conventional prefixes. **ASK before every push and before opening/updating any PR.**
- **`uv` only** — system `python3` is 3.9. `uv run pytest -q -W error::RuntimeWarning`,
  `uv run ruff check src/ tests/`. The suite must stay warning-clean and **unmodified**.
- **Checkpoint the ledger AND `docs/JOURNAL.md` at every task completion**, committing the journal
  separately (`docs: Plan #3 journal checkpoint — Task N …`).
- **Never** overwrite `packs/twincore/calibration.json` outside a consented passing calibrate run.
  Never commit `runs/`. The NiuwnAI product repo (`…/niuwnai-mvp`) is READ-ONLY.
- CI self-test must keep `TOY_DISCOVERY_WEAKNESSES=0` so `ci/baseline-example.json` never moves.
  `discover` is never in the CI blocking path.

## 8. FIRST ACTIONS in the new session

1. `git log --oneline -3` and `git status` — confirm the tree is clean and note HEAD.
2. Re-verify the baseline and **report the numbers**:
   `uv run pytest -q -W error::RuntimeWarning`, `uv run ruff check src/ tests/`,
   both packs `validate-pack`.
3. Read `.superpowers/sdd/2026-08-04-evalyn-plan3-discover/progress.md` — the tail carries Task 8a's
   completion line and every deferred minor. Nothing is owed; 8a closed clean.
4. Read `task-8-controller-rulings.md` in full, then dispatch Task 8b per §5.

## 9. Success bar (spec §12) and the deadline

`evalyn discover` on the toy target finds **≥1 confirmed** problem (validated by the scoring layer,
not self-asserted) and emits **≥1 reproducible** probe file; adopting it **reds `gate`** — the
flywheel closes. Agent structurally cannot leave the allowlist; a budget stop yields a partial
report, exit 0. Full suite green, ruff clean, both packs `validate-pack` exit 0.

**AI Tinkerers Bremen demo: 2026-08-14.** Remaining: 8b, 9, 10, 11, 12, 13, then the gated 14.
If the schedule tightens, the pre-agreed safe cut is injection + PII live on the toy, with
hallucination + persona shown from logs (all four still ship in code) — **confirm with the
maintainer before cutting.**

**Task 14 is USER-GATED**: a live TwinCore discovery pre-run requiring fresh explicit consent with
the cost stated first, full stdout captured to the SDD workspace (`… > file 2>&1`).

---

## Kickoff prompt for the new session

Paste everything below into a fresh session.

```
Continue executing Evalyn Plan #3 (`discover` mode + flywheel). Tasks 0–8a are DONE; resume at Task 8b.

Read first, in this order:
1. docs/superpowers/handoffs/2026-08-05-plan3-task8b-kickoff.md  — full state transfer (start here)
2. docs/superpowers/plans/2026-08-04-evalyn-plan3-discover.md    — the plan you execute (Tasks 8–14)
3. docs/superpowers/specs/2026-08-04-discover-mode-design.md     — the ratified design spec
4. docs/JOURNAL.md → Plan #3 section                             — task table + deferred-findings register
5. .superpowers/sdd/2026-08-04-evalyn-plan3-discover/task-8-controller-rulings.md — R8-0…R8-17, BINDING

You are the lead engineer and execution controller. You delegate ALL implementation to fresh
subagents — implementers, fixers AND reviewers — using superpowers:subagent-driven-development, with
`model: opus` set explicitly on every dispatch. Your job is orchestration, review and verification,
not writing code yourself.

State: branch `feat/plan3-discover`, cut from `dev` @ 6d6753d, nothing pushed. Re-verify before
starting and report the numbers: `uv run pytest -q -W error::RuntimeWarning`,
`uv run ruff check src/ tests/`, both packs `validate-pack` exit 0, `git status`.

The SDD workspace and ledger already exist at `.superpowers/sdd/2026-08-04-evalyn-plan3-discover/` —
task briefs 6–13 are pre-extracted and per-task controller-rulings files sit beside them. Append to
that ledger; do not start a new one. CHECK ITS TAIL FIRST: if Task 8a's fix round has no completion
line, the scoped re-review is owed — run that before anything else.

Task 8 was SPLIT by controller ruling R8-0: 8a (solver + task_builder) is done; 8b is the
orchestrator `run.py` — Finding, DiscoveryArtifact, run_discovery, write_discovery_artifact,
render_discovery_report. Rulings R8-2, R8-3, R8-4, R8-5, R8-7, R8-13, R8-14, R8-15, R8-16 and R8-17
bind it. R8-1 is already ANSWERED by a measured spike — do not re-investigate it.

Working agreements: commits happen automatically under the maintainer's identity with no Claude
trailer (`git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com'
commit …`), conventional prefixes; ASK before every push and before any PR. `uv` only. The suite must
stay green, unmodified and warning-clean. A bare ModuleNotFoundError is weak RED evidence — require
every task to show its tests genuinely discriminate. Write controller rulings to a FILE before each
dispatch and point both implementer and reviewer at it. Tasks 8b–13 are zero-spend; **Task 14 is
USER-GATED** and needs fresh explicit consent with the cost stated first.

Deadline context: the AI Tinkerers Bremen demo is 2026-08-14. Flag scope cuts EARLY.

Execute Tasks 8b→13 continuously, checkpointing the ledger and docs/JOURNAL.md at each task
completion. Stop before Task 14 and present the cost estimate. Use skills. Think hard.
```
