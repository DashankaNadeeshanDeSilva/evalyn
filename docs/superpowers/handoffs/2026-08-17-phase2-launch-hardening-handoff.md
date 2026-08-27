# Phase 2 — launch-failure hardening: session handoff

**Written 2026-08-17.** Entry point for the next session. Phase 1 (the Plan #4 final whole-branch
review) is finished and in review as PR #11; Phase 2 is a **new session on a new branch**, by the
maintainer's ruling of 2026-08-17 — the approved plan file says "same branch" and is superseded on
that point only.

---

## 0. KICKOFF PROMPT FOR THE NEXT SESSION

> We are doing **Phase 2 of the post-demo consolidation plan: launch-failure hardening**. Work on a
> new branch **`fix/launch-failure-hardening`** cut from `dev`.
>
> Read, in this order:
> 1. `docs/superpowers/handoffs/2026-08-17-phase2-launch-hardening-handoff.md` — this file, the
>    entry point. §2 contains a correction to the plan's root-cause hypothesis that you must not
>    skip: **the leading theory in the plan file is very likely wrong**, and I have the evidence.
> 2. `~/.claude/plans/thnaks-to-your-hard-snoopy-twilight.md` §"Phase 2" — the approved scope.
> 3. `docs/2026-08-14-DEMO-RUNBOOK.md` §1–§2 — the stage commands that failed.
>
> The mission, in one line: **at the demo the cockpit came up with no pack to launch, wrote nothing
> to disk, and gave the operator no way to tell why. Make that failure impossible to have silently.**
>
> Do the work in this order, and do not skip step 1:
> 1. **Reproduce read-only first.** Characterise what actually happens for each of the three
>    candidate causes in §2. Show me real terminal output before you change any code. A fix built on
>    the wrong cause is worse than no fix.
> 2. **Then harden**, per §3 — resolve `--target` to absolute paths and echo them; make the
>    zero-pack server state explain itself instead of rendering an empty list; and close the
>    port-shadow hole for **8765**, not just 8000.
> 3. **Then update the runbook** (§4) with absolute paths and the failure mode.
>
> Constraints are in §5 and they have all drawn blood before — read them. Verification standard is
> in §6: evidence, not assertions, and the repro must be demonstrated BEFORE the fix and the loud
> refusal AFTER it.
>
> Commit automatically under the user's name with no Co-Authored-By trailer. **Ask before every
> push and before opening the PR.** Use subagents (Opus 5, set `model` explicitly) for anything
> that needs heavy reading. Think hard and reason deeply.

---

## 1. Where things stand

| | |
|---|---|
| Released | **v0.5.0**, tag `3fdf85a`, all three modes + the 7-page cockpit |
| `dev` | `1d1616b` before Phase 1; **PR #11 merges into it** |
| Phase 0 | DONE 2026-08-16 — worktrees pruned, TAINTED baseline deleted, branches cleaned |
| Phase 1 | DONE 2026-08-16/17 — PR #11, 7 commits, CI green, under review |
| **Phase 2** | **this handoff — not started** |
| Phase 3 | docs sweep + JOURNAL entries, docs-only, direct on `dev`. Blocked on Phase 1 merging |
| Phase 4 | the user-gated live TwinCore baseline run (~$0.06) |

**Phase 1's triage table** (50 items, the four rulings, all the evidence) is published at
<https://claude.ai/code/artifact/07dc53af-22ef-43e4-8e47-1c23918f8d8e>. Phase 3 transcribes it into
`docs/JOURNAL.md`. Do not redo that work.

---

## 2. ⚠️ THE ROOT-CAUSE HYPOTHESIS IN THE PLAN IS PROBABLY WRONG

The plan file says the demo failure was the **wrong working directory**: the runbook starts
`evalyn ui` with relative `--target packs/...` paths, so from the wrong cwd the packs are not found
and the UI refuses the launch, writing nothing to disk.

**I tested that on 2026-08-17 and it does not produce the observed symptom.**

```
$ uv run python -c "from evalyn.targets.loader import load_pack; \
    load_pack(__import__('pathlib').Path('packs/does-not-exist'))"
PackError :: no target.yaml in packs/does-not-exist
```

A `--target` that does not exist raises `PackError` out of `build_redactor`
(`src/evalyn/ui/server.py:243`), which propagates to `cli.py:945-951`, which prints
`evalyn ui: setup error: ...` and **exits 2**. The server never starts. A wrong cwd is therefore
already loud — you would have got a dead terminal, not a live cockpit.

The observed symptom was **a cockpit that was up, with nothing to launch**. That shape has a
different and exactly-matching cause:

```
$ uv run python -c "from pathlib import Path; from evalyn.ui.server import create_app; \
    print(create_app(Path('runs'), [], allow_discover=False).state.packs_by_id)"
{}
```

**Zero `--target` flags is not an error.** `cli.py:944` passes `packs=[Path(t) for t in target or []]`,
so no flags means an empty list, the server starts happily, and the Launch page has nothing to
offer. Nothing is written to disk because nothing was ever launched.

### The three candidate causes, in my order of likelihood

**(a) A stale cockpit process was holding port 8765.** This is my leading theory and it is
*documented*: on 2026-08-13, after v0.5.0 shipped, the running cockpit was observed still reporting
**v0.4.0** — a process from an earlier session that was never restarted. If that process was still
bound to 8765 when the runbook command ran, the new server fails to bind, the operator's browser
reaches the **old** cockpit, and that old process was started with different (or no) `--target`
flags. Every observed symptom follows: cockpit up, no packs, zero disk trace, and a version number
nobody looked at. **The runbook's port-shadow warning covers only port 8000 (the twin). It says
nothing about 8765.** That is the hole.

**(b) The `--target` flags never reached the process** — the multi-line runbook command was
copy-pasted partially, or a line continuation was lost. Same end state.

**(c) The wrong-cwd theory after all**, if some path resolved to a directory that *exists* but is
not a pack, or if the failure was `AllowlistError` rather than `PackError`. Lower likelihood given
the above, but characterise it rather than assume.

**Your first job is to tell these apart, read-only, with real output.** Do not fix (a) by killing
processes on a port — **ruling R4-105: never kill processes by port**; the twin's own runbook note
explains why (that `lsof` list has included Docker).

---

## 3. What to build

Ordered by how much of the failure each one closes.

**1. Make the zero-pack server explain itself.** Today `app.state.packs_by_id == {}` is
indistinguishable, from the browser, from a server that is simply still loading. Two surfaces:
- The **Launch page's** empty state must say *why* — "this server was started with no launchable
  packs; restart it with `--target <pack>`" — not render an empty list.
- The **server**, at startup, must echo the packs it resolved, so the operator's terminal shows
  what the cockpit will offer before anyone opens a browser.

**2. Resolve every `--target` to an absolute path at startup and echo the resolved path.** The
relative path in the runbook is a real trap even though it is not *this* bug: the echo turns
"which packs did this cockpit load, and from where" into a question the terminal has already
answered. Decide whether an absolute-path echo belongs behind a flag or is always on — always on is
my recommendation; it is one line of output at startup.

**3. Close the 8765 port-shadow hole.** This is the one that would actually have saved the demo.
Options to weigh (this is a design call worth thinking about, not an obvious fix):
- Refuse to start if the port is already bound, with a message naming the port and saying what to
  check — better than uvicorn's raw `address already in use`.
- Have the cockpit's own `/api/health` version be surfaced somewhere the operator sees during the
  runbook's pre-flight, so a stale process announces itself. `/api/health` already carries the
  version and `AppShell` already displays it — the pre-flight step just never checks it.
- Add a pre-flight step to the runbook that curls `127.0.0.1:8765/api/health` and compares the
  version to `evalyn --version`.

**4. Consider whether "no packs" should be fatal at all.** A cockpit with no packs can still browse
`runs/`, which is a legitimate read-only use. So do **not** make it a hard refusal by reflex —
argue the case either way and record the decision. My inclination: not fatal, but loud.

---

## 4. Docs to update

`docs/2026-08-14-DEMO-RUNBOOK.md` — §2's launch block gets absolute paths, and §1's port-shadow
check gets an 8765 arm beside the existing 8000 one. Note the failure mode in words, so the next
operator recognises it. (If a successor runbook is written for a future demo, update that instead.)

---

## 5. Constraints that have drawn blood

- **`uv` only.** System `python3` is 3.9 and too old for Inspect. Always `uv run`.
- **Never `fastapi.testclient`.** The suite has its own in-process pattern; follow it.
- **macOS has no `timeout`.** Do not write it into a test or a script.
- **R4-105: never kill processes by port.** The `lsof -t` list has included Docker.
- **R4-18 / `server.py:236-243`: a pack that will not load is FATAL and must stay fatal.** The
  reason is not tidiness — `build_redactor` harvests each pack's `not_contains` literals into the
  redactor, so starting without a pack that loaded means serving with a redaction hole. Do not
  "improve" this into a warning.
- **The frozen TS wire contract is a three-way drift triangle**: `src/evalyn/ui/models.py` ↔
  `ui/src/api/types.ts` ↔ `ui/src/mocks/handlers.ts`. Change all three together or none. Enforced by
  `ui/src/api/__tests__/models-drift.test.ts`, which reads `types.ts` as source text and asserts
  field ORDER.
- **If ANY `ui/src` file changes, rebuild the served bundle** (`cd ui && npm run build`, output to
  `src/evalyn/ui/static/`) and re-verify `ui/src/__tests__/bundle-freshness.test.ts`. Source→bundle
  drift has bitten four times. **R4-98: only the controller runs the build; the bundle is rebuilt,
  never restored; the rebuild lands as its own `chore:` commit.**
- **The minifier delimits strings with backticks.** A guard searching for `"some-testid"` reads zero
  against a perfectly fresh bundle. Match `"`, `'` and `` ` ``.
- **A mock that is a superset of the server is a trap** (R4-91 / mutation M9). A page written
  against a route only MSW serves is green in vitest and dead in `evalyn ui`. Phase 1 deleted one
  such phantom route; do not add another.
- **`.superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md` stays gitignored.** Read it for
  context; never `git add -f` it, and keep its candid notes out of the public repo.

---

## 6. Verification standard

- **Show the repro before the fix and the loud refusal after it.** Evidence, not assertions — this
  is the whole point of Phase 2, and a fix whose failure mode was never reproduced is a guess.
- Python: `find . -name __pycache__ -exec rm -rf {} +` then `uv run pytest -q` and
  `uv run ruff check src/ tests/`, **in both colour modes** (a `SyntaxWarning` is emitted at compile
  time only, so a warm cache hides it and CI forces colour).
- Frontend: `cd ui && npm run test -- --run && npx tsc --noEmit && npm run build`.
- Baselines **as of PR #11's head**: **1623** Python tests, **631** UI tests, ruff clean, `tsc`
  exit 0. If PR #11 gained review fixes before merging, re-baseline from `dev` rather than trusting
  these numbers.
- Every new test must be **discriminating**: it fails if the fix is reverted, and where possible
  sits beside a control that proves it is not vacuous. A zero proves nothing until the probe can
  return non-zero.

---

## 7. Commands

```bash
# the practice target (no spend) — serves 127.0.0.1:8899
uv run python examples/toy_target.py
# point the engine at a target
EVALYN_TARGET_URL=http://127.0.0.1:8899 uv run evalyn gate --target packs/example

# the cockpit
uv run evalyn ui --port 8765 --no-open --runs-dir runs --target packs/example

# health (this is the check the runbook is missing)
curl -s 127.0.0.1:8765/api/health
```

`discover` launches from the cockpit additionally require the server flag `--allow-discover`; it
spends real money and stays user-gated.

---

## 8. What NOT to do in this session

- **Do not start Phase 3 or Phase 4.** Phase 3 is docs-only and commits directly on `dev`; Phase 4
  is a live billed run that needs the user's approval at run time and has an unresolved product
  question in front of it (the `injection-exfil-boundaries` anchor probe fails `pass^k` on *output
  conformance*, so a fresh run will likely FAIL again and `--update-baseline` correctly refuses to
  bless a FAIL).
- **Do not re-derive Phase 1's findings.** Three in particular are settled and written down: the
  control-race remedy proposed in the JOURNAL is unimplementable; Plan #3 register row 16 describes
  a validation hole that does not exist; and `R4-88` is a citation to a ruling that was never
  issued.
- **Do not re-litigate the deferred register.** Every open item has a written reason now.
