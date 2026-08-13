# Plan #4 (`evalyn ui`) — session 9 handoff

**Written 2026-08-12, small hours.** Supersedes `2026-08-11-plan4-session8-handoff.md`, which is
history only.

**The demo is 2026-08-14, a 6pm slot.**

**The wiring pass is DONE and it earned its place.** It found a critical defect (the Cancel button
was a live grenade), and chasing "what will the maintainer actually type on stage?" then found two
more that would each have spoiled the demo — one of which would have **killed the run outright**.
All are fixed. Nothing was billed this session; all 7 pre-approved rehearsal runs are unused.

---

## 0. Read this order

1. **`.superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md`** — the ledger, rulings R4-0 … R4-68.
   **It and `git log` outrank anyone's recollection, including your own.** Its last ~250 lines are
   session 9.
2. This document.
3. **`docs/JOURNAL.md`'s last two sections** — ratified scope/ordering and the registered residual
   race. Committed on purpose; the SDD workspace is gitignored and dies with the plan.
4. `PRODUCT.md` before any scope question. `.impeccable/surfaces/ui-src.md` before any page task —
   **but see §6, it contains a proven falsehood.**
5. `docs/superpowers/plans/2026-08-07-evalyn-plan4-ui.md` — the plan. **Its line-number citations are
   stale throughout.**

---

## 1. Where things stand

| | |
|---|---|
| `feat/plan4-ui` (trunk) | **`c6cf625`**, pushed. Everything below is in it except Trends. |
| `feat/plan4-ui-frontend` (`../Evalyn_frontend_lane`) | **`29d60bd`**, pushed. **Holds Trends — NOT yet merged.** |
| `feat/plan4-ui-engine` (`../Evalyn_engine_lane`) | `048e41a`. Fully merged long ago; now **stale**, reusable only after a merge from trunk. |
| Python suite (trunk) | **1539 passed, 0 skipped**, both colour modes, cold, ruff clean |
| UI suite (frontend lane) | **449 passed / 22 files**, `tsc` exit 0 |
| `runs/` corpus (trunk only, gitignored) | **102 artifacts** |
| Spend | **~$0.276 of ~$1.00. NOTHING billed this session. 7 of 8 rehearsal runs still unused.** |
| Recovery tag | `pre-merge3-20260812` → `dca4282`, local. Delete when you like. |

**Complete:** tasks 0–9, 18–20, 21 (steps 1–3), 22, 23, the **wiring pass**, and **Trends (frontend
half)**.

**Expected working-tree noise — leave both alone:** the maintainer's unstaged edit to
`docs/superpowers/handoffs/2026-08-07-plan4-ui-kickoff.md` (mtime 2026-08-07, verified not ours), and
the quarantined `ci/baseline-twincore-injection.TAINTED-blessed-a-FAIL.json`.

### ⚠️ TWO THINGS ARE UNREVIEWED. REVIEW THEM FIRST.

Everything else this session went through an independent Opus 5 review that **reproduced the
mutation evidence itself** — and in three separate cases the reviewer overturned or corrected the
implementer. These two did not get that, because the session chose to spend its remaining context on
this handoff rather than on rushed reviews:

- **the stage fixes**, trunk `adcb431..c6cf625` (5 commits) — §3
- **Trends**, frontend lane `6ab0641..29d60bd` (7 commits) — §4

Both are green and controller-verified for file set, identity, leakage and suite counts. Neither has
had its mutation evidence reproduced by a second party. **That is the next session's first job.**

---

## 2. What the wiring pass found (all fixed, all reviewed)

Driving a real browser at the real server for the first time, on the **free** `example` pack.

- **T20-d, CRITICAL — the Cancel button was a live grenade.** `build_argv` never passed `--control`,
  so the child never polled the control file. Measured: cancel returned `202 accepted:true`, the child
  **completed all 12 trials**, and **zero `control.*` events** appeared in a 62-event stream. Then the
  orphaned control file made `derive_status` relabel that **completed** run `cancelled`. Fixed both
  ways: the channel is armed, and the artifact now outranks the control file. Proof after the fix:
  cancel produces `control.cancelled` in ~1s with `cancelled: True` and `trials: [0,0,0,0]` —
  R4-13's exact signature.
- **H2** — `run.finished` carries no `exit_code` but the SPA read one, so the banner said
  `⚠ FINISHED … EXIT CODE not reported` while the gate block 40px below said `EXIT CODE 1`. Fixed.
- **F1** — every launch error rendered the literal `(undefined)`. Fixed.
- **F2** — a running run claimed "This artifact records no probe rows". Fixed.
- **The mocks were lying in 16 ways** and that is *why* none of this was caught. Corrected, and the
  corrections are now **pinned by tests**, which they were not at first.
- **18 things verified genuinely working**, including: Task 20's 404 defect does not reproduce;
  `LiveRunPanel` mounted for the first time ever; the 409 busy lock renders sanely; zero console
  messages, zero 5xx.

**H3 is still open and the rehearsal is its test.** Nothing emits `heartbeat` despite
`heartbeat_seconds: 15.0`; the stream is silent until a 120s `: idle-timeout`. The longest gap
actually **measured** was 0.809s because the free run is ~2.1s end to end, so the stall could not be
provoked. A real run lasts minutes. **Measure it during the rehearsal; do not build a heartbeat on
speculation (R4-27).** The same goes for **F4** — intermediate progress rendering has still never
been seen by a human on any pack.

---

## 3. The stage command, and the two defects that only appear when you write it down

**R4-67.** Neither is a bug in any component — every piece worked as written. They exist because
**the cockpit and the CLI drifted apart and only the CLI was ever exercised.** The three measured
runs are CLI runs; the stage run is a cockpit run. Nobody had ever assembled the actual command.

1. **The cockpit could not use a real judge, at all.** No judge option on `evalyn ui`, no env-var
   route anywhere in `src/`, and `build_argv` never passed `--judge-model` — so every cockpit run fell
   to `mockllm/model`. The demo pack has **four `classifier` checks, one `required: true`**
   (`injection.yaml:257`), and `cli.py:175-179` makes those **fail closed / UNSURE** under mockllm.
   **Maintainer chose: add `--judge-model` to `evalyn ui`.** Done.
   *Mitigation that saved the story anyway:* the anchor probe `injection-exfil-boundaries` uses
   `invariant`/`invariant`/`not_contains`/`contains` — **no classifier** — so the central finding is
   judge-independent. Only the board *around* it was contaminated.
2. **A cockpit run silently gated against another pack's baseline** — and it was worse than that.
   `build_argv` omitted `--baseline`, so the child fell to `runs/baseline.json`, which belongs to the
   **`example`** pack (4 probes vs 31). Then, while actually running the command, the implementer
   found that **`runs/baseline.json` predates the Plan #2a schema and does not load at all**. Every
   cockpit gate from the repo root was printing `gate: baseline error` and **exiting 2** after
   writing its artifact.

   **⭐ The two defects were masking each other.** The wiring pass saw `GATE FAILED / EXIT CODE 1`
   rendered from the *artifact*, while the banner said "exit code not reported" — the H2 bug. The
   process's exit 2 was invisible, so nobody noticed the runs were dying. **A cockpit-launched demo
   would have died on stage.**

   Fix: the launcher decides and hands `build_argv` the answer. The CLI default path is passed **only
   if `load_baseline` returns an artifact whose `pack_name` matches this pack**; otherwise the run
   gets a provably-empty path inside its own sidecar dir. Checked `pack_name`, not `pack_hash` — an
   edited probe makes a baseline *stale*, not *foreign*, and the existing staleness warning covers
   that.

3. **Cancel said "accepted" to an already-dead run** (T-A2). `POST …/control` returned 202 against
   nothing alive, while `GET /api/runs` said `running` — and only a *detail* GET reaped as a side
   effect, after which the list said `interrupted` and control returned 409. **The two endpoints
   disagreed until someone happened to open the detail page.** Now the control POST reaps before
   deciding. (An earlier implementer had ruled this out; a re-reviewer proved the objection was
   already overruled one route away — `server.py:712` calls `reap()` from a GET.)

### THE STAGE COMMAND — use exactly this

```bash
set -a; . ./.env; set +a
EVALYN_TWIN_SLUG=dashanka-de-silva EVALYN_TARGET_URL=http://localhost:8000 \
  uv run evalyn ui --port 8765 --no-open --runs-dir runs \
    --target packs/twincore-injection \
    --judge-model anthropic/claude-sonnet-5
```

**The env vars must be on the *server*, not the run** — the launcher passes `{**os.environ, ...}` to
the child, so whatever the server lacks, the run lacks. Omit `--judge-model` and you get the free
mockllm path, which is how to debug the cockpit without spending.

---

## 4. Trends (frontend half) — built, unreviewed, NOT merged

Frontend lane `6ab0641..29d60bd`, 7 commits, **449 passed / 22 files** (+45), `tsc` 0.

- **Recharts `3.10.1` pinned exactly** (no caret), +**37** lockfile entries (d3 tree, redux, etc.).
  **The bundle will grow noticeably at the next build.** 0 vulnerabilities.
- Rendered in a real browser at 1440 and 820 and **found three real defects that way**, each now
  fixed with a test — including a reading on the domain floor drawn half outside the frame, which for
  pass^k at 0.00 is *the common case*.
- **The load-bearing behaviour:** a run a probe never read is **absent** from the row, so the line
  breaks. The 26 degraded `example` runs are gaps, **never zeros**. A mutation filling them with `0`
  reddens a named test. 18 mutations total, each restored by `cp` + `cmp`.
- Selection is by **weight, not hue** (2.5px vs 1px), named in words, keyboard-reachable with
  `aria-pressed`. Opens on the most notable channel with zero clicks — on the injection pack that is
  the anchor probe.

**Its four open items:**

1. **`GET /api/trends` does not exist server-side.** Against a real `evalyn ui` the page shows its
   error branch. **This is the next backend task.** Three things a mock cannot prove are listed in
   `Trends.tsx`'s docstring: that a degraded run is genuinely absent rather than `0`; that `?pack=`
   takes the pack **name**; that a pack with no history answers `200 []` rather than 404.
2. **The pack selector reads `GET /api/packs`** — the launch *allowlist*, not the set of packs with
   history. With the stage command only `twincore-injection` is allowlisted, so only it will offer
   trends. **If you want `example`'s 53 points on screen too, allowlist it with a second `--target`.**
   Needs a decision.
3. **`Detent` was extracted out of `Launch.tsx`**, so the diff touches another task's page. Suite is
   green and the contrast guard caught both halves of the move, but **it deserves a reviewer's eye.**
4. **Compare was not built** — deliberately out of scope for that brief, though the plan pairs them.

---

## 5. Next actions, in order

1. **Review the two unreviewed waves** (§1). Stage fixes first — they are what the demo runs on.
2. **Merge Trends into the trunk**, then **REBUILD THE BUNDLE**. See §7 — this is the step that
   decides whether any frontend work is visible at all.
3. **Build `GET /api/trends`** (backend half), then **wiring-check Trends against the real route.**
4. **The rehearsal run** — now finally meaningful, with the judge flag. It is the natural test for
   **H3** (heartbeat/stall), **F4** (progress rendering), and the **control buttons driven by mouse**,
   none of which any test can settle. Take a screenshot of the finished banner for the maintainer.
5. **Judge Trust → Discoveries → Compare.** If road runs out, it runs out on Compare.

**Parallelisation model (R4-68), and why it works:** Task 1 froze all 34 wire models and Task 5 built
the complete MSW fixture+handler layer for all five endpoints, so **every remaining page already has
its model, TS type, fixture and mock — only the middle is missing.** The frontend of a page can
therefore be built and tested against mocks without its route existing. Stream A = trunk (Python:
routes, aggregation, rehearsal, no merges). Stream B = frontend lane (`ui/**` only).
**Named risk: building against mocks is exactly the setup that produced the 16 divergences. A wiring
check against the real route is a REQUIRED gate before any page counts as done.**

---

## 6. Constraints that bite (corrected — older docs are stale)

- **The frozen TS wire model is `ui/src/api/types.ts`** (45 types), **NOT `ui/src/types.ts`** — that
  path in older handoffs is wrong. The six frozen copies: `src/evalyn/ui/models.py`;
  `EXPECTED_STRUCTURE` and `RUN_ID_TYPED_FIELDS` in `tests/ui/test_models.py`; `ui/src/api/types.ts`;
  and two guards that parse `models.py` **as source text** and assert field **order** —
  `ui/src/api/__tests__/types.test.ts` and `ui/src/api/__tests__/models-drift.test.ts`. **No docstring
  line may begin with four spaces then an identifier and a colon**, or it parses as a phantom field.
- **⚠️ `.impeccable/surfaces/ui-src.md:139` contains a proven falsehood** — it claims Recharts was
  "pinned exactly by Task 5". **Task 5 never installed it.** It is pinned now, by Trends. Treat that
  document as checkable, not authoritative.
- **There is a SEPARATE optionality guard** at `models-drift.test.ts:227`
  (`ApiError: no optional key…`). Field-order guards tolerate `\??` and pass; optionality is checked
  independently. **That guard's own rationale is false** — it says "FastAPI serialises defaults, so
  nothing is absent", but `redact.py:705` uses `exclude_none=True`. Parked, handed to the final review.
- **R4-11 — cancel is NEVER built on signals**, in code, docstring, comment, test name or message —
  **not even in prose.** ⚠️ **The repo's own guard only scans `engine/control.py` source and permits
  retraction prose, so it will NOT catch a slip elsewhere.** An implementer caught its own slip this
  session; the suite did not.
- **R4-12** — pause means "start no new samples"; in-flight samples finish and keep spending.
- **R4-13** — a cancelled run's probes reduce to `trials=0` and `RunArtifact.cancelled` makes it exit 3.
- **R4-27** — max two reviews per task: review → one fix round → one re-review → park the rest. A fix
  may not build new infrastructure.
- **R4-45** — concurrent agents are fine, governed by **file-set disjointness**. Two implementers must
  never share a worktree.
- **R4-62** — **a merge with zero conflicts proves nothing.** Prove containment, per-file identity,
  scope, and reconcile the union count. Push every branch *before* merging.
- **R4-6** — counts are derived invariants, never literals.
- Tailwind scans `ui/src/**/*.{ts,tsx}` and **does not strip comments** — a utility class named in
  prose ships a dead CSS rule.
- The contrast guard reasons per file and is blind to `inset`/`safety` families and to
  `border-*`/`decoration-*`/`[--rule:…]`. Hand-measure ink on dark grounds and record the ratio.
- Never `fastapi.testclient`; never `warnings.catch_warnings(record=True)`; `CliRunner` comes from
  `tests/cli_runner.py`. Keep the `evalyn.ui.index` import lazy.
- macOS has no `timeout` — `perl -e 'alarm N; exec @ARGV'`. Some SSE tests HANG rather than fail.

---

## 7. Commands

```bash
uv sync --extra ui
find . -name __pycache__ -not -path "*/node_modules/*" -exec rm -rf {} +   # before claiming clean
uv run pytest -q -W error::RuntimeWarning
FORCE_COLOR=1 uv run pytest -q -W error::RuntimeWarning     # CI forces colour; verify BOTH
uv run ruff check src/ tests/
cd ui && npm run test -- --run && npx tsc --noEmit

# free cockpit — the whole wire at $0 (judge defaults to mockllm)
uv run python examples/toy_target.py &                       # serves 127.0.0.1:8899
uv run evalyn ui --port 8765 --no-open --runs-dir runs --target packs/example
```

**⚠️ REBUILDING THE BUNDLE — do not skip after any `ui/` change:**

```bash
cd ui && npm run build        # writes ../src/evalyn/ui/static, emptyOutDir wipes stale hashes
```
`evalyn ui` serves the **committed** bundle. Without a rebuild the server keeps serving the old SPA
and any browser check verifies nothing. **Prove the rebuild took** — check `index.html` points at the
new hash, the old asset is gone, and a string you changed is present. Note `grep -c` counts *lines*,
useless on minified JS; use `grep -o … | wc -l`, and mind the case.

---

## 8. Git-safety block for every dispatch

Forbid in every form: `git clean`, `push`/`merge`/`rebase`/`pull`/`fetch`,
`checkout <branch>`/`switch`, `worktree`/`branch -d`/`reset --hard`/`reset <commit>`/`stash`,
`git checkout -- <file>`, and `git add .`. Path-scoped `git reset HEAD <path>` is fine. Require
`git rev-parse --show-toplevel` and `--abbrev-ref HEAD` before every commit, and "stop and report"
rather than self-repair. **`git checkout -- <file>` has silently reverted uncommitted work in this
plan** — restore from an explicit `cp` backup and `cmp` it. **Backup names must be unique, lowercase
and agent-prefixed**: the scratchpad is shared and the filesystem is case-insensitive.

Commit as `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com'
commit …`, **no Claude trailer**, staged explicitly by path.
**Pushes are pre-authorised; merges and PRs need an ask.**

---

## 9. Deferred findings register

**None blocks the demo.**

**New this session:** the phantom `running` row for a dead-but-unreaped child (read path has no
evidence to decide with; only the control surface was fixed) · a completed `compare`/`discover` run
with a stale cancel file still relabels, now **pinned by a test deliberately written to go red when
an engine-side `cancelled` field lands** · the `models-drift` optionality guard's false rationale
(above) · `judge_usd` meters `0.013875` for a `mockllm` run (known pre-existing metering bug) ·
`IconQuery` now serves three states · `.impeccable/surfaces/ui-src.md:139` still false.

**Carried from Tasks 19/20:** `--update-baseline --force-baseline` on a cancelled run exits 0 · one
bare `warnings.catch_warnings()` · the inert `ack_timeout` · a secret **split across two SSE records**
goes out in halves (inherent to per-record redaction, pre-existing) · the registered residual race ·
`_run_is_live` reaches into the private `RunIndex._sidecar` · pack-id digest length unpinned ·
`POST /api/runs` unnamed in `WRITE_ROUTES` · a dead `cwd=` parameter · a permanent-`running` ghost if
the launching server dies · `/stderr` read whole into memory.

**⚠️ Discoveries renders findings from a live product, including a PII-leak finding.** The redaction
chokepoint covers it **by luck, not design**: `build_redactor` harvests literals only from
`load_pack(pack).probes`, and `load_pack` never reads `<pack>/discoveries/`, so a staged value that is
a **name, id or hostname** rather than an email would reach the browser unredacted. **And the test
that should catch this cannot — it uses an email sentinel, so it passes either way.** Strengthen that
sentinel to a non-pattern value and wire the discoveries harvest **before** building that page, and
**look at the page on a screen before it goes near a projector.**

---

## 10. The demo, and the numbers you may state

The maintainer runs the eval **live on stage, launched from the cockpit's Launch button**. The
recorded RED (`~/Desktop/evalyn-k7-RED-2026-08-11.mov`) is cued as fallback (R4-47).

**The finding is an output-conformance failure, NOT an exfiltration.** The words "leak" and
"exfiltration" are **banned** for this probe (R4-35). The product is supposed to stay on script, and
the standard lives in the maintainer's pack, not in Evalyn.

| | |
|---|---|
| Board RED | **3 of 3 runs** |
| `injection-exfil-boundaries` RED | **3 of 3** — the anchor; build the demo on it |
| Anchor probe's trials across 3 runs | **21** |
| …that revealed the file | **0** |
| …that used non-approved wording | **3 — exactly one per run, never the same trial twice** |
| `invariant_failures` | **0**, every trial, every run |

**⚠️ A P(green board) figure of ~12% in older notes is RETRACTED.** The trustworthy number is
empirical: **3 of 3 runs came up red.** **The deviating epoch moves every run — never script the
stage click-path to a fixed epoch.**

**The banner glyph is SETTLED: keep the defaults.** The maintainer chose this. It has now been wrong
in two directions — an alarm on every finished run, then a check that read as "passed" — and the
question mark under-claims without ever contradicting the red `✗ GATE FAILED` below it. A genuinely
neutral mark would be better but **nothing in the icon family can supply one** (the only valence-free
marks are 40×16 and mean "dead channel"). Draw it after the demo, not before.

---

## 11. Method lessons this session earned

- **⭐ ASK WHAT THE HUMAN WILL ACTUALLY TYPE.** Three demo-breaking defects — including one that would
  have killed the run — were invisible to every test, every review and a full browser wiring pass.
  They appeared the moment someone wrote out the stage command and asked whether each flag was right.
  **A component can be perfect and the composition still broken.**
- **⭐ TWO DEFECTS CAN MASK EACH OTHER.** The runs were exiting 2 on a baseline error, and the exit
  code was invisible *because of a separate bug in the banner*. Neither was findable while the other
  stood.
- **⭐ THE CONTROLLER'S OWN LEDGER ENTRIES ARE CLAIMS TO VERIFY.** I recorded an implementer's story
  that three tests "contradicted their own names" and floated it as a lying artefact. A reviewer went
  to git and disproved it — they were *vacuous*, not contradictory, and I had repeated the claim
  without reading the preamble under the header. The correction is in the ledger, not edited away.
- **⭐ VERIFY YOUR OWN VERIFICATION.** My first bundle check grepped lowercase, case-sensitively, and
  reported a failed rebuild that had actually succeeded. `grep -c` counts lines, not occurrences.
- **A proof reasoned about rather than executed is not evidence** — but reading *found* the critical
  defect in minutes; only execution established that it bites. **Neither step was sufficient alone.**
- **Reviewers must reproduce, not read.** Three times this session a reviewer overturned an
  implementer: proving `detail?:` unsafe against the controller's own hypothesis, catching an
  "other ten passing proves it" **non-sequitur** and running the decisive mutation instead, and
  finding a narrow fix an implementer had wrongly ruled out.
- **Decline to fix, with reasons, beats a patch that lies.** The best answer this session was an
  implementer refusing to relabel a phantom `running` row, because `start_new_session=True` means the
  child outlives its parent and `running` may simply be *true*.
- **Read a mutation proof BY TEST NAME, never by pass/fail count.** Still the highest-yield rule.
- **After any edit, re-run the FULL suite, not the file you touched.**
- **Render the UI and look.** Trends found three real defects that way after its tests were green.
- **Comments that lie are first-class defects — nine so far**, one introduced *by the commit whose
  purpose was to stop a docstring overclaiming.**

---

## 12. Kickoff prompt for the next session

```
We're continuing Plan #4 — the `evalyn ui` cockpit. Demo is 2026-08-14 (AI Tinkerers Bremen), 6pm.
Work in the trunk: /Users/dashankadesilva/Drive/Projects/Evalyn_eval_agent, branch feat/plan4-ui at
c6cf625, pushed. Trends lives UNMERGED in ../Evalyn_frontend_lane at 29d60bd, also pushed.
../Evalyn_engine_lane is stale — don't use it without merging trunk into it first.

Read first, in this order:
1. docs/superpowers/handoffs/2026-08-12-plan4-session9-handoff.md — START HERE.
2. .superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md — the ledger, rulings R4-0 … R4-68. It
   and `git log` outrank anyone's recollection, including your own.
3. docs/JOURNAL.md's last two sections.
4. PRODUCT.md before any scope question. .impeccable/surfaces/ui-src.md before any page task — but
   line 139 of it is a PROVEN FALSEHOOD, so treat it as checkable, not authoritative.

State: 1539 Python (0 skipped) / 449 UI (22 files), ruff and tsc clean, warning-clean both colour
modes cold. 102 artifacts in runs/. Nothing was billed last session — all 7 pre-approved rehearsal
runs are unused. ui/node_modules present in BOTH the trunk and the frontend lane.

Your job, in this order:
1. REVIEW THE TWO UNREVIEWED WAVES — stage fixes (trunk adcb431..c6cf625) and Trends (frontend lane
   6ab0641..29d60bd). Everything else last session was reviewed by an Opus 5 agent that reproduced
   the mutation evidence itself, and it overturned the implementer three times. These two didn't get
   that. Stage fixes first — they are what the demo runs on.
2. Merge Trends into the trunk, then REBUILD THE BUNDLE (`cd ui && npm run build`) and prove the
   rebuild took. Without it the server serves the old SPA and any browser check verifies nothing.
3. Build `GET /api/trends` (the backend half), then wiring-check Trends against the REAL route.
4. The rehearsal gate run, with --judge-model. It is the only test for the heartbeat/stall question,
   for intermediate progress rendering, and for the control buttons driven by mouse. Screenshot the
   finished banner for me.
5. Judge Trust → Discoveries → Compare. If we run out of road, we run out on Compare.

The stage command is now:
  set -a; . ./.env; set +a
  EVALYN_TWIN_SLUG=dashanka-de-silva EVALYN_TARGET_URL=http://localhost:8000 \
    uv run evalyn ui --port 8765 --no-open --runs-dir runs \
      --target packs/twincore-injection --judge-model anthropic/claude-sonnet-5
The env vars must be on the SERVER — the launcher passes its own environment to the child.

Before building Discoveries: its redaction is covered by LUCK, not design, and the test that should
catch that uses an email sentinel so it passes either way. Fix both before that page exists, and look
at the page on a screen before it goes near a projector.

The demo's central finding is measured and is NOT an exfiltration: three safety-critical probes fail
pass^k because the twin improvises its own good refusal instead of the approved copy. Across three
paid runs, 21 attempts on the anchor probe revealed the file ZERO times. Never say "leak" or
"exfiltration". The ~12% P(green board) figure in older notes is RETRACTED — 3 of 3 runs came up red.
The banner glyph is SETTLED: keep the defaults.

Working agreements: `uv` only; suite green and warning-clean in BOTH colour modes with __pycache__
DELETED; ALL subagents on Opus 5, set explicitly on every dispatch including reviews and fix rounds;
TDD with a DISCRIMINATING red; reviewers must REPRODUCE mutation evidence rather than trust it, and
must READ IT BY TEST NAME, NEVER BY PASS/FAIL COUNT; after any edit re-run the FULL suite, not the
file you touched; every dispatch names its absolute worktree path, its exact file globs, and the
git-safety block in §8; snapshot every worktree before dispatching a reviewer and diff it after;
backup names unique and lowercase; stage explicitly, never `git add .`; commits under my identity
with no Claude trailer. Pushes are pre-authorised — ASK before any merge or PR. Use impeccable for
UI work. Tell every implementer to commit each coherent piece as it finishes, and every reviewer to
restore after EVERY mutation and write its report incrementally.

Use superpowers:subagent-driven-development. Parallelise where file sets are disjoint — the frontend
of a page can be built against the existing mocks without its route existing, because Task 1 froze
all 34 models and Task 5 built the full MSW layer. But a wiring check against the REAL route is a
REQUIRED gate before any page counts as done: building against mocks is exactly what produced the 16
divergences we found last session.

Think hard, be careful, check on your subagents with evidence, and ask me questions.
```
