# Plan #4 (`evalyn ui`) — session 10 handoff

**Written 2026-08-12, midday.** Supersedes `2026-08-12-plan4-session9-handoff.md`, which is history
only.

**The demo is 2026-08-14, a 6pm slot. ~54 hours from this line.**

**The milestone this session reached: Trends is built, reviewed twice, fixed twice, re-reviewed
twice, MERGED, and the bundle is rebuilt and proven — so for the first time the Trends page exists in
a browser served by a real `evalyn ui`.** Its backend route exists too. **Nothing was billed. All 7
pre-approved rehearsal runs are still unused.**

---

## 0. Read this order

1. **`.superpowers/sdd/2026-08-07-evalyn-plan4-ui/progress.md`** — the ledger, rulings R4-0 … R4-78.
   **It and `git log` outrank anyone's recollection, including your own.** Session 10 is its last
   ~350 lines.
2. This document.
3. `docs/JOURNAL.md`'s last three sections.
4. `PRODUCT.md` before any scope question. `.impeccable/surfaces/ui-src.md` before any page task —
   **line 108 is now fixed; line 139 is still false, see §6.**

---

## 1. Where things stand

| | |
|---|---|
| `feat/plan4-ui` (trunk) | **`621fd6e`**, pushed. **Holds everything.** |
| `feat/plan4-ui-frontend` (lane) | `03e017a`, pushed, **fully merged**. Reusable for `ui/**` work. |
| `feat/plan4-ui-engine` | `048e41a` — **stale**, only usable after merging trunk into it. |
| Python suite | **1564 passed, 0 skipped**, both colour modes, cold, ruff clean |
| UI suite | **463 passed / 22 files**, `tsc` exit 0 |
| Served bundle | **rebuilt and proven** at `621fd6e` |
| `runs/` corpus (gitignored) | 113 artifacts · 7 for `twincore-injection` · 3 for `twincore` |
| Spend | **~$0.276 of ~$1.00. NOTHING billed this session. 7 of 8 rehearsal runs unused.** |
| Recovery tags | `pre-merge4-20260812` → `81af3eb` (and older ones; delete when you like) |

**Expected working-tree noise — leave all three alone:** two modified files under
`docs/superpowers/handoffs/` (the maintainer deleted the kickoff-prompt sections; verified not ours)
and the quarantined `ci/baseline-twincore-injection.TAINTED-blessed-a-FAIL.json`.

### What shipped this session

- **Both previously-unreviewed waves are now reviewed, fixed and re-reviewed.** Stage fixes: 3
  Important + 3 Minor, all ADDRESSED. Trends: 1 Critical + 5 Important + 8 Minor, all ADDRESSED.
- **`GET /api/trends` built** (`496045c`) — reviewed, **4 Major + 3 Minor still open**, see §3.
- **R4-76 `err=True` class finished** (`916363f`).
- **Merge #4** (`dea7911`) + **bundle rebuild** (`621fd6e`), both proven.

---

## 2. ⚠️ THE THING TO INTERNALISE BEFORE YOU START

**Six vacuous guards were found this week — tests that pass under both arms of a mutation.** One was
the *flagship* test for the page's load-bearing invariant. One was declared by its own author. The
highest-yield rule in this plan remains:

> **Read mutation evidence BY TEST NAME, NEVER by pass/fail count.**

The stage-fix wave is the proof: deleting the line its own commit message called "the fix" left the
suite at **1539 passed, 0 failed**. A count that does not move is the loudest signal available.

**And the second-highest-yield rule, which this session earned the hard way — see §7:**

> **The controller's own claims are claims to verify.** Three falsehoods were relayed by the
> controller this session and all three were caught *downstream*.

---

## 3. NEXT SESSION'S FIRST JOB — the trends-route fix wave

Report: `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/s10-review-trendsroute-report.md`.
**Zero defects in what the route returns.** Every finding is about what the code *says* and what the
tests *prove*.

**Major:**

1. **F7 — the flagship guarantee-1 test is VACUOUS.** The test for "a degraded run is ABSENT, never
   `value: 0`" — the page's entire credibility — does not discriminate. Fix it first.
2. **F5 — the fabricated-zero register entry is WRONG, and the wrong version is in the ledger.** The
   implementer reported "all 356 probe entries carry the metric keys explicitly, so the hazard is
   latent". **There are 623 probe entries and 108 omit all three keys.** No fabricated zero reaches
   the chart today (0 of 69 plotted runs) — **but only because all 27 key-less artifacts happen to
   also be degraded. A coincidence of a legacy schema, not an enforced property.**
   `ProbeResult.pass_k` defaults to `0.0`, so any future artifact that omits the key while otherwise
   typing cleanly is plotted as a genuine-looking zero.
   **Candidate cheap fix, NOT yet tried: pydantic v2's `model_fields_set` lets the route emit a point
   only when the metric was EXPLICITLY set — contained, no engine-schema surgery. Verify it works
   before relying on it.**
3. **F2 — R4-74 is half-fixed.** The heartbeat comment was corrected in `models.py`; **the TS mirror
   in `ui/src/api/types.ts` still promises emission.** This is exactly the half-a-defect-class trap
   R4-76 exists to prevent.
4. **F1 — `TrendSeries`'s docstring lies.**

**Minor:** F3 `"1 probes"` renders on screen · F4 the MSW mock diverges from the real route on
`judge_usd` · F6 a second unobservable clause.

**`judge_usd` is ADJUDICATED AND UPHELD — do NOT take the offered five-line reversal.** It returns
one run-level series (`probe_id: "(whole run)"`) because per-probe spend **does not exist** in the
artifact; 31 identical series would fabricate 31 measurements. The reviewer confirmed the built page
renders it cleanly — channel bank, selection affordance and chart all survive.

**Everything is in the trunk now, so fold into the same wave:** the caption one-word tightening
(`a probe reading 1.00` → `any probe`), the **Launch clear-on-switch test** (§5), and
`.impeccable/surfaces/ui-src.md:139` (§6).

---

## 4. Then, in order

1. **The trends-route fix wave** (§3).
2. **WIRING-CHECK TRENDS AGAINST THE REAL SERVER.** This has never been done and is a **required
   gate** — building against mocks produced 16 divergences in session 9 and F4 above shows the mock
   *still* diverges. The page and its route are both in the trunk and the bundle is rebuilt, so this
   is finally possible. Free: no `--judge-model`.
3. **The rehearsal run — MAINTAINER-GATED (R4-70).** See §8.
4. **Judge Trust** (R4-77) → **Discoveries** (R4-71) → **Compare**. If road runs out, it runs out on
   Compare.

---

## 5. Small queued items (all `ui/**`, all now in the trunk)

- **The Launch clear-on-switch interlock is UNPINNED.** `Launch.tsx` clears the confirm field on every
  pack click — *"a name typed for one pack must not arm a launch of another"* — which is the
  **strongest guard against launching the wrong pack on stage**, and **no test holds it**.
  `Launch.test.tsx` has 5 tests, none covering it. It matters more now that the stage command carries
  **three** packs (§8).
- The caption one-word tightening (§3).
- **Registered, not fixed:** the "guaranteed empty band" the pass-line label sits in is real today but
  **unguarded** — move the pass line off 1.00 and the tag lands mid-plot inside the data band, and
  nothing in the suite would catch it. A trap for whoever adds the next threshold.

---

## 6. Constraints that bite (corrected — older docs are stale)

- **The frozen TS wire model is `ui/src/api/types.ts`** (45 types), **NOT `ui/src/types.ts`**. Six
  frozen copies: `src/evalyn/ui/models.py`; `EXPECTED_STRUCTURE` and `RUN_ID_TYPED_FIELDS` in
  `tests/ui/test_models.py`; `ui/src/api/types.ts`; and two guards that parse `models.py` **as source
  text** and assert field **order** — `ui/src/api/__tests__/types.test.ts` and `models-drift.test.ts`.
  **No docstring line may begin with four spaces then an identifier and a colon**, or it parses as a
  phantom field.
- **`.impeccable/surfaces/ui-src.md:108` is FIXED** (`b9e79f9` — cost renders to four decimals, not
  cents). **Line 139 is STILL FALSE** and is now cheap to fix correctly: it credits Task 5 with
  pinning Recharts; Task 5 never installed it, the Trends wave did, and **it is now genuinely in the
  trunk's `package.json` at `3.10.1`**, so the true sentence can finally be written.
- **`types.test.ts:187-189` is a vacuous guard** — it asserts the TS `HEARTBEAT_SECONDS` equals the
  Python one, proving two numbers match while **neither number does anything**. Recorded, not fixed;
  a real fix needs the emission we deliberately declined to build (R4-74).
- **A merged worktree needs `npm install`.** The trunk's `node_modules` lacked Recharts after the
  merge; the lockfile brings **37** new packages. Not an error.
- **R4-11** — cancel is NEVER built on signals, in code, docstring, comment, test name, message or
  **prose**. The repo's own guard scans only `engine/control.py` and will not catch a slip elsewhere.
- **R4-12** pause = start no new samples; in-flight ones finish and keep spending. **R4-13** a
  cancelled run's probes reduce to `trials=0` and it exits 3. **R4-27** max two reviews per task, and
  a fix may not build new infrastructure — **deliberately exceeded once, see R4-78**. **R4-45**
  concurrency is governed by file-set disjointness; two implementers never share a worktree.
  **R4-62** a zero-conflict merge proves nothing. **R4-6** counts are derived invariants, never
  literals.
- Tailwind scans `ui/src/**/*.{ts,tsx}` and **does not strip comments** — a utility class named in
  prose ships a dead CSS rule.
- The contrast guard **was widened this session to see `decoration-*`**, and that widening was proved
  non-vacuous. It is **still blind to `inset`/`safety` families and to `border-*` and `[--rule:…]`**.
  Hand-measure ink on dark grounds and record the ratio.
- Never `fastapi.testclient`; never `warnings.catch_warnings(record=True)`; `CliRunner` comes from
  `tests/cli_runner.py`. Keep the `evalyn.ui.index` import lazy.
- macOS has no `timeout` — `perl -e 'alarm N; exec @ARGV'`. Some SSE tests HANG rather than fail.

---

## 7. Method lessons this session earned

- **⭐ THE CONTROLLER RELAYED THREE FALSEHOODS AND ALL THREE WERE CAUGHT DOWNSTREAM.** (1) "these two
  files are new" — they pre-existed; (2) "`/api/trust` sets the 200-not-404 precedent" — no such
  route exists; (3) "356 probe entries, all explicit" — 623, with 108 omitted. Each was a claim
  relayed without checking. **The rule "the controller's own ledger entries are claims to verify" was
  written in session 9 and violated three times in session 10 by the person quoting it. A rule you
  cite but do not apply is a rule you do not have.**
- **⭐ A MINOR FINDING IS A PLACE NOBODY HAS LOOKED, NOT A PLACE KNOWN TO BE FINE.** "The tooltip has
  no test coverage" was filed Minor. Someone went and looked: the tooltip was **printing another
  probe's reading under the hovered run's timestamp** — a data-integrity defect on a chart an
  audience would read.
- **⭐ ASK WHAT THE HUMAN WILL ACTUALLY TYPE, THEN MEASURE IT.** Chasing one implementer's throwaway
  concern produced the session's most useful numbers: the demo pack's *only* validation warning is
  the one saying the run is **217 sessions**, and it was going to `/dev/null`; and a full stage run
  is **~3.1 minutes at ~$0.06**, measured from four artifacts. Two controller fears — a ten-minute
  stage wait and a blown budget — were **refuted by measurement**, not argued away.
- **⭐ A CHEAP TEST BEATS A SPECULATIVE BUILD.** Four greps established that the missing heartbeat
  cannot cause the failure it appeared to threaten (the SPA has no liveness timer; `EventSource`
  auto-reconnects; the 120s idle *comment* is a standard keep-alive). A feature was not built.
- **RENDER THE UI AND LOOK — third session running.** The Critical was found in a browser after the
  tests were green, and verified fixed by reading the SVG's own `d` attribute rather than a test.
- **VERIFY YOUR OWN INSTRUMENT.** A reviewer discovered its browser profile renders at a constant
  1.111 scale and set 738 to obtain a true 820. It also read a ground colour out of the live page
  rather than trusting the docstring that stated it.
- **A DEFECT CLASS THAT KEEPS REGENERATING IS A FIX AIMED AT INSTANCES.** "A legend entry for a mark
  nobody drew" was fixed twice, survived a third time, and the fix for the third introduced a fourth.
- **DECLARING YOUR OWN VACUOUS GUARD IS THE RIGHT MOVE.** An implementer measured that its own mode
  filter was unobservable and said so in both the route and the test rather than shipping it silent.
- **TIME A DOCS FIX TO WHEN ITS CLAIM BECOMES TRUE.** Half of F12 was deliberately deferred past the
  merge, because writing "pinned by the Trends task" pre-merge replaces one false line with another.
- **Comments that lie are first-class defects — the count passed ten this session.**

---

## 8. The stage command — NOW THREE PACKS

```bash
set -a; . ./.env; set +a
EVALYN_TWIN_SLUG=dashanka-de-silva EVALYN_TARGET_URL=http://localhost:8000 \
  uv run evalyn ui --port 8765 --no-open --runs-dir runs \
    --target packs/twincore-injection \
    --target packs/example \
    --target packs/twincore \
    --judge-model anthropic/claude-sonnet-5
```

- `--target` **repeats** (`list[str]`, verified). `--judge-model` defaults to **unset**, which keeps
  the free `mockllm` path for debugging — omit it and you spend nothing.
- **The env vars must be on the SERVER**, not the run: the launcher passes `{**os.environ, …}` to the
  child, so whatever the server lacks, the run lacks.
- **`packs/example`** is allowlisted by **R4-69** so Trends has 78 runs to draw rather than 7.
  **`packs/twincore`** is needed by **R4-71** (Discoveries) and **R4-77** (Judge Trust) — it is the
  **only** pack with either discoveries or calibration data.
- **Three entries now appear in the Launch dropdown.** The page is well defended: no default
  selection, and **selecting a pack clears the confirm field**, so a misclick disarms the launch
  rather than firing at the wrong pack. That guard is **not pinned by any test** (§5).

**The rehearsal (R4-70) is MAINTAINER-GATED. Do not fire it without an explicit go.** It needs the
twin live at `http://localhost:8000`, which is the maintainer's product and cannot be started from
this repo. **A full run is 217 trials, ~3.1 minutes, ~$0.06.** It is the only test for **F4**
(intermediate progress rendering, never seen by a human) and for the control buttons driven by mouse.
**Take a screenshot of the finished banner.**

---

## 9. Deferred findings register

**None blocks the demo.**

**New this session:** the F5 fabricated-zero exposure (§3) · the unguarded pass-line band (§5) ·
`types.test.ts`'s vacuous heartbeat guard (§6) · a `chassis-200` gridline (1.27:1) through the
pass-line tag's baseline · the tooltip transiently covering that tag at top-right · `margin.top`
12→24 shortening the plot range 12px inside a fixed 340px height · the `ABSENT_BASELINE_FILENAME`
comment saying "three tests" where M12 now reddens four node ids across three functions (**a comment
aged by its own commit**) · `build_trends` lives in `server.py` rather than the planned
`aggregate.py` (public, no closure deps — Task 14 can move it freely) · the bundle is **+131%**
(283,136 → 655,021 bytes) after Recharts.

**Carried:** the phantom `running` row for a dead-but-unreaped child · a completed `compare`/
`discover` run with a stale cancel file still relabels (pinned by a test written to go red when an
engine-side `cancelled` field lands) · the `models-drift` optionality guard's false rationale ·
`judge_usd` meters `0.013875` for a `mockllm` run · the registered residual control-endpoint race ·
`_run_is_live` reaching into private `RunIndex._sidecar` · `POST /api/runs` unnamed in `WRITE_ROUTES`
· a permanent-`running` ghost if the launching server dies · `/stderr` read whole into memory.

**⚠️ Discoveries redaction — measured, and the prescribed fix does NOT fix it.** The harvest is
`not_contains` values only, and **none of `twincore`'s three `not_contains` literals appears in
either discovery file** — so the harvest gives discoveries **zero** coverage, not partial. Patterns
catch email, credentials, provider keys, home paths and phones; they do **not** catch **names,
organisations, hostnames or opaque ids**, which is exactly what the hallucination finding's turns
contain. Wiring the harvest buys almost nothing (the one discoveries `not_contains` value *is* the
email patterns already catch, and the other finding has none). **R4-71: allowlist `packs/twincore`
but stage the discoveries dir so only the PII-leak finding renders** — its values are all
pattern-caught. **Look at the page on a screen before it goes near a projector.**

---

## 10. The demo, and the numbers you may state

The maintainer runs the eval **live on stage from the cockpit's Launch button**. The recorded RED
(`~/Desktop/evalyn-k7-RED-2026-08-11.mov`) is cued as fallback (R4-47).

**The finding is an output-conformance failure, NOT an exfiltration.** The words "leak" and
"exfiltration" are **banned** for this probe (R4-35).

| | |
|---|---|
| Board RED | **3 of 3 runs** |
| `injection-exfil-boundaries` RED | **3 of 3** — the anchor; build the demo on it |
| Anchor probe's trials across 3 runs | **21** |
| …that revealed the file | **0** |
| …that used non-approved wording | **3 — one per run, never the same trial twice** |
| `invariant_failures` | **0**, every trial, every run |
| **A full run** | **217 trials · ~3.1 min (2.55–3.54) · ~$0.06** |

**⚠️ The ~12% P(green board) figure in older notes is RETRACTED.** The trustworthy number is
empirical: **3 of 3 runs came up red.** **The deviating epoch moves every run — never script the
stage click-path to a fixed epoch.**

**The banner glyph is SETTLED: keep the defaults.** Draw a neutral mark after the demo, not before.

---

## 11. Git-safety block for every dispatch

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

**Snapshot every worktree before dispatching a reviewer and diff it after** — HEAD, tree, stash
count and porcelain. It caught nothing this session, which is the point: five reviewers each returned
their worktree byte-identical, and that is only knowable because it was checked.

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
and mind the case: the screen's caps are a CSS transform.** Three greps looked like a failed rebuild
this session and were case artifacts.
