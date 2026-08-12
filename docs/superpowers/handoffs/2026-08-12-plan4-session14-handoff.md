# Plan #4 (`evalyn ui`) — session 14 handoff

**Written 2026-08-12, night.** Supersedes the session-13 handoff, which is history only.

**The demo is 2026-08-14, 6pm. The cockpit is feature-complete, rehearsed end to end, and shipped.**

---

## 0. IF YOU ONLY READ ONE THING

**`docs/2026-08-14-DEMO-RUNBOOK.md` is the stage document.** One scannable page, detail below a hard
break. Its numbers were measured on 2026-08-12 from the artifacts; every earlier doc's demo figures
are stale. Do not re-derive them from the session-13 handoff.

**There is no queued work.** Both items from session 13 are done and merged. What remains is
optional, listed in §4, and none of it is needed for Saturday.

---

## 1. State

| | |
|---|---|
| `feat/plan4-ui` | **`94ca41a`**, pushed |
| Python | **1613 passed**, both colour modes, cold `__pycache__`, ruff clean |
| UI | **629 passed / 30 files**, `tsc` exit 0 |
| Served bundle | **`index-Bgn9_ppq.js`**, rebuilt and proven at `364eb17` |
| Spend | **$0.0665** this session (one live run) |

**Expected working-tree noise, leave it alone:** two modified files under `docs/superpowers/handoffs/`
and the untracked `ci/baseline-twincore-injection.TAINTED-blessed-a-FAIL.json`.

**Spent worktrees — merged, do not reuse without merging trunk in first:** `../Evalyn_backlog1_lane`,
`../Evalyn_guard_lane`, plus session 13's `../Evalyn_frontend_lane`, `../Evalyn_compare_lane`,
`../Evalyn_budget_lane`. `../Evalyn_engine_lane` is stale.

**Merge trail:** `4959142` (bundle guard) → `b7d26ee` (BACKLOG-1) → `364eb17` (bundle rebuild) →
`94ca41a` (docs).

---

## 2. What shipped this session

**The rehearsal.** Port check green, cockpit up on the stage command, launched from the Launch
button, 217 trials, ~3 min, board came up **red**. Every page walked against the real route.
Run `20260812T181257886997-52a5b176-twincore-injection`, $0.0665.

**BACKLOG-1 — a stopped run no longer claims a verdict it did not earn.** It was wider than recorded:
the runs list said `GATE FAILED` too, off the real `verdict_hint` wire field, because
`verdict_hint_of` counts un-run probes as INCOMPLETE. Fixed on both surfaces, **frontend-only by
maintainer ruling** — `src/evalyn/**` deliberately untouched. Verified in a browser against a real
cancelled run: the detail page reads **⊘ NO VERDICT** with no pass/fail, no exit code and no status
colour; the list row reads `stopped`; **every other gate row still reads `GATE FAILED`**.

**The bundle-staleness guard** — `ui/src/__tests__/bundle-freshness.test.ts`, driven off
`shippedDestinations()`, asserts each shipped page's marker is still in the committed bundle.

---

## 3. The things worth carrying forward

**1. THIS MINIFIER USES BACKTICKS.** A guard searching for `"some-testid"` reads **zero for every
page against a perfectly fresh bundle**. Written naively, the freshness guard would have reported the
whole cockpit missing. Match the value delimited by any of `"`, `'`, `` ` ``.

**2. `.get(k)` RETURNING `None` IS NOT EVIDENCE OF A NULL FIELD.** It cannot distinguish an absent key
from a null value. That is exactly how R4-107's "measured, not inferred" claim — that
`GET /api/runs/{id}` returns `exit_code: null` — was wrong. `RunDetail` has no such field. Use
`k in obj`.

**3. ONLY THREE RUNS RECORD CHECK-LEVEL DETAIL.** The six before 2026-08-11 14:26 record transcripts
but zero checks. Any corpus-wide claim about checks reads mostly absent data. `invariant_failures` is
different — present in all 1497 trial records and non-zero in none.

**4. A ZERO PROVES NOTHING UNTIL THE PROBE CAN RETURN NON-ZERO.** `curl /api/discoveries | grep -c
<address>` returns 0 because that payload carries no check values at all. The real proof is the
detail route with the raw file as control: 2 occurrences on disk, 0 served, two `«redacted:email»`
markers in exactly those positions.

**5. A DELETION OR REORDERING HAS A BLAST RADIUS.** The BACKLOG-1 fix's first attempt reintroduced
the same overclaim through the door it opened, by putting the stopped check above the mode check.

**6. VERIFY EVERY MERGE WITH A PREDICTION STATED BEFORE RUNNING IT** (R4-62). Both merges this
session were predicted exactly — 622, then 629.

---

## 4. Deferred — nothing blocks the demo

**Backend pass, after Saturday, as one job:** `verdict_hint_of` should emit `null` for a cancelled run
rather than `failed` (type-legal today — `models.py:541` is already `VerdictHint | None`); and
`GET /api/runs/{id}/report` serves `**FAIL** — N failure(s)` for a cancelled run with the false
parenthetical "(all trials errored?)". **No cockpit surface consumes `/report`** — measured, the only
handler is the MSW mock — so it is CLI/API only.

**Cheap hardening:** `RunsPage.tsx` carries no `data-testid` of its own, so the freshness guard's
`/runs` marker lives in `RunsTable.tsx`. Give `RunsPage` its own and repoint the map.

**Also carried:** `"not yet"` is optimistic on terminal states; the control-file-derived `cancelled`
label still reaches the STATUS chip for compare/discover; `index.py:280`'s docstring says `run.py:431`
where it means `engine/run.py:431`; plus the full carried register in the ledger's session-13 entry.

---

## 5. Constraints unchanged from session 13

The frozen TS wire model and its three-way drift triangle; `models.py` docstring indentation (203
phantom-field lines); model layers are TOP-LEVEL (`ui/src/compare.ts`, not under `api/`); `client.ts`
exports exactly three hooks; `vite.config.ts:51` hard-codes the dev proxy to 8765; Tailwind does not
strip comments; the contrast guard's blind spots and the `#fafbfc` ladder
(16.37 / 8.70 / 5.98 / 4.03 / 2.30 / 1.55); `**/discoveries/*.yaml` is gitignored; counts are derived
invariants (R4-6); never `fastapi.testclient`; macOS has no `timeout`.

**The ledger `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md` stays out of the repo (R4-88).**
Do not `git add -f` it. Backup refreshed to `~/Desktop/evalyn-ledger-backup-2026-08-12.md`.
