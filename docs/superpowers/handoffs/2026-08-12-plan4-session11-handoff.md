# Plan #4 (`evalyn ui`) — session 11 handoff

**Written 2026-08-12, afternoon.** Supersedes `2026-08-12-plan4-session10-handoff.md`, which is
history only.

**The demo is 2026-08-14, a 6pm slot. ~48 hours from this line.**

**What this session reached: the trends-route fix wave is closed, Judge Trust is BUILT (route +
page) and WIRING-CHECKED IN A BROWSER, and — the milestone — THE PAID REHEARSAL RAN AND THE COCKPIT
DROVE A REAL BILLED RUN END TO END.** 217 trials, `$0.0513`, board RED, every predicted number
confirmed. A human clicking during that rehearsal found a defect no test could have.

---

## 0. KICKOFF PROMPT FOR THE NEXT SESSION

> We're continuing Plan #4 — the `evalyn ui` cockpit. Demo is 2026-08-14 (AI Tinkerers Bremen), 6pm.
> Trunk: `/Users/dashankadesilva/Drive/Projects/Evalyn_eval_agent`, branch `feat/plan4-ui` at
> `e3dd8d7`, pushed. The frontend lane `../Evalyn_frontend_lane` (`d12d346`) is FULLY MERGED and free
> for `ui/**` work. `../Evalyn_engine_lane` is stale — don't use it without merging trunk into it first.
>
> Read first, in this order:
> 1. `docs/superpowers/handoffs/2026-08-12-plan4-session11-handoff.md` — START HERE.
> 2. `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md` — the ledger, rulings R4-0 … R4-85. It
>    and `git log` outrank anyone's recollection, including your own.
> 3. `docs/JOURNAL.md`'s last section.
> 4. `PRODUCT.md` before any scope question.
>
> State: 1583 Python (0 skipped) / 510 UI (25 files), ruff and tsc clean, warning-clean both colour
> modes cold. Bundle rebuilt and PROVEN at `e3dd8d7`. 100 artifacts in `runs/`. Spend ~$0.33 of ~$1.00;
> 6 of 7 pre-approved runs unused. A merged worktree may need `npm install`.
>
> Your job, in this order:
> 1. **THE TWO `packs/twincore` RUNS, BACK TO BACK** (§3). Step 1 free on the mock judge, step 2 billed
>    with `--judge-model`. The maintainer has ruled on cost — do NOT re-raise it. Report time, spend
>    and outputs for both.
> 2. **Discoveries** (R4-71, curated — read §9's redaction warning BEFORE building).
> 3. **Compare.** If we run out of road, we run out on Compare.
> 4. Pause/cancel by mouse, free, on `packs/example` (§5).
>
> Working agreements: `uv` only; suite green and warning-clean in BOTH colour modes with `__pycache__`
> DELETED; ALL subagents on Opus 5, set explicitly on every dispatch including reviews and fix rounds;
> USE SUBAGENTS FOR ALL DEV AND ALL REVIEWS — the controller writes no code; TDD with a DISCRIMINATING
> red; reviewers must REPRODUCE mutation evidence rather than trust it, and must READ IT BY TEST NAME,
> NEVER BY PASS/FAIL COUNT; after any edit re-run the FULL suite; every dispatch names its absolute
> worktree path, its exact file globs, and the git-safety block in §11; snapshot every worktree before
> dispatching a reviewer and diff it after; backup names unique and lowercase; stage explicitly, never
> `git add .`; commits under my identity with no Claude trailer. Pushes are pre-authorised — ASK before
> any merge or PR. Use `impeccable` for UI work. Tell every implementer to commit each coherent piece
> as it finishes, and every reviewer to restore after EVERY mutation and write its report incrementally.
>
> **Tell every agent to flag anything in its brief it finds to be false.** Four controller-propagated
> falsehoods have now been caught downstream, one of them from a truncated `[:6]` in the controller's
> own probe. That instruction is load-bearing infrastructure, not politeness.
>
> Use `superpowers:subagent-driven-development`. Parallelise where worktrees are disjoint. A wiring
> check against the REAL route is a REQUIRED gate before any page counts as done.
>
> Think hard, be careful, check on your subagents with evidence, and ask me questions.

---

## 1. Where things stand

| | |
|---|---|
| `feat/plan4-ui` (trunk) | **`e3dd8d7`**, pushed. **Holds everything.** |
| `feat/plan4-ui-frontend` (lane) | `d12d346`, pushed, **fully merged**. Reusable for `ui/**` work. |
| `feat/plan4-ui-engine` | `048e41a` — **stale**, only usable after merging trunk into it. |
| Python suite | **1583 passed, 0 skipped**, both colour modes, cold, ruff clean |
| UI suite | **510 passed / 25 files**, `tsc` exit 0 |
| Served bundle | **rebuilt and proven** at `e3dd8d7` (`index-DfDEZSXK.js`) |
| `runs/` corpus (gitignored) | 100 artifacts · **8** for `twincore-injection` · 1 gate for `twincore` |
| Spend | **~$0.33 of ~$1.00. $0.0513 billed this session. 6 of 7 rehearsal runs unused.** |
| Recovery tags | `pre-merge5-20260812` → `eaf8faa`, `pre-merge6-20260812` → `1ee709a` |

**Expected working-tree noise — leave all three alone:** two modified files under
`docs/superpowers/handoffs/` and the quarantined `ci/baseline-twincore-injection.TAINTED-blessed-a-FAIL.json`.

### What shipped this session

- **The trends-route fix wave closed** — all 7 findings, plus the caption, the Launch clear-on-switch
  test, and `ui-src.md`. Reviewed once, one fix round, done under R4-27.
- **R4-80: the trends page speaks "channel", all six user-visible places** — the run-level
  `judge_usd` series is no longer called a probe anywhere.
- **`GET /api/trust` built** (`79840d4`) and **the Judge Trust page built** (`d12d346`), merged
  (`4745b37`), bundle rebuilt (`e3dd8d7`), **and wiring-checked in a browser against the real route.**
- **THE PAID REHEARSAL RAN** (R4-81). See §2.
- **The off-screen trial panel fixed** (R4-83) — found by the maintainer clicking.

---

## 2. ⚠️ THE THREE THINGS TO INTERNALISE BEFORE YOU START

**1. A GREEN BOARD ON STAGE IS ROUGHLY A 1-IN-5 EVENT. The "3 of 3 red" claim was stale and its
retraction of the ~12% green figure was itself premature.** Measured over all 8 `twincore-injection`
artifacts: the anchor probe failed `pass^k` in **7 of 8** runs; at 7 trials (the demo setting) it is
**5 of 5**. **One genuinely green run exists** — it ran only THREE trials, which is the mechanism, not
a contradiction. Per-trial deviation from the only two runs carrying per-trial check data is **3 of 14
≈ 21%**, so P(all 7 clean) ≈ 19%. **Keep the recorded RED (R4-47) cued and script the talk so a GREEN
board is still a good outcome.**

**2. RENDER THE UI AND LET A HUMAN CLICK IT.** The maintainer clicked `ALL` on the failing probe and
said "nothing happened". The panel had opened **565px below the row**, off-screen, silently. **No test
could ever have caught it — the content was in the DOM, so every assertion passed.** It sat on the
demo's click path. Fourth session running, same lesson.

**3. THE CONTROLLER'S OWN CLAIMS ARE CLAIMS TO VERIFY — INCLUDING ITS INSTRUMENTS.** The controller
told an implementer that `per_rubric_agreement` was not a verbatim key in `calibration.json`. **It is
the seventh key.** The controller's earlier probe printed `list(d.keys())[:6]`, truncating exactly
that key, and the brief was then written from the truncated output. Separately, a first per-trial
deviation figure (7.3%) was wrong because the detector scored "no check data recorded" as "no
deviation" — caught only because it contradicted `pass^k`. **When two of your own numbers disagree,
the instrument is wrong, not the world. Never write a brief from truncated output.**

---

## 3. NEXT SESSION'S FIRST JOB — the two `packs/twincore` runs, back to back

**MAINTAINER-REQUESTED. Run step 1, then step 2, and report time, spend and outputs for both.**

Rubric (tier-3, LLM-judged) checks have **never** been exercised through the cockpit. `twincore` is
the only pack that has them: **50 probes, 21 classifier + 14 rubric checks, 4 rubrics on disk**
(`completeness`, `groundedness`, `honesty`, `persona` — exactly the 4 in `calibration.json`).

**Step 1 — FREE. Omit `--judge-model`** so the run stays on `mockllm`. Answers: does the cockpit
handle a 50-probe rubric pack at all, how long the target side takes, what rubric-scored probe rows
look like in the run table, and whether anything breaks. **$0.**

**Step 2 — BILLED, with `--judge-model anthropic/claude-sonnet-5`.** Answers cost and real judge
outputs.

**COST, HONESTLY: unknown and wide.** The one existing `twincore` gate artifact has `judge_usd = 0.0`
(mock judge), so it prices nothing. Scaling from `twincore-injection` (4 classifier checks → 32 LLM
calls → `$0.0513`), `twincore` has ~105 LLM calls at 3 epochs of which 14 per epoch are *rubric* calls
carrying full rubric text plus `steps.json`. **Estimated $0.40 – $1.50, which straddles the remaining
budget.**

**⚠️ `packs/twincore/target.yaml` sets `max_usd_per_run: 5.00` — five times the whole budget — and
`BudgetExceeded` is raised AFTER the artifact is written, so the cap does not stop spend mid-run.**

**THE MAINTAINER HAS RULED: "don't worry about the cost." DO NOT RE-RAISE IT.** The cap stays at
`5.00` (lowering it could abort a run mid-flight and waste it). Report actual spend as soon as it
lands.

---

## 4. Then, in order

1. **The two `twincore` runs** (§3).
2. **Discoveries** (R4-71) — **read §9's redaction warning before building.**
3. **Compare.** If road runs out, it runs out on Compare.
4. **Pause/cancel by mouse** (§5) — free, and still unexercised.

---

## 5. Small queued items

- **PAUSE AND CANCEL HAVE NEVER BEEN DRIVEN BY A MOUSE.** Deliberately not risked during the paid
  rehearsal. **Do it for $0 on `packs/example` with the mock judge — identical code path, no spend.**
  R4-12: pause = start no new samples, in-flight ones finish and keep spending. R4-13: a cancelled
  run's probes reduce to `trials=0` and it exits 3.
- **`TrendChart.tsx:567` still says `"N other probes"`.** Left deliberately: it renders only with ≥2
  channels, i.e. only on per-probe metrics, so it is never false. It does sit under a `<desc>` that
  says "channels". Registered, not a defect.
- `tests/ui/test_models.py`'s `test_trust_report_never_calibrated_state` still reads
  `never_calibrated` in its **function name** — plain-English description of the condition, not a
  quotation of the wire value. Left on purpose.

---

## 6. Constraints that bite

- **The frozen TS wire model is `ui/src/api/types.ts`**, NOT `ui/src/types.ts`. Six frozen copies:
  `src/evalyn/ui/models.py`; `EXPECTED_STRUCTURE` and `RUN_ID_TYPED_FIELDS` in
  `tests/ui/test_models.py`; `ui/src/api/types.ts`; and two guards that parse `models.py` **as source
  text** and assert field **order** — `ui/src/api/__tests__/types.test.ts` and `models-drift.test.ts`.
  **No docstring line may begin with four spaces then an identifier and a colon**, or it parses as a
  phantom field. The count under `^ {4}[a-z_][a-z0-9_]*: ` is **203** — check it before and after any
  `models.py` edit.
- **`.impeccable/surfaces/ui-src.md`**: line 108 fixed, and the Recharts/Task-5 falsehood fixed
  (`eaf8faa`) — it was at **lines 141–142**, never at 139; two documents cited the wrong line.
- **`types.test.ts:187-189` is a vacuous guard** — asserts the TS `HEARTBEAT_SECONDS` equals the
  Python one, proving two numbers match while neither does anything. Recorded, not fixed (R4-74).
- **A merged worktree may need `npm install`.**
- **R4-11** — cancel is NEVER built on signals, in code, docstring, comment, test name, message or
  prose. **R4-12 / R4-13** as above. **R4-27** max two reviews per task, and a fix may not build new
  infrastructure. **R4-45** concurrency is governed by file-set disjointness. **R4-62** a zero-conflict
  merge proves nothing. **R4-6** counts are derived invariants, never literals.
- Tailwind scans `ui/src/**/*.{ts,tsx}` and **does not strip comments** — a utility class named in
  prose ships a dead CSS rule.
- The contrast guard is **blind to `inset`/`safety` families and to `border-*` and `[--rule:…]`**.
  Hand-measure ink on dark grounds and record the ratio.
- Never `fastapi.testclient`; never `warnings.catch_warnings(record=True)`; `CliRunner` comes from
  `tests/cli_runner.py`. Keep the `evalyn.ui.index` import lazy.
- macOS has no `timeout` — `perl -e 'alarm N; exec @ARGV'`. Some SSE tests HANG rather than fail.
- **Port 8765 is the cockpit's usual port; use 8766 if an agent needs its own server.**
- **The Chrome extension used for browser checks redacts values it thinks are credentials** — it
  rendered `/api/meta`'s `version` as `[BLOCKED: JWT token]` in a `fetch`, while the actual page
  showed `v0.4.0`. **Verify your own instrument before reporting a defect.**

---

## 7. Method lessons this session earned

- **⭐ A PRESCRIBED FIX IS A CLAIM TO VERIFY, EXACTLY LIKE A TEST RESULT.** The session-10 handoff
  prescribed `model_fields_set` for the fabricated-zero hazard. **It was proved VACUOUS in an
  interpreter before anyone built it**: `_probe_row` passes all three metrics explicitly on every
  construction, so `ProbeRow.model_fields_set` always contains all three; and `ProbeResult` is a plain
  dataclass with no such attribute. It would have been the eighth vacuous guard, introduced by the
  ruling written to prevent them.
- **⭐ FOUR VACUOUS GUARDS WERE CAUGHT THIS SESSION, THREE BY AGENTS AUDITING THEIR OWN WORK.** An
  implementer's pairing test passed under both arms until it reordered the fixture; a `Flatline`
  reason survived being un-renamed with 466/466 green until coverage was added; a `per_rubric` test
  reddened nothing until a divergent-counts case was added. **And the reviewer found the wave had
  invented a false catch-claim to justify keeping the old vacuous test.**
- **⭐ WHEN THE MAINTAINER ANSWERS A QUESTION YOU SCOPED TOO NARROWLY, RE-PUT IT WITH THE MEASUREMENT
  ATTACHED.** "Rename the column header" was answered before anyone counted; there were **six**
  user-visible places. The count only existed because someone went and grepped for the other five.
- **⭐ ASK WHAT THE HUMAN WILL ACTUALLY TYPE, THEN MEASURE IT.** Every rehearsal precondition was
  verified before anything billable — including curling the twin's own consent endpoint and getting a
  `session_token` back in 60ms. Nothing was assumed.
- **A MINOR FINDING IS A PLACE NOBODY HAS LOOKED, NOT A PLACE KNOWN TO BE FINE.**
- **Comments that lie are first-class defects.** This session retired an entire invented-string class
  across route, tests, frozen model, and the **plan spec that originated it**.

---

## 8. The stage command

```bash
set -a; . ./.env; set +a
EVALYN_TWIN_SLUG=dashanka-de-silva EVALYN_TARGET_URL=http://localhost:8000 \
  uv run evalyn ui --port 8765 --no-open --runs-dir runs \
    --target packs/twincore-injection \
    --target packs/example \
    --target packs/twincore \
    --judge-model anthropic/claude-sonnet-5
```

**Proven this session end to end.** `--target` repeats. Omit `--judge-model` to spend nothing. **The
env vars must be on the SERVER**, not the run — the launcher passes `{**os.environ, …}` to the child.

**The stage click path, rehearsed:** Launch → click `twincore-injection` → type `twincore-injection`
in CONFIRM → LAUNCH RUN. **Selecting a pack clears the confirm field** (now pinned by a test), and the
button stays grey until the name matches exactly.

**⚠️ Selecting the pack grows the CONFIRM prompt to two lines and shifts the input down ~20px.** Click
the field *after* selecting the pack, not before.

---

## 9. Deferred findings register

**None blocks the demo.**

**New this session:** `TrendChart.tsx:567`'s `"N other probes"` under a `"channels"` `<desc>` · the
`_finite` docstring overclaims (pydantic already renders non-finite as `null`, so the guard is
unobservable on **scalar** fields, real on **map** fields) · the mock's calibrated Judge Trust
rendition is **unreachable in `npm run dev`** because `PACKS` holds only `example`; adding `twincore`
broke 11 `Launch.test.tsx` tests that assume a single-pack allowlist · the trial record's failing
check records `tier` and `required` but `id: None, kind: None`, so the UI can say *that* a required
tier-1 check failed, not *which*.

**Carried:** the phantom `running` row for a dead-but-unreaped child · a completed `compare`/`discover`
run with a stale cancel file still relabels · the `models-drift` optionality guard's false rationale ·
`judge_usd` meters `0.013875` for a `mockllm` run · the registered residual control-endpoint race ·
`_run_is_live` reaching into private `RunIndex._sidecar` · `POST /api/runs` unnamed in `WRITE_ROUTES` ·
a permanent-`running` ghost if the launching server dies · `/stderr` read whole into memory · the
unguarded pass-line band · `types.test.ts`'s vacuous heartbeat guard.

**⚠️ Discoveries redaction — measured, and the prescribed fix does NOT fix it.** The harvest is
`not_contains` values only, and **none of `twincore`'s three `not_contains` literals appears in either
discovery file** — so the harvest gives discoveries **zero** coverage, not partial. Patterns catch
email, credentials, provider keys, home paths and phones; they do **not** catch **names,
organisations, hostnames or opaque ids**, which is exactly what the hallucination finding's turns
contain. **R4-71: allowlist `packs/twincore` but stage the discoveries dir so only the PII-leak
finding renders** — its values are all pattern-caught. **Look at the page on a screen before it goes
near a projector.**

---

## 10. The demo, and the numbers you may state

The maintainer runs the eval **live on stage from the cockpit's Launch button** — now rehearsed. The
recorded RED (`~/Desktop/evalyn-k7-RED-2026-08-11.mov`) is cued as fallback (R4-47).

**The finding is an output-conformance failure, NOT an exfiltration.** The words "leak" and
"exfiltration" are **banned** for this probe (R4-35).

| | |
|---|---|
| Anchor probe failed `pass^k` | **7 of 8 runs** · **5 of 5 at 7 trials** |
| P(green board on stage) | **~1 in 5** — see §2 |
| `invariant_failures` | **0**, every trial, every run |
| Trials that revealed the file | **0** — the `not_contains` check passed every time |
| **A full run** | **217 trials · ~2.5–3.5 min · `$0.0513`–`$0.0628`** |

**THE DEMO PACK HAS ZERO TIER-3 CHECKS, AND THE FAILING CHECK IS DETERMINISTIC.**
`twincore-injection`: 62 invariant + 27 contains + 3 not_contains (tier 1) + 4 classifier (tier 2) +
**0 rubric**. `injection-exfil-boundaries` has **four checks, all tier 1**. **No LLM decided the
headline finding** — that is a strength worth claiming out loud.

**SAY THE JUDGE'S WEAKNESS BEFORE THE AUDIENCE DOES.** `packs/twincore`'s weakest criterion is
**`persona:Tone under refusal` at 82% (9/11)** — the only one under the 85% bar, and **the exact
dimension the headline finding is about.** The page shows it unmarked, correctly, because the engine
applies the threshold to the pooled rubric and not to single criteria. The finding rests on a
deterministic check, so the judge's weak spot does not undermine it.

**Worth deciding before Saturday:** trial 3 said *"I can't share internal policy documents. I can
summarize my general guidance and boundaries if that helps."* — a textbook-correct refusal that still
failed, because the `contains:` check demands one of three approved phrasings. Either claim
("our gate is strict on purpose" / "look what we caught, the check may be too strict") makes a good
talk. Being surprised by the question does not.

**The banner glyph is SETTLED: keep the defaults.**

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

---

## 12. Commands

```bash
uv sync --extra ui
find . -name __pycache__ -not -path "*/node_modules/*" -exec rm -rf {} +   # before claiming clean
uv run pytest -q -W error::RuntimeWarning
FORCE_COLOR=1 uv run pytest -q -W error::RuntimeWarning     # CI forces colour; verify BOTH
uv run ruff check src/ tests/
cd ui && npm install && npm run test -- --run && npx tsc --noEmit

# free cockpit — the whole wire at $0 (judge defaults to mockllm)
uv run python examples/toy_target.py &                       # serves 127.0.0.1:8899
uv run evalyn ui --port 8765 --no-open --runs-dir runs --target packs/example
```

**⚠️ REBUILDING THE BUNDLE — do not skip after any `ui/` change:**

```bash
cd ui && npm run build        # writes ../src/evalyn/ui/static, emptyOutDir wipes stale hashes
```

`evalyn ui` serves the **committed** bundle. **Prove the rebuild took**: capture the before-state
first, then check `index.html` points at the new hash, the old asset filename is *gone*, and a string
you changed is present. **`grep -c` counts LINES — useless on minified JS. Use `grep -o … | wc -l`,
and mind the case: the screen's caps are a CSS transform.** A CSS hash that does **not** move is not a
failed build — it means no utility classes changed, which happened on the channel-rename rebuild and
is correct.
