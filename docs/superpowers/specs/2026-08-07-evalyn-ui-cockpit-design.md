# Evalyn `ui` cockpit — design spec

**Written:** 2026-08-07, immediately after Plan #3 merged (`dev` @ `4717891`, v0.4.0, 726 tests).
**Supersedes, for the demo window:** `2026-07-24-evalyn-pro-ui-design.md` (the UI spec) and the four
`2026-07-24-evalyn-pro-4{a,b,c,d}-*.md` plans. Those predate Plan #2b and Plan #3 and are wrong about
the run layout, the CLI surface, and the existence of `discover`. **Mine them; do not execute them.**

---

## 1. What this builds, and why now

A local, loopback-only web cockpit — `evalyn ui` — that launches and live-streams `gate`, `compare`
and `discover` runs, and browses finished runs, `discover` findings, compare scoreboards, trends and
judge-calibration trust.

The AI Tinkerers Bremen demo (**2026-08-14**) presents a committed proposal that promises this
cockpit. It is the one thing the proposal commits to that does not exist. The proven fallback is the
toy flywheel, which is terminal-only and green today; **the UI must not put that fallback at risk.**

### Scope, as decided by the maintainer on 2026-08-07

| Axis | Decision |
|---|---|
| Live scope | Full cockpit — browser launch **and** pause / resume / cancel, SSE streaming |
| Launchable modes | `gate` + `compare` + `discover` |
| Surfaces | Runs · Run Detail (live) · TranscriptViewer · Launch · Discover findings (read-only) · Compare scoreboard · Trends · Judge Trust |
| Judge Trust | Read-only over the **shipped** `calibration.json`. **No Cohen's κ** — 4b Task 1 stays out. |
| Packaging | A real `evalyn[ui]` extra, SPA bundle committed to `src/evalyn/ui/static`, wheel packaging, CI drift check |
| Deferred outright | All of 4a (simulation); 4b panels / escalation / review queue / promote; 4c transports / `evalyn init` / `report.html` |

**Cherry-pick ruling — nothing from 4a/4b/4c enters this plan.** Recorded so it is not re-opened:
`scoring/kappa.py` (4b T1) is genuinely free but renders nowhere in the demo and would re-open
enforcement-critical `calibrate`; `PythonTransport` (4c T2) is the best feature in the three plans
but needs `_open`/`_send` extracted from `engine/solver.py` where they are inline; `report.html`
(4c T6) competes with the SPA for the same drill-down slot. The single freebie taken is 4d's own
2026-07-28 amendment — surfacing `judge_usd` against the budget ceiling, since every artifact
already carries the field.

**Recorded risk.** The maintainer selected the maximum on every axis after being shown the cost.
Seven days, against a Plan #3 baseline of 15 tasks in 5 calendar days, plus a first-contact frontend
toolchain. **Not all of this is expected to land by Aug 14.** The plan is therefore ordered so every
prefix is independently demo-viable, and §8 carries a ranked cut list.

---

## 2. Ground truth — what the code actually does today

Verified this session. The 2026-07-24 documents are wrong about several of these.

- **`runs/` is flat, not per-run directories.** `atomic_write_artifact` (`engine/run.py:113-134`) is
  the single writer for all three modes and produces `runs/<stamp>-<uuid8>-<slug><suffix>.json`,
  with the stamp computed at *write* time. Suffix: `""` gate, `-compare`, `-discover`. There is no
  index, no manifest, no `latest` symlink. Inspect logs go to `runs/logs/`.
- **Typed readers already exist** and must be called rather than reimplemented: `RunArtifact`,
  `CompareArtifact`, `DiscoveryArtifact` `.from_dict`; `evaluate_gate(current, baseline) ->
  GateResult` (`engine/gate.py:25`, pure and in-memory); `render_compare_report` (`compare.py:298`);
  `render_discovery_report` (`discovery/run.py:561`); `emit.load_prior_discoveries` (`emit.py:357`);
  `engine.validate.validate_pack`; `engine.calibrate.load_record` (:195) and `is_stale` (:259);
  `engine.run.reduce_log_to_probes` (:169).
- **The gate report is never written to disk** — `evaluate_gate` returns it, `cli.py:169` echoes it.
- The three artifact classes are **dataclasses**, not Pydantic. Only `Probe` / `Check` / `TargetSpec`
  are Pydantic v2.
- `trial_records` (`run.py:219-227`) is the only place full conversations reach JSON.
- **`discover` provenance lives in YAML comments** (`emit.py:247-275`) and needs a bespoke parser.
  Confirmed status and replay verdict are not in the YAML at all — they are in the `*-discover.json`
  `DiscoveryArtifact.findings[]`. The hunt *conversation* exists only in the `.eval` log, reachable
  via `read_eval_log` + `discovery/solver.py:78 session_from_store`.
- The CLI is **one 674-line module**, `src/evalyn/cli.py` — not a package. Exit `2` is used
  throughout for preflight setup refusals.
- **FastAPI and uvicorn are already installed**, transitively: `inspect_ai==0.3.249` declares
  `fastapi>=0.119.0` and `uvicorn`. The venv holds fastapi 0.139.2, uvicorn 0.51.0, starlette 1.3.1.

### Data actually on disk

82 files in `runs/`: **27 fail `RunArtifact.from_dict`** (pre-Plan-#2a `ProbeResult` schema), 52
load, plus 2 `*-discover.json` (one with 2 replayed findings). **Zero `*-compare.json` exist.**
`runs/baseline.json` is **stale and unloadable** — it carries a `reducers` key that makes
`from_dict` raise. The 112 KB twincore gate artifact has `trial_records: []`.

### Hazards

1. **PII on stage.** `packs/twincore/discoveries/discovered-pii-leak-0bf80f3b.yaml` embeds a real
   person's email verbatim as a `not_contains` check value — it must, or the probe stops being
   outcome-graded. Rendering it raw puts a real address on a projector.
2. **Demo-fallback risk, independent of this work.** The only tracked baseline is
   `ci/baseline-example.json`. There is **no committed twincore baseline**, and `runs/baseline.json`
   is unloadable. The demo's closing beat is a red baseline diff against NiuwnAI, which today has
   nothing to diff against.

---

## 3. Two rulings that shape the architecture

### R1 — Instrumentation is an explicit sink, **not** `inspect_ai.hooks`

Two independent design passes disagreed here. Resolved against the pinned Inspect source: the sink
wins. `@hooks` registers **process-globally** through Inspect's registry, so it would fire for every
eval in the 726-test suite and would destroy the "flag absent ⇒ unchanged behaviour" proof that
protects the terminal fallback.

The sink is passed explicitly and captured by closure:
`build_task(pack, …, sink=NULL_SINK)` → `session_solver(pack, sink=sink)`. Explicit passing is what
makes the no-op provable; a ContextVar would not be.

### R2 — Pause/cancel uses `Task(early_stopping=…)`

The 2026-07-24 spec's "poll the control file between trials" appeared to have no seam: `run_gate` is
a single blocking `inspect_eval(...)` (`engine/run.py:285`) with no Evalyn-side trial loop. Inspect
provides the seam. Verified in `inspect_ai/_eval/task/run.py:1268-1277`:

```python
if early_stopping is not None and logger is not None:
    early_stop = await early_stopping.schedule_sample(state.sample_id, state.epoch)
    if early_stop is not None:
        # count the halt as terminal (not an error) so the eval can
        # reach `total` and be marked finished
        record_sample_completed(task_id)
        return early_stop
```

`EarlyStopping` is a `typing.Protocol`; `schedule_sample(id, epoch) -> EarlyStop | None` is **async**
and awaited **inside** the active-sample context manager, **after** the sample semaphore and
**before** any solver work. So the adapter can `await` there to pause and return `EarlyStop` to
cancel — and Inspect's own comment confirms a halt is recorded terminal-not-error, so the eval still
finishes cleanly rather than tripping `run_gate:287`'s non-success raise.

**"Between trials" with 4 samples in flight:** `schedule_sample` runs after the sample semaphore is
taken but before the target-HTTP concurrency gate (`solver.py:35`). Samples already past that line
run to completion — that is the drain. Newly scheduled ones park. Pause is therefore
**drain-and-hold** with no partial trials, exactly as the original spec asked for.

**A cancelled run can never report PASS**, and this falls out of the existing fail-closed design
rather than needing invention: an `EarlyStop`ped sample produces no scores → `reduce_log_to_probes`
gives that probe `trials == 0` → `evaluate_gate` emits `MISSING` → exit 1. This spec *upgrades* that
to exit 3 via an additive `RunArtifact.cancelled` flag, and adds `cancelled` to the existing
`--update-baseline` refusal list (`cli.py:118-131`) so a cancelled run can never be blessed.

---

## 4. File ownership

| Path | Owner | Purpose |
|---|---|---|
| `runs/<run_id><suffix>.json` | engine | the artifact — unchanged |
| `runs/<run_id><suffix>.events.jsonl` | engine | event stream, sibling on the same stem |
| `runs/<run_id><suffix>.control.json` | server writes, engine reads | pause / resume / cancel |
| `runs/.evalyn-ui/<run_id>/` | server | `meta.json` (argv, pid), `stderr.log` — dot-prefixed, hidden from the glob |

**Siblings, not a per-run directory.** Every existing filename assertion globs `*.json`
(`tests/engine/test_run.py:269,404`, `test_budget.py:116`, `tests/test_cli.py:822,943`,
`tests/discovery/test_run.py:183`) and `*.json` does not match `.events.jsonl` — **zero test churn**.
A per-run directory would force changes to `--baseline` resolution, compare's `--a/--b`, the 82
legacy files and the docs. The run-directory migration stays its own deferred register item instead
of being smuggled in here.

An events file with no artifact is not an error — it is the evidence that a run died, and the UI
renders it as `interrupted`.

### Run-id correlation

`atomic_write_artifact` gains a **keyword-only `run_id: str | None = None`**. When `None` it mints
exactly as today — same stamp format, uuid8, slug regex — so no caller changes and no filename-format
change. A strictly additive diff.

The launcher passes `EVALYN_RUN_ID` in the child env; the **CLI** reads it at command entry and
threads it down as the parameter. `atomic_write_artifact` never reads `os.environ` itself: env is how
the subprocess is told, the parameter is how it flows. The server therefore knows the artifact path
before the run starts — no newest-file heuristics, no races between concurrent runs.

---

## 5. The event stream

One JSON object per line: `{"seq": 1, "ts": "…+00:00", "run_id": "…", "mode": "gate", "type": "…", …}`.

- `seq` starts at 1 and is assigned **under a `threading.Lock` immediately before the write**, so
  file order ≡ seq order. It doubles as the SSE `id:`, and a reconnecting client's `Last-Event-ID: N`
  is served by scanning for `seq > N`. A `threading.Lock` (not asyncio) because gate emits from
  Inspect's event loop thread while `discover` emits from an `asyncio.to_thread` worker.
- Opened `buffering=1` with an explicit `flush()`, no `fsync`. A hard kill can therefore leave a torn
  final line — **the reader must skip an unparseable trailing line**, and that is a stated
  requirement, not folklore.
- `emit` **never raises**: wrapped, warns once as `UserWarning` (never `RuntimeWarning` — the suite
  runs `-W error::RuntimeWarning`), then self-demotes to no-op. Instrumentation must never fail a
  shipping gate.
- `JsonlSink` records `os.getpid()` and refuses to append to a file whose `run.started` carries a
  different pid — single-writer invariant, asserted rather than assumed.

**Ordering under concurrency.** Every trial-scoped event carries `trial_key = f"{probe_id}#{epoch}"`
(gate) or `hunt_key = f"{objective_id}::{persona_id}"` (discover). Global `seq` is a total order;
filtering by key yields per-trial order for free. No vector clocks needed — seq is assigned under one
lock in one process.

**Liveness boundary, stated plainly.** The *conversation* is live: solver and discovery loop emit
from inside the eval. The *scoreboard* (`probe.scored`, `verdict`) arrives in one burst after the
eval returns, because `reduce_log_to_probes` runs post-hoc. Instrumenting the tier scorers would mean
three signature changes on the highest-consequence code in the repo; that is deliberately deferred.

---

## 6. The no-op guarantee

Null-object singleton, one code path, unconditional `sink.emit(…)` at every call site, `NULL_SINK` as
the default at every level. **No `if sink is not None`.**

The claim is *observable* identity — artifacts, exit codes, warnings, filesystem writes, HTTP traffic
— not identical bytecode; arguments are still evaluated. Enforced by a reviewable rule: **call sites
may only pass values already in scope.** Never a computed join, never a deepcopy, never a rebuilt
transcript. That is checkable in review and free at runtime.

Proven by four tests in `tests/engine/test_events_noop.py`: an `_ExplodingSink` whose `emit` raises,
proving the call sites exist (the discriminating RED — a bare `ImportError` would not do);
**constructor interdiction**, monkeypatching `JsonlSink` to a forbidden sentinel and running all three
modes on default paths (the load-bearing test); a filesystem assertion that no sidecar files appear;
and artifact equality between a default run and an explicit-`NULL_SINK` run. The existing 726 green
tests are themselves the proof, provided the first two exist to stop that being vacuous.

---

## 7. Server design

### API contract — frozen first, because it is the parallelism seam

Task 1 produces `src/evalyn/ui/models.py` (Pydantic v2) plus a generated `ui/src/api/types.ts`.
Nothing else starts until it merges: it is what lets frontend and backend tasks proceed as concurrent
subagents against mock fixtures. What it must pin:

1. **`run_id` grammar** — `^\d{8}T\d{6}\d{0,6}-[0-9a-f]{8}-[A-Za-z0-9._-]+$`, with a relaxation for
   legacy `20260723T080347-example`. It is a path *segment*, never a path.
2. **Enums.** `mode`: `gate|compare|discover`. `status`: `passed|gate_failed|invalid|running|paused|
   cancelled|interrupted|failed_to_start|unreadable`. `verdict` tier: `1|2|3|abstained`.
3. **Error envelope** — every non-2xx is `{error:{code, message, detail?}}` with `code` from a closed
   enum. Never a bare FastAPI `{"detail": …}`.
4. **Degradation, not failure** — every list item carries `degraded: bool` + `degraded_reason`. A
   degraded row has null metrics but a valid `run_id`, `created_at`, `mode`.
5. **Absent vs null** — a `capabilities: {transcripts, trial_records, hard_metrics}` block. The SPA
   disables affordances off `capabilities`, never off truthiness.
6. **Redaction marker** — `«redacted:email»`, plus `redacted: bool` on any object that passed the
   filter. One format, no second.
7. **Time** ISO-8601 UTC verbatim from the artifact; the SPA formats. **Money** float, key suffix `_usd`.
8. **SSE names** and a `heartbeat` every 15 s.
9. **Pagination** — cursor by `created_at` descending.

### Endpoints

`/api/meta` · `/api/health` · `/api/runs` · `/api/runs/{id}` · `/api/runs/{id}/gate` ·
`/api/runs/{id}/report` · `/api/runs/{id}/trials/{probe}/{epoch}` · `/api/runs/{id}/events` (SSE) ·
`/api/runs/{id}/stderr` · `POST /api/runs` · `POST /api/runs/{id}/control` · `/api/packs` ·
`POST /api/packs/{id}/validate` · `/api/packs/{id}/axes` · `/api/discoveries` ·
`/api/discoveries/{probe_id}` · `/api/compare/{id}` · `/api/trends` · `/api/trust`.

### Run indexing over a hostile directory

`RunIndex` — single scan, in-process cache keyed by `(path, st_mtime_ns, st_size)`. Mode
classification is **purely lexical**: the filename suffix decides; never open a file to learn what it
is. Loading is a three-layer fallback, every layer caught: `json.loads` → typed `from_dict` → a
shallow *salvage* read (`pack_name`, `created_at`, `len(probes)`) that is enough for a greyed row with
a tooltip. The 27-file failure path must be exercised by a test pointed at the real `runs/` shape.

The index **excludes any filename not matching the run_id grammar**, which drops `baseline.json` and
`logs/` for free. `evaluate_gate` is called **lazily**, only on the detail endpoint, never in the
list — the list carries a cheap `verdict_hint` explicitly labelled as an approximation.

### Redaction is a chokepoint, not a habit

Enforced by a custom `APIRoute` subclass on the `/api` router that scrubs the response body **after**
model serialization. An endpoint cannot bypass it by forgetting to call something; it bypasses only
via an explicit marker, present on exactly two routes (`/api/meta`, `/api/health`) and asserted by a
test that enumerates the route table. The SSE tailer is the only other call site.

Patterns: email, phone, home-dir paths, key shapes — **plus the pack's own `not_contains`/`contains`
check values** harvested from `Probe.checks`. That last one catches
`discovered-pii-leak-0bf80f3b.yaml` *by construction*, since its leaked email **is** a check value.

Reveal is per-object, gated on a token minted at server start, logged to stderr with the probe id.
**There is no global off switch and no env var** — a demo must never be one flag away from projecting
a real person's address.

### Safety guards on browser-launched runs

`--i-know-this-is-prod` is documented but unimplemented (deferred register); the full item needs a
pack-schema field and a four-document sweep, and is Plan #5 material. The UI-scoped minimum:

1. The server never accepts a pack **path** from a request body — only packs named on
   `evalyn ui --target <path>` (repeatable).
2. `discover` launch requires `evalyn ui --allow-discover` at server start.
3. Browser-launched `discover` gets a server-supplied `--max-usd` clamped to
   `min(request, pack.spec.budget.max_usd_per_run)`. The browser can lower it, never raise it.
4. The POST body must echo the pack name as a `confirm` field, so no drive-by `curl` starts spend.
5. One run at a time per `runs_dir` (409 `busy`) — this removes a whole class of demo failure.

Ack and escalation: the `control.paused` / `control.cancelled` **event is the ack**. If none lands
within 60 s the server escalates to `SIGTERM` on the process group, **after** writing `cancel` to the
control file so the CLI can distinguish a deliberate cancel from an infra crash. Never `SIGKILL` —
that loses the Inspect log.

---

## 8. Packaging, testing, CI

**The `[ui]` extra is a contract, not a gate**, since inspect_ai already pulls fastapi and uvicorn.
An "extra missing" environment cannot arise naturally, so that branch is tested by **monkeypatching
the import** — a `skipif` marker would never fire and would give false confidence. Missing extra →
exit **2**, which matches `cli.py`'s existing preflight-refusal semantics exactly.

```toml
[project.optional-dependencies]
ui = ["fastapi>=0.119", "uvicorn>=0.30"]   # no sse-starlette, no uvicorn[standard]

[tool.hatch.build.targets.wheel]
packages = ["src/evalyn"]
artifacts = ["src/evalyn/ui/static/**"]
```

SSE is ~30 lines of `StreamingResponse` over an async generator; starlette is already present and
hand-rolling keeps the framing testable as a pure function.

**Hatchling respects `.gitignore`** (`ignore-vcs` defaults `False`), so the bundle must **not** be
gitignored — a "gitignored but committed" scheme would silently ship an empty `static/`. Use
`artifacts`, not `force-include` (which is for paths *outside* the package). Ruff already ignores the
bundle (`include` is `*.py|*.pyi|*.ipynb|pyproject.toml`) and `node_modules` is already in pytest's
`norecursedirs` — **zero tool-config change for the committed JS**.

**Never import `fastapi.testclient`.** Verified: it raises `StarletteDeprecationWarning` — a
`UserWarning` subclass — at import, recommending `httpx2`, which is not in the lock. Endpoint tests
use `httpx.ASGITransport` + `httpx.AsyncClient`; `asyncio_mode = "auto"` already makes async tests
first-class.

**Import isolation** is already correct — `import evalyn.cli` is 0.150 s and loads neither fastapi,
uvicorn nor inspect_ai — and must be defended by a **subprocess** guard test. An in-process assertion
is worthless once another test has imported the server.

**The SSE tail test is the one that can hang the suite.** Three escalating tests, none starting
uvicorn: a pure sync `sse_frame()` test carrying the `Last-Event-ID` / malformed-line / torn-trailing
-line coverage; a replay-only test against a fixture already ending in `run.finished`, which cannot
hang by construction; and a live tail with **three independent stops** — return on `run.finished`, a
production **idle timeout**, and `asyncio.wait_for(…, 10)`. A fourth covers early client disconnect,
the path that leaks tasks in production. `warnings.catch_warnings(record=True)` is banned here — that
is the documented Plan #3 flake, and an ASGI/anyio test is exactly where a stray GC
`ResourceWarning` lands.

**Drift check.** Vite's hashed filenames are content-derived and stable; the real nondeterminism is
dependency drift, toolchain drift, sourcemaps and line endings. Control all four — commit
`package-lock.json` and use `npm ci`; commit an exact `.nvmrc` and drive `actions/setup-node` from
it; `build.sourcemap: false`; `.gitattributes` `src/evalyn/ui/static/** -text` — and the byte diff is
dependable *on CI's platform*. The rule is **the committed bundle is whatever ubuntu-latest +
`.nvmrc` produces**, and the job uploads its rebuild so a diverging maintainer commits CI's output
rather than fighting it. The diff must be **path-scoped**; a bare `git diff --exit-code` trips over
the suite's writes into `logs/`. Named fallback if it red-flakes twice: a `.build-stamp` hash over
`ui/src` + lockfile + vite config + `.nvmrc`.

**Staged CI — a job lands only in the commit where it can pass.** S0 extras → `uv sync --extra ui`;
S1 server tests join the existing job; S2 adds `ui-frontend` with the drift step
**`continue-on-error: true`**; S3 flips it hard once the SPA is feature-complete; S4 adds `ui-e2e` on
pull_request only; S5 adds `wheel-clean-install` before the release tag. **S2's `continue-on-error`
is the most important scheduling decision here** — between scaffold and feature-complete the bundle
rebuilds on nearly every commit, and a hard gate in that window is precisely the "CI red for days"
failure. Only S0–S1 are on the demo critical path.

---

## 9. Staging, and the ranked cut list

Every stage boundary is a working demo:

- **After the server skeleton** — `evalyn ui` opens a browser on a real port. "It exists."
- **After packaging** ★ **the safe demo** — browse all 82 artifacts (27 as greyed degraded rows),
  open a run, read its gate verdict, drill into a trial transcript. Packaged and CI-checked. If
  everything after this is cut, a coherent product still ships.
- **After the read-only pages** ★ **the differentiator demo** — discover findings with PII redacted
  by default and a deliberate reveal; compare scoreboard; trends; Judge Trust with per-rubric bars.
- **After the launcher** — a browser-launched gate run appears as `running` and tails to completion.
- **After the SPA live layer** — the full cockpit.

**Cut from the top if 2026-08-12 arrives mid-flight:** (1) pause/resume, keeping cancel; (2) per-turn
streaming, emitting `trial.finished` only — Run Detail fills row-by-row for ~80% of the perceived
liveness and none of the solver risk; (3) compare *launching*, keeping the scoreboard; (4) trends;
(5) `?baseline=` re-diff; (6) the drift check downgraded to advisory.

**Never cut:** the redaction chokepoint, the degraded-row path, the `run_id` correlation. Each is
small, load-bearing, and far more expensive to retrofit than to build.

---

## 10. Open questions requiring a spike before Task 19

Three things were read but not run, and they gate the control channel:

1. Does blocking inside `schedule_sample` trip Inspect's display watchdog or `active_sample`
   bookkeeping? The CM is entered *before* the call.
2. Does an `EarlyStop`ped sample leave `log.status == "success"`? `record_sample_completed` implies
   yes, but `run_gate:287` raises on any non-success status, so it must be proven.
3. How does `inspect_eval` react to `SIGTERM`?

Also unverified: Vite byte-reproducibility across macOS↔Linux (hence the `.build-stamp` fallback).

---

## 11. Demo prep outside this plan

**Create a committed twincore baseline.** The demo's closing red-diff beat has nothing to diff
against today: `ci/baseline-example.json` is the only tracked baseline and `runs/baseline.json` is
stale and unloadable. This is user-gated live spend and sits on the critical path independently of
any UI work.
