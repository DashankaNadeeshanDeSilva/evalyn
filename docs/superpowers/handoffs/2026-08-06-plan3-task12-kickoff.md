# Plan #3 `discover` — session handoff & kickoff (resume at Task 12)

**Written:** 2026-08-06, at the close of Task 10. **Branch:** `feat/plan3-discover`
(cut from `dev` @ `6d6753d`). **Nothing is pushed.** **Stay on this branch — do NOT cut a new one;**
Tasks 12–14 continue on it, and it only becomes a PR into `dev` at the very end with maintainer
approval.

This is the complete state transfer for a fresh session. Read it, then the source-of-truth docs it
points at. **Do not re-plan** — the design and plan are ratified and every open decision has a written
ruling.

---

## 1. Where things stand

**Tasks 0–11 complete** (each reviewed clean; most needed one fix round). **Task 12 is next**, then
Task 13, then the **USER-GATED** Task 14.

**Controller-verified at this handoff — real output, not claims:**

```
uv run pytest -q -W error::RuntimeWarning   → 694 passed (branch started at 481; warning-clean)
uv run ruff check src/ tests/               → All checks passed!
uv run evalyn validate-pack packs/example   → exit 0
uv run evalyn validate-pack packs/twincore  → exit 0
uv run evalyn discover --help               → exit 0
git status                                  → clean (apart from untracked .claude/)
```

**HEAD is `8869e99`. 29 commits on the branch, nothing pushed.**

Recent branch commits (newest first):

| Commit | Subject |
|---|---|
| `8869e99` | fix(cli): surface would-be discover refusals under --dry-run; align family check to run's rubric model |
| `0bb00e6` | feat(cli): evalyn discover subcommand |
| `a7b3c77` | docs: Plan #3 journal checkpoint — Tasks 8b + 9 + 11 complete (parallel), merged & verified |
| `61f1478` | merge(discover): Task 11 — toy planted weaknesses + persona/playbook (default ON, CI-gated) |
| `89f592d` | merge(discover): Task 9 — family-parity check extended to the discovery agent |
| `5d17127` | feat(discover): orchestrator (run.py) + report + shared artifact writer |

## 2. Read these first (in this order)

1. `docs/superpowers/plans/2026-08-04-evalyn-plan3-discover.md` — **the plan you execute.** Task 12
   onward. Global Constraints at the top bind every task.
2. `docs/superpowers/specs/2026-08-04-discover-mode-design.md` — the ratified design (§7 orchestration,
   §10 toy weaknesses, §12 the success bar Task 12 asserts, §14 human-adoption wording Task 13 fixes).
3. `docs/JOURNAL.md` → **Plan #3 section** — task table, what the reviews caught, and the full
   deferred-findings register (source of truth for open items; triage it at the final review).
4. `.superpowers/sdd/2026-08-04-evalyn-plan3-discover/` — the SDD workspace: `progress.md` (the
   recovery ledger — **append, do not restart**), pre-extracted task briefs (`task-12-brief.md`,
   `task-13-brief.md`), per-task controller-rulings files, and implementer reports. The prior handoff
   `2026-08-05-plan3-task8b-kickoff.md` has a still-useful §3 interface inventory for Tasks 0–8a.

## 3. Working agreements (non-negotiable)

- **Models: controller session runs on Fable 5; ALL subagents on Opus 5** — set `model: opus`
  explicitly on **every** dispatch (implementers, fixers AND reviewers). An omitted model silently
  inherits the session's.
- **Execution:** superpowers:subagent-driven-development — one fresh subagent per task, TDD with a
  **discriminating** RED shown first (a bare `ModuleNotFoundError`/`AttributeError` is weak RED — this
  project has required a mutation/inverted-stub demonstration every task; keep that bar). Two-stage
  review (task review → fix rounds capped at 5 → scoped re-review). Hand subagents **files** (briefs,
  rulings, review packages), never pasted history.
- **Write controller rulings to a file before dispatching** a task and point both implementer and
  reviewer at it. This is what made the reviews sharp. Task 12/13 rulings files do not exist yet — you
  write them (`task-12-controller-rulings.md`, `task-13-controller-rulings.md`).
- **Commits happen automatically** under the maintainer identity, no Claude trailer:
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit …`.
  Conventional prefixes. **ASK before every push and before opening/updating any PR.** Stage files
  explicitly — **never `git add .`** (the working tree carries an untracked `.claude/` that must stay
  untracked).
- **`uv` only** — system `python3` is 3.9. Suite must stay green, unmodified and **warning-clean**
  (`uv run pytest -q -W error::RuntimeWarning`); `uv run ruff check src/ tests/`.
- **Checkpoint the ledger AND `docs/JOURNAL.md` at every task completion**, committing the journal
  separately (`docs: Plan #3 journal checkpoint — Task N …`).
- **Never** overwrite `packs/twincore/calibration.json` outside a consented passing calibrate run.
  Never commit `runs/`. The NiuwnAI product repo is READ-ONLY.
- **Worktree gotcha (if you parallelize):** the Agent `isolation: "worktree"` tooling mis-seeded both
  Task 9/11 worktrees at an OLD commit (`1c1836f`, Plan #2a era). Both implementers caught it and
  `git reset --hard` onto the intended base. **If you spin up a worktree, verify its base
  (`git -C <wt> rev-parse HEAD`) before trusting the work**, and never merge into a working tree an
  agent is live in. Tasks 12–13 are naturally sequential, so parallelism is optional here.

## 4. The invariants that govern everything (unchanged)

1. **The agent PROPOSES, the scoring layer DISPOSES.** "Confirmed" ⇔ the candidate probe's required
   checks FAIL against the transcript via the *real* tier-1/tier-3 scorers. **Unsure is never a
   finding.**
2. **Containment is structural.** Closed action enum (`send`/`propose`/`stop`), no URL/file/shell
   tool; `loop.py` imports no httpx/requests/urllib/socket/subprocess and a test guards it. Do not widen.
3. **One definition of the candidate probe** — `emit.candidate_probe`. A second definition is an
   automatic review failure.
4. **Zero spend through Task 13. Task 14 is USER-GATED.**

## 5. Interfaces you now consume (new since the 8b handoff)

- **`discovery/run.py` (Task 8b):** `async run_discovery(pack, cfg) -> DiscoveryArtifact`;
  `DiscoveryArtifact` (fields incl. `findings`, `error_count`, `sessions_total`, live vs reconciled
  spend as separate fields, `partial`/budget flag; `to_dict`/`from_dict`); `Finding(objective_id,
  confirmed, probe_path, replay, duplicate_of, duplicate_reason)`; `ReplaySkipped` (distinct from a
  failed replay); `write_discovery_artifact(artifact, out_dir="runs") -> Path` (atomic,
  `<stamp>-<uuid8>-<slug>-discover.json`); `render_discovery_report(artifact) -> str`. Spend uses
  `max(live, reconciled)`, never the sum. Each replay gets its own `replay-<probe_id>/` log dir.
- **Shared writer (Task 8b, R8-13):** `engine/run.py:atomic_write_artifact(payload, pack_name, out_dir,
  suffix)` — the single atomic artifact writer, called by `run_gate` (suffix `""`),
  `write_compare_artifact` (`-compare`), and `write_discovery_artifact` (`-discover`). Do not add a
  fourth verbatim copy.
- **Family rule (Task 9):** `evalyn.engine.task_builder.family_warnings(pack, *, judge_model,
  rubric_model, discovery_model=None) -> list[str]` and the module constant `REFUSE_PREFIX = "REFUSE: "`.
  An entry is refuse-class iff it `.startswith(REFUSE_PREFIX)`; the CLI turns that into exit 2. Import
  the constant, never hard-code it.
- **CLI (Task 10):** `evalyn discover` in `src/evalyn/cli.py` — §8 flag surface, exit codes `0`
  completed / `2` setup-refuse / `3` all-sessions-errored (findings NEVER fail). Preflight refusals:
  family collision (`--allow-family-collision` overrides), rubric-objective-without-judge (no
  override), tier-3 staleness (`--allow-uncalibrated` overrides), `--max-usd 0` rejected, cap-drop
  notice, id validation. `--dry-run` prints the plan + "NOTE: a real run would REFUSE (exit 2): …"
  lines (computed from the SAME predicates as the real refusals) and makes ZERO model/HTTP calls.
- **Toy weaknesses (Task 11):** `examples/toy_target.py` serves four §10 planted weaknesses **behind
  `TOY_DISCOVERY_WEAKNESSES`, which now defaults ON** (maintainer decision R11-8; CI sets `=0`
  explicitly). Three are deterministic (injection via a ≥2-turn trust-pivot, PII, persona) and
  tier-1-confirmable with NO judge; the fourth (hallucination) is tier-3/judge-graded. Triggers are
  disjoint from every static probe turn (both flag-on and flag-off gate runs match
  `ci/baseline-example.json`, pinned). New pack assets: `packs/example/personas/curious-auditor.md`,
  `packs/example/playbooks/trust-then-pivot.md`, `packs/example/discoveries/.gitkeep`.

## 6. Task 12 — your next task, and its obligations

**Scope:** `tests/discovery/test_e2e_discover.py` (plus any small glue the e2e exposes). Zero-spend.
The plan's Task 12. It asserts the spec §12 success bar — **the flywheel closing end to end**.

- **Step 1 — `test_discover_toy_end_to_end`:** with `TOY_DISCOVERY_WEAKNESSES` ON and a scripted /
  mockllm agent that adaptively hits the **three deterministic** planted bugs, `run_discovery` yields
  **≥1 confirmed finding** and **≥1 emitted probe whose `ReplayResult.reproduced is True`**; the
  emitted probe file loads via `Probe.model_validate`; the run exits 0. Use the deterministic weaknesses
  only (tier-1, no judge) to stay zero-spend — do NOT wire the tier-3 hallucination hunt into this
  test (it needs a paid judge).
- **Step 2 — `test_adopted_probe_reds_gate`:** move a staged probe into `packs/example/probes/`, run
  `gate` → it now **FAILS** (the flywheel closes). **Then remove it and leave the pack clean** — this
  test must leave `git status` clean and `ci/baseline-example.json` untouched (R8-7 hygiene is
  Critical here; prefer a tmp copy of the pack, or guarantee restoration).
- **Step 3:** implement any glue exposed, PASS, full suite + lint green, commit
  `test(discover): end-to-end flywheel acceptance (zero spend)`.

**Binding context to fold into your Task 12 rulings:**
- **Closes T8a→T8b/T12:** 8b already proved a real-scorer confirmation through the orchestrator; Task
  12 proves the FULL `discover → confirmed → emit → replay(reproduced) → adopt → gate-reds` chain.
- **T7→T8 flaky-flag (still open):** `ReplayResult` has no `pass_at_k`/`expected_trials`, so for a
  `samples: 3` safety-critical probe `reproduced=True` can't distinguish "3/3" from "1/3". Spec §7
  asks the caller to flag flaky. Decide in Task 12 whether to surface it or re-defer to final review.
- Keep CI's `TOY_DISCOVERY_WEAKNESSES=0` intact; `discover` is never in the CI blocking path.

## 7. Task 13 — docs/roadmap/version (after 12)

`docs/EVALYN_EXPLAINED.md` (fix "automatically" → confirmed findings become gate tests **after human
review**, per spec §14 — inert staging dir + hand-adopt), `docs/CI_ADOPTION.md` (discover-findings →
human-triage note), `docs/ROADMAP.md` (Plan #3 status ✅ + change-log), `docs/JOURNAL.md` (per-task
entries + register close-out — triage every open item: fix / re-defer with reason / accept),
`pyproject.toml` (version bump, e.g. `v0.4.0`). Commit `docs: Plan #3 discover delivered — …`.

## 8. Task 14 — USER-GATED (do NOT start without fresh consent)

A live TwinCore `discover` pre-run that spends real judge/agent tokens. **Stop and present the cost
estimate first; get explicit maintainer consent before running.** Capture full stdout to a file in the
SDD workspace (`… > file 2>&1`). This is demo material for the AI Tinkerers Bremen event (2026-08-14).

## 9. The deferred-findings register

Every open item, per task, lives in `docs/JOURNAL.md` → Plan #3 → *Open items* and in the ledger.
Notable still-open: T7→T8 flaky-flag (Task 12 call); T10 exit-2-on-mid-run-crash minor; T8b's 3
latent-edge minors (`_reconcile_path` union-glob, live-only skip predicate, serialized derived
`effective_spend_usd`); T11 unbounded `_session_turns`. Triage all at the final whole-branch review.

## 10. Success bar (spec §12) and the deadline

`evalyn discover` on the toy finds **≥1 confirmed** problem (validated by the scoring layer, not
self-asserted) and emits **≥1 reproducible** probe; adopting it **reds `gate`** — the flywheel closes.
The agent structurally cannot leave the allowlist; a budget stop yields a partial report, exit 0. Full
suite green, ruff clean, both packs `validate-pack` exit 0. **AI Tinkerers Bremen demo: 2026-08-14.**
Remaining: Task 12, 13, then the gated 14. If the schedule tightens, the pre-agreed safe cut is
injection + PII live on the toy with hallucination + persona shown from logs — **confirm with the
maintainer before cutting.**

---

## Kickoff prompt for the new session

Paste everything below into a fresh session (stay on `feat/plan3-discover`).

```
Continue executing Evalyn Plan #3 (`discover` mode + flywheel). Tasks 0–11 are DONE; resume at Task 12.
Stay on branch feat/plan3-discover — do NOT cut a new branch.

Read first, in this order:
1. docs/superpowers/handoffs/2026-08-06-plan3-task12-kickoff.md  — full state transfer (start here)
2. docs/superpowers/plans/2026-08-04-evalyn-plan3-discover.md    — the plan you execute (Tasks 12–14)
3. docs/superpowers/specs/2026-08-04-discover-mode-design.md     — the ratified design (§7, §10, §12, §14)
4. docs/JOURNAL.md → Plan #3 section                             — task table + deferred-findings register
5. .superpowers/sdd/2026-08-04-evalyn-plan3-discover/progress.md — the recovery ledger (APPEND, do not restart)

You are the lead engineer and execution controller. Delegate ALL implementation to fresh subagents —
implementers, fixers AND reviewers — via superpowers:subagent-driven-development, with `model: opus`
set explicitly on every dispatch. Controller session stays on Fable 5; subagents on Opus 5. Your job is
orchestration, review and verification, not writing code yourself.

Re-verify before starting and report the numbers: `uv run pytest -q -W error::RuntimeWarning`,
`uv run ruff check src/ tests/`, both packs `validate-pack` exit 0, `git status`. Expected state:
HEAD 8869e99, 694 passed warning-clean, tree clean apart from untracked .claude/, nothing pushed.

Task 12 is the end-to-end flywheel acceptance (tests/discovery/test_e2e_discover.py), zero-spend:
prove discover→confirmed(real scorer)→emit→replay(reproduced)→adopt→gate-reds on the toy's THREE
deterministic weaknesses (weaknesses default ON; do not wire the tier-3 hallucination hunt — it needs a
paid judge). Step 2's adopt-then-gate-reds test MUST leave the pack clean and ci/baseline-example.json
untouched (R8-7 hygiene, Critical). Then Task 13 (docs/version). STOP before Task 14 (USER-GATED live
run) and present the cost estimate for explicit consent first.

Working agreements: write controller rulings to a FILE before each dispatch and point implementer +
reviewer at it. TDD with DISCRIMINATING red (not a bare import error). Commits automatic under the
maintainer identity, no Claude trailer; stage files explicitly, never `git add .` (untracked .claude/
must stay untracked); ASK before every push and any PR. `uv` only; suite stays green + warning-clean.
Checkpoint the ledger AND docs/JOURNAL.md at each task completion. Use skills. Think hard.
```
