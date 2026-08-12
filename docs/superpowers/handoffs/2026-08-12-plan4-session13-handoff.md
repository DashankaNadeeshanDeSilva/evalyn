# Plan #4 (`evalyn ui`) — session 13 handoff

**Written 2026-08-12, evening.** Supersedes `2026-08-12-plan4-session12-handoff.md`, which is
history only.

**The demo is 2026-08-14, a 6pm slot.**

**What this session reached: EVERY COCKPIT PAGE NOW SHIPS.** Discoveries and Compare were reviewed,
fixed, merged and rebuilt into the served bundle; the `mockllm` metering bug is fixed and visible on
screen; and **pause and cancel have been driven by a mouse for the first time in this plan.**

---

## 0. KICKOFF PROMPT FOR THE NEXT SESSION

> We're continuing Plan #4 — the `evalyn ui` cockpit. Demo is 2026-08-14 (AI Tinkerers Bremen), 6pm.
> Trunk: `/Users/dashankadesilva/Drive/Projects/Evalyn_eval_agent`, branch `feat/plan4-ui` at
> `5d48986`, pushed. **All three lanes are merged — `../Evalyn_frontend_lane`,
> `../Evalyn_compare_lane` and `../Evalyn_budget_lane` are spent. `../Evalyn_engine_lane` is stale.
> Do not use any of them without merging trunk in first.**
>
> Read first, in this order:
> 1. `docs/superpowers/handoffs/2026-08-12-plan4-session13-handoff.md` — START HERE.
> 2. `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md` — the ledger, rulings R4-0 … R4-107
>    plus BACKLOG-1. It and `git log` outrank anyone's recollection, including your own. The ledger
>    is gitignored and untracked by deliberate ruling (R4-88) — do NOT `git add -f` it.
> 3. `docs/JOURNAL.md`'s last section.
> 4. `PRODUCT.md` before any scope question — **but measure the corpus, never quote its counts**
>    (R4-6); it was last edited 2026-08-10 and its "zero compare artifacts" line is now stale.
>
> **The plan is feature-complete for the demo.** Your job, in this order:
> 1. **Rehearse the demo end to end**, including §10's REQUIRED PORT CHECK. That check is not
>    optional bookkeeping — see R4-104.
> 2. **BACKLOG-1** (§6): a cancelled run renders a gate verdict it did not earn. Maintainer ruled
>    2026-08-12: documented, deferred, do it **if there is time**.
> 3. **Optional and droppable** (§6): the bundle-staleness guard.
> 4. Anything in §9 the maintainer wants pulled forward.
>
> Working agreements: `uv` only; suite green and warning-clean in BOTH colour modes with
> `__pycache__` DELETED; ALL subagents on Opus 5, set explicitly on every dispatch including reviews
> and fix rounds; USE SUBAGENTS FOR ALL DEV AND ALL REVIEWS — the controller writes no code, **except
> that the maintainer ruled browser verification is the controller's to do directly**; TDD with a
> DISCRIMINATING red; reviewers must REPRODUCE mutation evidence rather than trust it, and must READ
> IT BY TEST NAME, NEVER BY PASS/FAIL COUNT; after any edit re-run the FULL suite; every dispatch
> names its absolute worktree path, its exact file globs, and the git-safety block in §11; snapshot
> every worktree before dispatching a reviewer and diff it after; backup names unique and lowercase;
> stage explicitly, never `git add .`; commits under my identity with no Claude trailer. Pushes are
> pre-authorised — ASK before any merge or PR. Use `impeccable` for UI work. Tell every implementer
> to commit each coherent piece as it finishes, and every reviewer to restore after EVERY mutation
> and write its report incrementally.
>
> **Tell every agent to flag anything in its brief it finds to be false.** That instruction caught
> something in **every single dispatch** of session 13 — including two controller claims that were
> flatly wrong and one that would have destroyed working guards if followed literally. It is
> load-bearing infrastructure, not politeness.
>
> **AND CALIBRATE EVERY INSTRUMENT BEFORE TRUSTING ITS READING.** Sessions 12 and 13 caught: a
> mutation harness scoring perfectly while measuring nothing; a browser whose resize drifted 270px; a
> self-reported contrast figure that was wrong; a name-extractor reporting the literal string
> `FAILED` as a test name; and a bundle probe that would have read 0 after a perfect build. **Controls
> that must stay GREEN, exact-width iframes, figures computed from hex, and a harness that refuses to
> report when its own edit did not land.**
>
> Use `superpowers:subagent-driven-development`. Parallelise where worktrees are disjoint. A wiring
> check against the REAL route is a REQUIRED gate before any page counts as done.
>
> Think hard, be careful, check on your subagents with evidence, and ask me questions.

---

## 1. Where things stand

| | |
|---|---|
| `feat/plan4-ui` (trunk) | **`5d48986`**, pushed. All three lanes merged. |
| Python suite | **1613 passed, 0 skipped** — both colour modes, cold `__pycache__`, ruff clean |
| UI suite | **615 passed / 29 files**, `tsc` exit 0 |
| Served bundle | **REBUILT AND PROVEN** at `5d48986` — `index-DP63OzAO.js`. Discoveries and Compare are in it. |
| Pages shipped | Runs · Launch · **Discoveries** · **Compare** · Trends · Judge Trust — **nav has no unshipped destination left** |
| `runs/` corpus | 106 `.json`; **1 `*-compare.json`** (new this session, $0.00). Counts are DERIVED invariants, never literals (R4-6). |
| Spend | **~$1.72 total. $0.00 this session.** |

**Expected working-tree noise — leave all three alone:** two modified files under
`docs/superpowers/handoffs/` and the untracked `ci/baseline-twincore-injection.TAINTED-blessed-a-FAIL.json`.

**Merge trail:** `8abc71e` (mockllm) → `d2e3068` (Discoveries) → `386c279` (Compare) → `5d48986` (bundle).

---

## 2. ⚠️ THE THINGS TO INTERNALISE BEFORE YOU START

**1. A TOY TARGET CAN SILENTLY SHADOW THE REAL TWIN ON PORT 8000 (R4-104).** `docker ps` shows
`niuwnai-mvp-api-1  0.0.0.0:8000->8000/tcp` — **the real twin is on port 8000, exactly where the
stage command points.** A process bound to `127.0.0.1:8000` (IPv4) shadows Docker's `*:8000` for
localhost connections. This actually happened for ~10 minutes this session. **Had it survived to
Saturday, the demo would have evaluated a toy stub instead of the product, every probe result would
have been fiction, and the run would have looked completely normal on screen.** No allowlist catches
it — the URL is right; the *listener* is wrong. **Run §10's port check before the demo.**

**2. NEVER KILL BY PORT (R4-105).** The controller ran `kill $(lsof -iTCP:8000 -t)` and the PID list
included the maintainer's Docker backend. It survived, but that was luck. Kill only PIDs you started,
matched by full command line. `pkill -f "foo(8000)"` silently matches nothing — unescaped regex parens.

**3. `npm run build` WRITES INTO A TRACKED PATH (R4-96/R4-98).** `src/evalyn/ui/static/` is tracked
and `evalyn ui` serves it. Only the controller builds; agents are forbidden. **Never restore the
bundle — rebuild it.** Restoring is how you commit a bundle that matches no source.

**4. THE CONTROLLER'S OWN CLAIMS ARE CLAIMS TO VERIFY.** Every dispatch this session caught
something. See §8.

---

## 3. What shipped

### `mockllm` price fall-through — `8abc71e`
`price_for("mockllm/model")` matched no `PRICES` key and fell through to the opus-tier unknown-model
bound, so the free local stub was metered at $0.015/$0.075 per 1k on *synthesised* usage, and the
phantom cost counted against `budget.max_usd_per_run`. Keyed on `"mockllm"`, **not**
`"mockllm/model"` — a second variant `mockllm/agent-brain` would otherwise have kept billing.

**The finding that mattered:** two real regression guards used *"mockllm gets billed the opus
default"* as their proof that the usage plumbing works. Zeroing the price would have made a genuine
`0.0` indistinguishable from the 2026-07-28 bug's `0.0`. Each now restores the opus price for that
test only — and **the reviewer reintroduced the original bug at its true sites (`run.py:363`,
`meter.py:157`) and watched both go RED by name**, proving they still test plumbing, not arithmetic.

**Verified on screen:** `JUDGE USD $0.0000 of $1.0000 pack ceiling · 0.0% used`.

### Discoveries — `d2e3068`
Backend `6051153` + fixes `4ab6479`/`ae367e9`; frontend `8b129b4` + fixes `92d6e5f`…`22622f5`.

**R4-89 executed: the `X-Evalyn-Reveal` promise is DELETED, not built.** The wire model, the TS types
and the MSW mock all promised a reveal token; the real route takes no `Request` and no `Header`.
`RedactionMeta.reveal_required` stays `true` because it is true.

**Two defects a green suite could not see, both found by reading rendered words:**
- **The replay region contradicted itself** — *"the replay reproduced this finding"* and *"this
  finding's replay did not run"*, in the same view, **inside the very test written to prove that copy
  honest**. Fixed in the page.
- **The size readout could print "2 safety-critical"** against a fixture where every figure was `1`.
  The sibling model test in the same commit had already broken that tie; the page test hadn't.

**Redaction re-proven post-merge against the real corpus: `grep -c` for the maintainer's address
returns 0 on `/api/discoveries`, `?objective=pii-leak`, and `/api/runs?mode=compare`.**

### Compare — `386c279`
Frontend-only: `_scoreboard()` → `RunDetail.compare` → `GET /api/runs/{id}` already existed.
**There is no `/api/compare` route on the real server and never was**, though `handlers.ts:438`,
`models.py` and `types.ts` all documented one.

**Which side is which was pinned by nothing** — five independent A/B transpositions shipped green,
and a "strict" `toEqual` could not discriminate three tally fields that all read `1`. **No
transposition was actually present**; every identity assertion passed against the unmodified page.
*The defect was that nothing could have told us.*

**The half-empty board is a first-class state.** `packs/twincore-injection` has zero rubric checks and
`compare.py:116` skips rubric-less probes, so the pairwise half is legitimately empty:

> *"No rubric-checked probes were judged, so this comparison has no pairwise verdicts. Compare judges
> only probes that carry a rubric check. The hard metrics below come from the trial records and are
> unaffected."*

### The first compare artifact — R4-94, **$0.0000**
`runs/20260812T164746520652-9ec23a3d-twincore-injection-compare.json`, from two existing
`twincore-injection` gate runs. **`evalyn compare` makes no target HTTP calls** — it re-judges two
gate artifacts. Real numbers on the board: latency mean **2.81s / 2.27s**, p95 **13.11s / 10.24s**,
invariant failures **0 / 0**, 217/217 trials.

---

## 4. Pause and cancel — DRIVEN BY A MOUSE (R4-106)

Free, on `packs/example` with a **scratch runs dir**, port 8000 never involved.

**Method note worth reusing:** 12 trials against the local toy target finish in ~2s and 217 in ~4s —
far too fast to click anything. A **scratchpad-only latency proxy** (8899 → 8901, 8s delay) stood in
for the twin's network latency. No repo file changed.

- Pause label: **"PAUSE (FINISHES IN-FLIGHT TRIALS)"** — the honesty PRODUCT.md demands.
- Pause pending: *"…Pausing starts no new samples. Trials already in flight finish, and keep
  spending."* Server confirmed `status: "paused"` + control sidecar.
- **Cancel has a two-step interlock** with an escape hatch (KEEP RUNNING / CANCEL RUN) and copy that
  names both the continued spend **and** that "the artifact is still written".
- Cancel confirmed: `status: "cancelled"`, `cancelled: true`, `judge_usd 0.0`.

**⚠️ R4-13 AS WRITTEN DID NOT REPRODUCE.** "A cancelled run's probes reduce to `trials=0` and it
exits 3" is **false under this timing**: measured `trials/probe = [3]` on all four probes, and the
artifact has **no `exit_code` key at all**. Explanation, consistent with the product's own copy: all
12 trials were already in flight, and in-flight trials finish by design. **R4-13 can only describe a
cancel that lands before trials start. Restate it.**

---

## 5. Deferred findings register

**None blocks the demo.**

**New this session:** BACKLOG-1 (§6) · the Compare "judged twice, in both orders" legend renders
*above* the sentence saying it never ran · `line-clamp-1` escapes the new Discoveries clip guard
(a four-string blocklist where a regex is needed) · at 375px on a multi-category compare board,
**column B clips before `B − A`** (single-category boards clip `B − A` first; body never scrolls
sideways either way) · `FindingRow.duplicate_reason` is free text, so "no `FindingRow` field holds the
captured email" is true in practice but not structurally guaranteed · `source_a`/`source_b` come back
**verbatim with `redacted:false`** for relative CLI paths — harmless for our artifact, but do not
claim those fields are redacted · 21 dead `filterwarnings("ignore:no price entry")` decorators across
4 files (proven to mask nothing by flipping all 21 to `error:` → 94 passed) · the two `judge_usd > 0`
guards should assert on **token counts**, not cost, which needs artifacts to expose token totals.

**Stale docs, not repaired:** `PRODUCT.md:101` still says there are zero compare artifacts (R4-94
superseded it) and its `~80 indexable runs` figure is stale — measured 106 `.json` today. The Launch
page's *"this console has no picker for them yet — launch a compare from the CLI"* is **still true**:
the Compare page is a viewer, not a launcher.

**Carried:** the phantom `running` row for a dead-but-unreaped child · a completed `compare`/`discover`
run with a stale cancel file still relabels · the `models-drift` optionality guard's false rationale ·
the registered residual control-endpoint race · `_run_is_live` reaching into private `RunIndex._sidecar`
· `POST /api/runs` unnamed in `WRITE_ROUTES` · a permanent-`running` ghost if the launching server dies
· `/stderr` read whole into memory · the unguarded pass-line band · `types.test.ts`'s vacuous heartbeat
guard · `TrendChart.tsx:567`'s `"N other probes"` · the discoveries cursor is run-granular and may
overshoot `limit` · `is_no_redact` scanned over `app.routes` proves nothing (lazy `_IncludedRouter`) ·
`useRevealOnOpen`'s smooth-scroll path is unobserved.

---

## 6. The two queued items

### BACKLOG-1 — a cancelled run renders a gate verdict it did not earn
**MAINTAINER-RULED 2026-08-12: documented, deferred, do it if there is time.**

Today a cancelled run shows, in one viewport:

```
STATUS  ⊘ CANCELLED        RUN OUTCOME  not reported     ← correct
              ✗ GATE FAILED    EXIT CODE 1               ← the problem
```

**Measured, not inferred:** `GET /api/runs/{id}` returns `exit_code: null` and the artifact has no
`exit_code` key. The `1` is on no wire field — it is derived client-side from a gate verdict computed
over only the probes that finished before the cancel landed.

**The fix, in the maintainer's framing:** on a cancelled run, do **not** show a gate verdict at all —
say the run was stopped and the verdict is unknown.

**Acceptance:** a cancelled run shows no PASS/FAIL and no exit code. Guard it with a **discriminating**
test — a cancelled fixture whose finished probes *would* fail the gate, so a test that merely renders
"cancelled" cannot pass while the verdict block is still there.

**Not demo-blocking** — reachable only by cancelling mid-run.
**RUNBOOK CONSEQUENCE UNTIL THEN: do not cancel a run on stage.**
**Do not confuse this with pause. Pause is correct and verified.**

### Optional and droppable — the bundle-staleness guard
A ~20-line test asserting every `shipped: true` nav destination has a page-unique `data-testid`
present in `static/assets/*.js`. Would have caught all four historical drifts. **Maintainer approved
it as a final task only if there is time, and it is to be dropped before pause/cancel work is.**

---

## 7. Constraints that bite

- **The frozen TS wire model is `ui/src/api/types.ts`.** The enforced guard is a THREE-WAY TRIANGLE at
  `ui/src/api/__tests__/models-drift.test.ts` — `models.py ←→ frozen literal ←→ types.ts`, with
  `types.ts` read as SOURCE TEXT and field ORDER asserted.
- **No docstring line in `models.py` may begin with four spaces then an identifier and a colon** — it
  parses as a phantom field. The count under `^ {4}[a-z_][a-z0-9_]*: ` is **203**. Check before and
  after any `models.py` edit. Better still, **execute the models** and read `model_fields`.
- **Model layers are TOP-LEVEL**: `ui/src/discoveries.ts`, `ui/src/trends.ts`, `ui/src/trust.ts`,
  `ui/src/compare.ts` — *not* under `api/`.
- **`client.ts` exports THREE hooks**: `useMeta`, `useRuns`, `useRunDetail`. There is no
  `useDiscoveries` and no `useCompare`.
- **`vite.config.ts:51` hard-codes the dev proxy to 8765.** A dev-server wiring check must use 8765.
- Tailwind scans `ui/src/**/*.{ts,tsx}` and **does not strip comments** — a utility class named in
  prose ships a dead CSS rule.
- The contrast guard is **blind to `inset`/`safety` families and to `border-*` and `[--rule:…]`**.
  Compute ratios from hex yourself. Established, confirmed three times independently, on `#fafbfc`:
  **16.37 / 8.70 / 5.98 / 4.03 / 2.30 / 1.55**. (2.30 is correct; 2.42 was wrong.)
- **`**/discoveries/*.yaml` is gitignored** (`.gitignore:38`) — the two real findings do not exist in
  CI or a fresh clone. Every test builds its own pack under `tmp_path`.
- **Counts are worktree-dependent (R4-93).** 1613 is the collected count; a fresh worktree without the
  gitignored `runs/` corpus skips 8 UI tests. Portable invariant: "collected count, 0 failed".
  **`-W error::RuntimeWarning` is a CLI flag only** — `pyproject.toml` has no `filterwarnings` key.
- Never `fastapi.testclient`; never `warnings.catch_warnings(record=True)`; `CliRunner` from
  `tests/cli_runner.py`. Keep the `evalyn.ui.index` import lazy in *server* code.
- macOS has no `timeout` — `perl -e 'alarm N; exec @ARGV'`. Some SSE tests HANG rather than fail.
- **R4-11** cancel is never built on signals. **R4-27** max two reviews per task; a fix may not build
  new infrastructure. **R4-45** concurrency is governed by file-set disjointness. **R4-62** a
  zero-conflict merge proves nothing. **R4-6** counts are derived invariants, never literals.

---

## 8. Method lessons this session earned

- **⭐ THE FLAG-FALSEHOODS INSTRUCTION PAID OFF IN EVERY SINGLE DISPATCH.** Among what it caught: my
  "ten lines below" was **297 lines wrong**; my cost model repeated the $0.62 mistake in a new shape
  (`schema.py:136` defaults a paid rubric model for *every* pack — `packs/example` is free because it
  has **zero rubric checks**, not because of its judge config); my file globs were incomplete twice;
  and **one instruction of mine, followed literally, would have deleted two working guards** ("confirm
  no `X-Evalyn-Reveal` string survives under `ui/`" — three survive and all three are correct,
  including the guard that must *name* the header to assert its absence).
- **⭐ A DELETION RULING HAS A BLAST RADIUS.** Enumerate every site that *asserts or describes* the
  deleted thing, not just the site that *defines* it. R4-89's edit list was 1 of 4.
- **⭐ A FIXTURE WHOSE NUMBERS COINCIDE CANNOT TELL YOU WHICH NUMBER WAS READ.** Caught twice, in two
  different pages, in two different shapes — `total=2/confirmed=1/safetyCritical=1` and
  `wins_a:1, ties:1, flips:1`. **A `toEqual` over coinciding values is not strictness.** The
  seventeenth vacuous guard in this plan.
- **⭐ A TEST THAT PINS COPY CAN CONSTRUCT A STATE THE PRODUCT CANNOT BE IN**, and then certify prose
  that is false about every real row. Check fixtures against a **real artifact's field values**, not
  only against the type.
- **⭐ VERIFY THE FIX DIDN'T HOLLOW OUT THE GUARD.** Don't settle for "deleting the fix reddens the
  test" — **reintroduce the original bug** and confirm it still reddens. That is the difference
  between a guard that survived a fix and one the fix quietly disarmed.
- **⭐ "ABSENT FROM MY WORKTREE" IS NOT "UNSOURCED".** An agent swept `src/`, `tests/`, `ci/`, never
  searched `docs/`, and generalised "I didn't find it" into "it isn't there". Its own phrase for the
  failure: **"inference dressed as measurement."**
- **⭐ CALIBRATE THE INSTRUMENT, INCLUDING THE ONE YOU JUST INVENTED.** The bundle-rebuild probe was
  going to be the literal `git mv` — which would have read **0 after a perfect build**, because all
  three occurrences are comments and minification strips them. Caught before use by proving the
  probe *class* survives minification first. Best harness pattern seen: **refuse to report at all
  unless the mutation changed the file's md5.**

---

## 9. The demo, and the numbers you may state

The maintainer runs the eval **live on stage from the cockpit's Launch button** — rehearsed session 11.
The recorded RED (`~/Desktop/evalyn-k7-RED-2026-08-11.mov`) is cued as fallback (R4-47).

**The finding is an output-conformance failure, NOT an exfiltration.** The words "leak" and
"exfiltration" are **banned** for this probe (R4-35).

| | |
|---|---|
| Anchor probe failed `pass^k` | **7 of 8 runs** · **5 of 5 at 7 trials** |
| P(green board on stage) | **~1 in 5** |
| `invariant_failures` | **0**, every trial, every run |
| Trials that revealed the file | **0** |
| A full demo run | **217 trials · ~2.5–3.5 min · `$0.0513`–`$0.0628`** |

**THE DEMO PACK HAS ZERO TIER-3 CHECKS, AND THE FAILING CHECK IS DETERMINISTIC. No LLM decided the
headline finding** — a strength worth claiming out loud.

**"One probe, two packs, same deterministic failure."** `injection-exfil-boundaries` failed identically
in both `twincore` runs. **Do NOT claim both demo probes converge** — `injection-multiturn-trust-pivot`
passes under a real judge.

**SAY THE JUDGE'S WEAKNESS BEFORE THE AUDIENCE DOES.** `packs/twincore`'s weakest criterion is
**`persona:Tone under refusal` at 82% (9/11)**. The headline finding rests on a deterministic check,
so the judge's weak spot does not undermine it.

**New and available:** the Compare board shows the newer run is **faster on both mean and p95**, with
**0 invariant failures on both sides** — measured, at $0.00.

**The banner glyph is SETTLED: keep the defaults.**

---

## 10. Commands, and the REQUIRED pre-demo port check

```bash
uv sync --extra ui
find . -name __pycache__ -not -path "*/node_modules/*" -exec rm -rf {} +   # before claiming clean
uv run pytest -q -W error::RuntimeWarning
FORCE_COLOR=1 uv run pytest -q -W error::RuntimeWarning     # CI forces colour; verify BOTH
uv run ruff check src/ tests/
cd ui && npm install && npm run test -- --run && npx tsc --noEmit
```

### ⚠️ RUN THIS BEFORE THE DEMO — R4-104

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN     # MUST show ONLY com.docker.backend — no stray python
docker ps --format '{{.Names}}\t{{.Ports}}' | grep 8000    # expect niuwnai-mvp-api-1
curl -s -X POST http://localhost:8000/api/twin/dashanka-de-silva/consent \
  -H 'content-type: application/json' -d '{"consent": true}'
# MUST return a real session_token. Verified 2026-08-12: {"session_token":"…","gdpr_consent":true}
```

**A toy target bound to `127.0.0.1:8000` shadows Docker's `*:8000` and the run looks completely
normal while evaluating a stub.**

### The stage command (proven end to end; env vars must be on the SERVER)

```bash
set -a; . ./.env; set +a
EVALYN_TWIN_SLUG=dashanka-de-silva EVALYN_TARGET_URL=http://localhost:8000 \
  uv run evalyn ui --port 8765 --no-open --runs-dir runs \
    --target packs/twincore-injection \
    --target packs/example \
    --target packs/twincore \
    --judge-model anthropic/claude-sonnet-5
```

**The stage click path, rehearsed:** Launch → click `twincore-injection` → type `twincore-injection`
in CONFIRM → LAUNCH RUN. **Selecting a pack clears the confirm field** and grows the CONFIRM prompt to
two lines, shifting the input down ~20px — **click the field AFTER selecting the pack.** Confirmed
again this session: the input moves from y=641 to y=664.

**DO NOT CANCEL A RUN ON STAGE** until BACKLOG-1 is fixed (§6).

### Rebuilding the bundle — R4-98

```bash
cd ui && npm run build        # writes ../src/evalyn/ui/static, emptyOutDir wipes stale hashes
```

`evalyn ui` serves the **committed** bundle, and `npm run build` dirties a **tracked** path — the
result must be **committed**, as its own `chore:` commit. **Never restore the bundle; rebuild it.**
**Prove the rebuild took** with page-unique `data-testid` values (proven to survive minification),
plus the new hash in `index.html` and the old asset filename *gone*. **`grep -c` counts LINES —
useless on minified JS. Use `grep -o … | wc -l`.** A CSS hash that does not move is not a failed
build. **Do not use a string that appears only in comments — minification strips them.**

---

## 11. Git-safety block for every dispatch

Forbid in every form: `git clean`, `push`/`merge`/`rebase`/`pull`/`fetch`,
`checkout <branch>`/`switch`, `worktree`/`branch -d`/`reset --hard`/`reset <commit>`/`stash`,
`git checkout -- <file>`, and `git add .`. Path-scoped `git reset HEAD <path>` is fine. Require
`git rev-parse --show-toplevel` and `--abbrev-ref HEAD` before every commit, and "stop and report"
rather than self-repair. **`git checkout -- <file>` has silently reverted uncommitted work in this
plan** — restore from an explicit `cp` backup and `cmp` it. **Backup names must be unique, lowercase
and agent-prefixed.**

Commit as `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com'
commit …`, **no Claude trailer**, staged explicitly by path.
**Pushes are pre-authorised; merges and PRs need an ask.**

**Snapshot every worktree before dispatching a reviewer and diff it after** — HEAD, tree, stash count
and porcelain.

**⚠️ THE LEDGER STAYS OUT OF THE REPO — R4-88, a deliberate maintainer decision.** The repo is public
and the ledger is candid internal process notes. It is content-safe (zero emails, zero secrets), so
this is a disclosure judgement, not a security one. **DO NOT `git add -f` IT. DO NOT un-ignore
`.superpowers/`.** A same-laptop backup exists; the maintainer was told it does not survive laptop
loss and **explicitly accepted local-only. Do not re-raise it.**

**Merge convention:** a real merge commit with a `merge: <prose>` subject — `--no-ff`, never a
fast-forward or a squash. Before any merge: snapshot, `comm -12` the two changed-file sets for
overlap, and `git merge-tree --write-tree` as a read-only trial. **Then verify with a falsifiable
prediction of the test count** — R4-62 means the clean merge itself proved nothing.
