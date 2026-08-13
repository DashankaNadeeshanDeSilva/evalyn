# Plan #3 `discover` — session handoff & kickoff (resume at Task 6)

**Written:** 2026-08-04, at the close of Task 5. **Branch:** `feat/plan3-discover` @ `72d9589`
(cut from `dev` @ `6d6753d`). **Nothing is pushed.**

This document is the complete state transfer for a fresh session. Read it, then read the three
source-of-truth docs it points at. Do not re-plan — the design and plan are ratified.

---

## 1. Where things stand

**Tasks 0–5 of 14 are complete**, each reviewed clean (four needed one fix round apiece).
Tasks 6–14 remain.

**Controller-verified at the pause — real output, not claims:**

```
uv run pytest -q -W error::RuntimeWarning   → 595 passed   (branch started at 481)
uv run ruff check src/ tests/               → All checks passed!
uv run evalyn validate-pack packs/example   → exit 0
uv run evalyn validate-pack packs/twincore  → exit 0
git status                                  → clean
```

Ten commits on the branch, oldest first:

| Commit | Subject |
|---|---|
| `a5a1710` | refactor: extract TargetSession from solver (no behavior change) |
| `6c0179e` | fix: preserve partial transcript on mid-send failure |
| `dc8fe06` | feat(discover): objective registry + run config |
| `129870b` | feat(discover): live spend meter + log reconcile |
| `799fb9c` | fix(discover): charge a conservative estimate when model usage is missing |
| `f09594d` | feat(scoring): add no-pii-leak tier-1 invariant (email+phone) |
| `b45c73b` | feat(discover): Confirmer reuses tier-1/tier-3 (trust boundary) |
| `088cbe2` | fix(discover): fail closed on unevaluable candidate checks; require a meter |
| `de0f073` | feat(discover): observe-reason-pursue session loop |
| `72d9589` | fix(discover): tighten verify_slots to assistant turns; survive transient sends |

## 2. Read these first (in this order)

1. `docs/superpowers/plans/2026-08-04-evalyn-plan3-discover.md` — **the plan you execute.** Task 6
   onward. Global Constraints at the top bind every task.
2. `docs/superpowers/specs/2026-08-04-discover-mode-design.md` — the ratified design (WHAT discover
   is; §6 confirmation table, §7 emission/dedup/replay, §8 CLI surface, §10 toy weaknesses).
3. `docs/JOURNAL.md` → **Plan #3 section** — the committed record: task table, what the reviews
   caught, and the full deferred-findings register. This is the source of truth for open items.
4. `.superpowers/sdd/2026-08-04-evalyn-plan3-discover/progress.md` — the session-recovery ledger
   (gitignored scratch; the JOURNAL supersedes it for anything that must survive).

## 3. What exists now — established interfaces (do NOT re-derive)

New package `src/evalyn/discovery/`:

- **`objectives.py`** — `OBJECTIVES: Mapping[str, Objective]` (a `MappingProxyType`; objectives are
  code-owned so a pack cannot forge a confirming check), `get_objective`, `default_objectives`.
  `Objective.confirm_checks(slots) -> list[Check]`; blank slot values are rejected.
  Four ids: `prompt-injection-bypass`, `pii-leak`, `persona-break` (tier 1), `hallucination` (tier 3).
- **`config.py`** — `Limits(max_steps, max_sessions, max_usd, max_turns)` (**4 fields**;
  `max_turns` was added), `CliLimits` (all-optional — **Task 10 must construct this**),
  `resolve_limits(pack, cli_limits)` clamping downward only, frozen `DiscoveryConfig`.
  Defaults match spec §8: steps 8, sessions 4, agent `openai/gpt-5-mini`, judge `mockllm/model`,
  `out_dir=runs`, `staging_dir=None` → pack's `discoveries/`, `replay=True`.
- **`meter.py`** — `SpendMeter(cap_usd)`: `charge_output(model, out)` (a usage-less output charges a
  pessimistic 16k/4k estimate, **not** 0), `charge_estimate(usd)`, `spent_usd`, `exhausted()` (`>=`),
  `remaining_usd`, `BudgetStop`, `reconcile(log)` (agrees with `engine/run.py`'s `_judge_usd`).
- **`confirm.py`** — `Confirmer(pack, *, rubric_model, cache_dir, meter)`; **requires a meter when
  `rubric_model` is set** (ValueError at construction + a runtime refusal making zero judge calls).
  `async confirm(probe, messages) -> Confirmation(confirmed, unsure, tier, check_results, reason)`.
  `tier3_confirmation_usd(model, n)` is the charge helper.
- **`loop.py`** — `AgentAction`, `parse_action` (strict JSON, one retry then stop; **no code-fence
  stripping**), `verify_slots(slots, transcript: Sequence[ChatMessage]) -> bool`, `StepRecord`,
  `SessionResult(objective_id, confirmed, probe_slots, steps, stop_reason, turns_used,
  usd_estimated, error, persona_id, playbook_id)`, `async run_session(pack, objective, persona,
  playbook, *, agent_model, meter, limits, confirmer, seed=None)`.
- **`personas.py`** — `Persona`, `Playbook`, `load_personas`, `load_playbooks`, `DEFAULT_PERSONA`,
  `DEFAULT_PLAYBOOK`.

Changed existing modules:

- **`src/evalyn/targets/session.py` (new)** — `TargetSession`, extracted from `engine/solver.py`
  with zero behavior change. `async with TargetSession.open(pack, timeout=30.0) as s`;
  `await s.send(msg) -> str` raising `TurnCapExceeded` at the cap; `turns_used`, `elapsed_seconds`,
  `messages` (returns a **copy**). `resolve_base_url` is called inside `open()` — the allowlist bites
  there. **This is the only target driver; do not write another.** The Inspect `concurrency()` gate
  stays in `engine/solver.py` around the session, so discovery must do its own gating.
- **`src/evalyn/scoring/tier1.py`** — added the `no-pii-leak` invariant (email + E.164-ish phone).
  It flows into `validate.KNOWN_INVARIANTS` automatically.

## 4. The two invariants that govern everything

1. **The agent PROPOSES, the scoring layer DISPOSES.** "Confirmed" ⇔ the candidate probe's required
   checks FAIL against the transcript, via the *real* tier-1/tier-3 scorers. **Unsure is never a
   finding.** Confirmation blanks pack-level invariants
   (`replace(pack, spec=pack.spec.model_copy(update={"invariants": []}))`) so what confirms and what
   gets emitted are the same artifact.
2. **Containment is structural, not policed.** The action space is a closed enum
   (`send`/`propose`/`stop`), `send` takes only a `str`, and there is **no URL, file, or shell tool**.
   The agent never handles a URL, so it cannot leave the allowlist. `loop.py` imports no
   httpx/requests/urllib/socket/subprocess/os/pathlib, and a test guards that. **Do not widen this.**

## 5. Start Task 6 with these obligations in hand

**Task 6 (emission + dedup) carries one binding obligation from Task 5's review:**

> `loop.py` has a private `_candidate_probe`. **Task 6 must export `candidate_probe`, make
> `loop.py` call it, and delete `_candidate_probe`.** A second definition means what confirms a
> finding and what gets emitted as a permanent regression probe could diverge — the exact failure the
> trust boundary exists to prevent. `_assert_outcome_graded` must also run on the *confirming* probe,
> not only the emitted one. **If Task 6 writes a second definition instead, treat that as a review
> failure of Task 6.**

Divergence today is latent and changes no verdict (`Confirmer` reads only `probe.checks` and
`probe.id`): `samples=1` vs `3` for safety-critical, a different id scheme, and no `reference`.

Also relevant to Task 6: a failed send leaves an **orphan user turn** in `session.messages`, which
now flows into the probe's `turns` list — so a finding confirmed after a transient failure would
carry a turn the target never answered, changing the conversation on replay.

Every other open item, per task, is in `docs/JOURNAL.md` → Plan #3 → *Open items*.

## 6. Working agreements (non-negotiable)

- **Subagent model: Opus 5**, set explicitly on every dispatch (implementers, fixers AND reviewers).
  The maintainer originally asked for Fable; the Fable 5 limit was hit mid-plan and Opus was chosen
  for the remainder. An omitted `model` silently inherits the session's.
- **Execution method:** superpowers:subagent-driven-development — one fresh subagent per task, TDD
  with RED shown first, two-stage review, fix rounds capped at 5. Never dispatch two implementers in
  parallel. Hand subagents *files* (briefs, review packages), never pasted history.
- **A bare `ModuleNotFoundError` is weak RED evidence.** Every task so far has been asked to show
  that its tests genuinely discriminate — via mutation checks or an inverted stub. Keep that bar.
- **Commits happen automatically** under the maintainer's identity, no Claude trailer:
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit …`
  Conventional-commit prefixes. **ASK before every push and before opening/updating any PR.**
- **`uv` only** — system `python3` is 3.9. `uv run pytest -q -W error::RuntimeWarning`,
  `uv run ruff check src/ tests/`. The suite must stay warning-clean.
- **Zero spend through Task 13.** **Task 14 is USER-GATED**: a live TwinCore discovery pre-run
  requiring fresh explicit consent with the cost stated first, full stdout captured to the SDD
  workspace (`… > file 2>&1`).
- **Never** overwrite `packs/twincore/calibration.json` outside a consented passing calibrate run.
  Never commit `runs/`. The NiuwnAI product repo (`…/niuwnai-mvp`) is READ-ONLY.
- CI self-test must keep `TOY_DISCOVERY_WEAKNESSES=0` so `ci/baseline-example.json` never moves.
  `discover` is never in the CI blocking path.

## 7. Success bar (spec §12) and the deadline

`evalyn discover` on the toy target finds **≥1 confirmed** problem (validated by the scoring layer,
not self-asserted) and emits **≥1 reproducible** probe file; adopting it **reds `gate`** — the
flywheel closes. Agent structurally cannot leave the allowlist; a budget stop yields a partial report,
exit 0. Full suite green, ruff clean, both packs `validate-pack` exit 0.

**AI Tinkerers Bremen demo: 2026-08-14.** If the schedule tightens, the pre-agreed safe cut is
injection + PII live on the toy, with hallucination + persona shown from logs (all four still ship in
code) — **confirm with the maintainer before cutting.**

---

## Kickoff prompt for the new session

Paste everything below into a fresh session.

```
Continue executing Evalyn Plan #3 (`discover` mode + flywheel). Tasks 0–5 are DONE; resume at Task 6.

Read first, in this order:
1. docs/superpowers/handoffs/2026-08-04-plan3-task6-kickoff.md  — full state transfer (start here)
2. docs/superpowers/plans/2026-08-04-evalyn-plan3-discover.md   — the plan you execute (Tasks 6–14)
3. docs/superpowers/specs/2026-08-04-discover-mode-design.md    — the ratified design spec
4. docs/JOURNAL.md → Plan #3 section                            — task table + deferred-findings register

You are the lead engineer and execution controller. You delegate ALL implementation to fresh
subagents — implementers, fixers AND reviewers — using superpowers:subagent-driven-development, with
`model: opus` set explicitly on every dispatch. Your job is orchestration, review and verification,
not writing code yourself.

State: branch `feat/plan3-discover` @ 72d9589, cut from `dev` @ 6d6753d, nothing pushed, tree clean.
Re-verify before starting: `uv run pytest -q -W error::RuntimeWarning` (expect 595),
`uv run ruff check src/ tests/` (clean), both packs `validate-pack` exit 0. Report the numbers.

The SDD workspace and ledger already exist at
`.superpowers/sdd/2026-08-04-evalyn-plan3-discover/` — task briefs 6–13 are pre-extracted. Append to
that ledger; do not start a new one.

Task 6 carries a BINDING obligation from Task 5's review: `loop.py` has a private
`_candidate_probe`, and Task 6 must export `candidate_probe`, make `loop.py` call it, and DELETE
`_candidate_probe`. A second definition means what confirms a finding and what gets emitted as a
permanent regression probe could diverge — the exact failure the trust boundary exists to prevent.
`_assert_outcome_graded` must also run on the confirming probe, not only the emitted one. If Task 6
writes a second definition, treat that as a review failure of Task 6.

Working agreements: commits happen automatically under the maintainer's identity with no Claude
trailer (`git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com'
commit …`), conventional prefixes; ASK before every push and before any PR. `uv` only. The suite must
stay green, unmodified and warning-clean. A bare ModuleNotFoundError is weak RED evidence — require
every task to show its tests genuinely discriminate. Tasks 6–13 are zero-spend; **Task 14 is
USER-GATED** and needs fresh explicit consent with the cost stated first.

Deadline context: the AI Tinkerers Bremen demo is 2026-08-14. Flag scope cuts EARLY.

Execute Tasks 6→13 continuously, checkpointing the ledger and docs/JOURNAL.md at each task
completion. Stop before Task 14 and present the cost estimate. Use skills. Think hard.
```
