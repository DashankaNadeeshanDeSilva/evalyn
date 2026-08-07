# Evalyn Plan #4 — the `evalyn ui` cockpit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task (fresh **Opus 5** subagent per task — implementers/fixers AND
> reviewers, set `model: opus` explicitly on **every** dispatch — TDD inside each, two-stage review,
> checkpoint with the maintainer after each task). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ship `evalyn ui` — a local, loopback-only cockpit that launches and live-streams `gate`,
`compare` and `discover` runs, and browses finished runs, `discover` findings, compare scoreboards,
trends and judge-calibration trust.

**Architecture:** an explicit `EventSink` threaded through the engine (never `inspect_ai.hooks`,
which registers process-globally and would fire inside the test suite), writing
`runs/<run_id>.events.jsonl` as a **sibling** of the existing flat artifact — no per-run-directory
migration. Pause/cancel rides Inspect's own `Task(early_stopping=…)` seam. A FastAPI server reads
`runs/` through the already-shipped typed readers and streams events over hand-rolled SSE; a Vite/
React SPA is prebuilt into `src/evalyn/ui/static` and shipped in the wheel behind an `[ui]` extra.

**Tech Stack:** Python 3.12, `uv`, Inspect AI ≥0.3.249, FastAPI + uvicorn (already transitive via
inspect_ai), Pydantic v2, pytest; Node 22 + Vite + React 18 + TS + Tailwind + TanStack Query +
React Router + Recharts + Vitest + Playwright.

**Design spec:** [`../specs/2026-08-07-evalyn-ui-cockpit-design.md`](../specs/2026-08-07-evalyn-ui-cockpit-design.md)
— **read it first; this plan implements it.**

## Global Constraints

- **`uv` only** (system `python3` is 3.9). Tests: `uv run pytest -q -W error::RuntimeWarning`.
  Lint: `uv run ruff check src/ tests/`. Branch starts at **726 tests**.
- **CI forces colour.** Verify every task under **both** plain and `FORCE_COLOR=1`. Any test
  asserting substrings against CLI output MUST import `CliRunner` from `tests/cli_runner.py`,
  **never** `typer.testing`.
- **Never import `fastapi.testclient`** — it raises `StarletteDeprecationWarning` (a `UserWarning`
  subclass) at import. Use `httpx.ASGITransport(app=app)` + `httpx.AsyncClient`.
- **Never use `warnings.catch_warnings(record=True)`** in UI tests — the documented Plan #3 flake.
- **The base package must never import FastAPI at module scope.** `src/evalyn/ui/__init__.py` stays
  empty; `fastapi` is imported only inside `ui/server.py`, which is imported only inside the `ui`
  command body. Baseline to defend: `import evalyn.cli` = 0.150 s, loading none of fastapi/uvicorn/
  inspect_ai.
- **`sink.emit(...)` is unconditional at every call site** — no `if sink is not None`. Call sites may
  only pass values **already in scope**: never a computed join, a deepcopy, or a rebuilt transcript.
- **Redaction is default-ON** and enforced at the serialization boundary. No global off switch, no
  env var. Reveal is per-object and token-gated.
- **Zero-spend by default.** Every task here is zero-spend (mockllm + the toy target). Nothing spends
  judge tokens or TwinCore sessions without the maintainer's fresh explicit consent, cost stated
  first.
- **Commits:** ask before every **push** and **PR**; commits themselves are automatic. Under the
  maintainer's name only, no Claude trailer:
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit …`.
  Conventional prefixes. Stage files **explicitly — never `git add .`**. Feature branch
  `feat/plan4-ui` cut from `dev` @ `4717891`, PR back to `dev`.
- **Never** overwrite `packs/twincore/calibration.json`. Never commit `runs/`. Never move
  `packs/twincore/discoveries/discovered-pii-leak-0bf80f3b.yaml` into `probes/` — it embeds a real
  email and `probes/` is tracked in a public repo.
- **Exit codes:** `0` pass, `1` gate regression, `2` preflight setup refusal (nothing billed),
  `3` run-invalid. A missing `[ui]` extra and a cancelled run map to `2` and `3` respectively.

---

## File structure

| File | Responsibility |
|---|---|
| `src/evalyn/engine/events.py` | `EventSink` protocol, `NullSink`/`NULL_SINK`, `JsonlSink` |
| `src/evalyn/engine/control.py` | `RunController`, the `EarlyStopping` adapter, `RunCancelled` |
| `src/evalyn/ui/__init__.py` | **empty** (docstring only) — import isolation |
| `src/evalyn/ui/models.py` | every API response model (Pydantic v2) + enums + error envelope |
| `src/evalyn/ui/paths.py` | `RUN_ID_RE`, artifact/events/control/sidecar path derivation |
| `src/evalyn/ui/index.py` | `RunIndex` — scan, classify, 3-layer load, salvage, status |
| `src/evalyn/ui/redact.py` | `Redactor` + `RedactingRoute` chokepoint |
| `src/evalyn/ui/stream.py` | `sse_frame`, `event_stream` (replay + live tail + idle timeout) |
| `src/evalyn/ui/launcher.py` | `build_argv`, `RunLauncher` (spawn, reap, control, stderr) |
| `src/evalyn/ui/discoveries.py` | provenance-comment parser + finding/verdict join |
| `src/evalyn/ui/aggregate.py` | trends aggregation + trust report |
| `src/evalyn/ui/server.py` | `create_app`, `serve`, all routers, static mount |
| `ui/` | Vite/React project; builds to `src/evalyn/ui/static/` (committed) |

---

### Task 0: Spike — prove the `early_stopping` seam (throwaway, not committed to `src/`)

Gates Task 19. Three things were read in Inspect's source but never run. **Timebox: one session.**

**Files:**
- Create: `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/spike_early_stopping.py` (throwaway)
- Create: `.superpowers/sdd/2026-08-07-evalyn-plan4-ui/SPIKE-FINDINGS.md`

**Interfaces:**
- Produces: a written yes/no on each question below. **No `src/` change.** Task 19 consumes the findings.

- [ ] **Step 1: Write the spike.** A minimal Inspect `Task` over the toy pack with an `EarlyStopping`
  implementation whose `schedule_sample` (a) sleeps 2 s for the first sample then returns `None`, and
  (b) returns `EarlyStop(id, epoch, reason="spike")` for a chosen sample.
- [ ] **Step 2: Answer Q1 — does blocking trip a watchdog?** Run with the 2 s sleep. Record whether
  Inspect logs a stall/timeout warning or alters `active_sample` bookkeeping.
- [ ] **Step 3: Answer Q2 — does `EarlyStop` leave `log.status == "success"`?** Print `log.status`
  and the sample count. **This is the load-bearing answer** — `run_gate:287` raises on any
  non-success status, so a `cancelled` result must still come back `success`.
- [ ] **Step 4: Answer Q3 — SIGTERM.** Send `SIGTERM` to a running `inspect_eval` in a subprocess;
  record whether a readable partial `.eval` survives.
- [ ] **Step 5: Write `SPIKE-FINDINGS.md`** with each answer plus the evidence, and note the fallback
  if Q2 is "no" (cancel would then have to be implemented as an artifact-level flag only, with
  pause/resume cut).
- [ ] **Step 6: Commit the findings doc only** (`docs:` prefix). The spike script stays uncommitted.

---

### Task 1: Freeze the API contract

**The parallelism seam.** Nothing else starts until this merges — every later task, backend and
frontend, is written against these types and the fixture corpus.

**Files:**
- Create: `src/evalyn/ui/__init__.py` (empty, docstring only), `src/evalyn/ui/models.py`
- Create: `tests/ui/test_models.py`, `tests/fixtures/ui_runs/` (4 JSON fixtures)
- Modify: `pyproject.toml` (register the `ui` pytest marker)

**Interfaces:**
- Produces: `RunMode` (`gate|compare|discover`); `RunStatus` (`passed|gate_failed|invalid|running|
  paused|cancelled|interrupted|failed_to_start|unreadable`); `ErrorCode` (`not_found|
  unreadable_artifact|pack_error|launch_refused|busy`); `ApiError`/`ErrorEnvelope`;
  `Capabilities(transcripts: bool, trial_records: bool, hard_metrics: bool)`;
  `RunSummary(run_id, mode, pack_name, created_at, status, degraded, degraded_reason, capabilities,
  judge_usd, verdict_hint)`; `RunDetail`; `TrialView`; `FindingRow`; `FindingDetail`; `Scoreboard`;
  `TrendSeries`; `TrustReport`; `LaunchRequest`; `ControlRequest`. All `model_config =
  ConfigDict(extra="forbid")`.

- [ ] **Step 1: Build the fixture corpus.** Copy from the real `runs/` into
  `tests/fixtures/ui_runs/`: one loadable post-#2a gate artifact **with** `trial_records`, one
  **legacy** gate artifact that fails `RunArtifact.from_dict`, one `*-discover.json` with 2 findings,
  and one hand-written `*-compare.json` (none exist on disk — synthesise it from `CompareArtifact`'s
  field list). Redact any real values by hand; these are committed.
- [ ] **Step 2: Write the failing test.** `tests/ui/test_models.py` asserts: every enum's exact
  member set; `extra="forbid"` rejects an unknown key; `RunSummary` round-trips each of the four
  fixtures; a degraded row validates with `degraded=True`, null metrics and a non-null `run_id`.
- [ ] **Step 3: Run it — expect FAIL** (`ModuleNotFoundError: evalyn.ui.models`).
  `uv run pytest tests/ui/test_models.py -v`.
- [ ] **Step 4: Implement `models.py`.** Pydantic v2 only; no imports from `fastapi`.
- [ ] **Step 5: Register the marker** in `pyproject.toml`:
  `markers = ["ui: exercises the evalyn[ui] server (in-process, no network)"]` (no markers exist today,
  so an unregistered one would raise `PytestUnknownMarkWarning`).
- [ ] **Step 6: Full suite + lint green in both colour modes**, then commit:
  `feat(ui): freeze the cockpit API contract and fixture corpus`.

---

### Task 2: `run_id` correlation + path layout

**Files:**
- Modify: `src/evalyn/engine/run.py:113-134` (`atomic_write_artifact`), `:305` (`run_gate`);
  `src/evalyn/engine/compare.py:290`; `src/evalyn/discovery/run.py:537`; `src/evalyn/cli.py`
- Create: `src/evalyn/ui/paths.py`, `tests/ui/test_paths.py`
- Test: `tests/engine/test_run.py` (add), existing filename tests must stay green

**Interfaces:**
- Produces: `new_run_id(pack_name: str) -> str`; `atomic_write_artifact(..., *, run_id: str | None =
  None) -> Path`; `paths.RUN_ID_RE`, `paths.events_path(artifact: Path) -> Path`,
  `paths.control_path(artifact: Path) -> Path`, `paths.sidecar_dir(runs_dir: Path, run_id: str) -> Path`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing tests.** (a) `atomic_write_artifact(..., run_id="20260807T101112000000-deadbeef-example")`
  writes exactly that filename; (b) with `run_id=None` the minted name still matches the **current**
  regex `^\d{8}T\d{6}\d{6}-[0-9a-f]{8}-.+\.json$` — this is the discriminating guard that the default
  path is unchanged; (c) `events_path`/`control_path` return siblings on the same stem; (d) `RUN_ID_RE`
  rejects `baseline.json` and accepts the legacy `20260723T080347-example` form.
- [ ] **Step 2: Run — expect FAIL** (`TypeError: unexpected keyword 'run_id'`).
  `uv run pytest tests/ui/test_paths.py tests/engine/test_run.py -v`.
- [ ] **Step 3: Implement.** Add the keyword-only param; when `None`, mint exactly as today. Extract
  the minting into `new_run_id`. Thread `run_id: str | None = None` through `run_gate`,
  `write_compare_artifact`, `write_discovery_artifact` — one line each.
- [ ] **Step 4: Wire the env read in `cli.py` only.** Each of `gate`/`compare`/`discover` reads
  `os.environ.get("EVALYN_RUN_ID")` at command entry, validates it against `RUN_ID_RE` (ignore if
  invalid), and passes it down. **`atomic_write_artifact` must never read `os.environ`** — add a test
  asserting `"environ" not in inspect.getsource(atomic_write_artifact)`.
- [ ] **Step 5: Run the full suite — expect PASS with zero churn** in `tests/engine/test_run.py:269,404`,
  `test_budget.py:116`, `tests/test_cli.py:822,943`, `tests/discovery/test_run.py:183`.
- [ ] **Step 6: Both colour modes + lint**, then commit:
  `feat(ui): thread an optional run_id through artifact writing`.

---

### Task 3: `RunIndex` — survive a hostile `runs/` directory

**Files:**
- Create: `src/evalyn/ui/index.py`, `tests/ui/test_index.py`

**Interfaces:**
- Consumes: `ui.models` (Task 1), `ui.paths` (Task 2).
- Produces: `RunIndex(runs_dir: Path)` with `.list(*, mode=None, pack=None, status=None, limit=50,
  before=None) -> list[RunSummary]`, `.get(run_id: str) -> RunDetail`, `.artifact_path(run_id) ->
  Path | None`. Module function `derive_status(artifact, sidecar, gate_result) -> RunStatus`.

- [ ] **Step 1: Write the failing tests.** (a) pointed at `tests/fixtures/ui_runs/`, `.list()` returns
  one row per fixture and **raises nothing**; (b) the legacy fixture comes back `degraded=True` with
  a non-null `run_id`, `created_at` and `mode`, and null metrics; (c) a file containing `{` (invalid
  JSON) yields `degraded=True, degraded_reason` mentioning JSON; (d) `baseline.json` and a `logs/`
  entry are **excluded** by `RUN_ID_RE`; (e) mode is classified from the filename suffix **without
  opening the file** — assert via a `monkeypatch` that makes `json.loads` raise, and check `.list()`
  still returns correct `mode` values; (f) `derive_status` is a pure function, table-tested over the
  nine status cases.
- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`). `uv run pytest tests/ui/test_index.py -v`.
- [ ] **Step 3: Implement the three-layer load.** `json.loads` → typed `from_dict` → shallow salvage
  (`pack_name`, `created_at`, `len(probes)`). **Every layer caught.** Cache keyed on
  `(path, st_mtime_ns, st_size)`.
- [ ] **Step 4: Implement listing.** Default sort is `sorted(filenames, reverse=True)` with zero I/O
  on the empty-filter path. `evaluate_gate` is **never** called here — the list carries only
  `verdict_hint`, computed from `probes[]`.
- [ ] **Step 5: Add the real-directory tolerance test.** Point `RunIndex` at the repo's actual `runs/`
  if present (`pytest.mark.skipif` when absent), assert it returns 82 rows with 27 `degraded` and
  raises nothing. This is the test that would have caught the 27-file minefield.
- [ ] **Step 6: Both colour modes + lint**, then commit: `feat(ui): run index with graceful degradation`.

---

### Task 4: Redaction chokepoint

**Files:**
- Create: `src/evalyn/ui/redact.py`, `tests/ui/test_redact.py`

**Interfaces:**
- Consumes: `targets.schema.Probe` (for check-value harvesting).
- Produces: `Redactor(extra_values: Iterable[str] = ())` with `.scrub(obj: Any) -> Any` and
  `.harvest_from_probes(probes: Iterable[Probe]) -> None`; `RedactingRoute(APIRoute)`;
  `no_redact(fn)` decorator marker; marker format `«redacted:<kind>»`.

- [ ] **Step 1: Write the failing tests.** (a) an email, an E.164 phone, a home-dir path and a bearer
  token in a **nested** dict/list are all replaced with the right `«redacted:*»` marker; (b)
  `harvest_from_probes` over a `Probe` carrying a `not_contains` check whose `value` is
  `owner@example.com` causes that literal to be scrubbed **even though it is not email-shaped after
  harvesting** — use a non-email sentinel value to prove harvesting, not the email regex, did the
  work; (c) scrubbing sets `redacted: True` on the containing object; (d) `scrub` is idempotent.
- [ ] **Step 2: Run — expect FAIL.** `uv run pytest tests/ui/test_redact.py -v`.
- [ ] **Step 3: Implement `Redactor`.** Walk any JSON-able structure; rewrite strings only.
- [ ] **Step 4: Implement `RedactingRoute`.** An `APIRoute` subclass whose `get_route_handler`
  scrubs the response body **after** model serialization. `no_redact` sets an attribute the subclass
  honours.
- [ ] **Step 5: Write the route-table test** (it will grow with Task 6+): enumerate `app.routes` under
  `/api` and assert each is either a `RedactingRoute` or carries the `no_redact` marker. Assert the
  marked set is **exactly** `{"/api/meta", "/api/health"}`.
- [ ] **Step 6: Both colour modes + lint**, then commit: `feat(ui): default-on redaction chokepoint`.

---

### Task 5: Frontend scaffold + mock layer

**Files:**
- Create: `ui/package.json`, `ui/package-lock.json`, `ui/.nvmrc`, `ui/vite.config.ts`,
  `ui/tsconfig.json`, `ui/tailwind.config.ts`, `ui/index.html`, `ui/src/main.tsx`,
  `ui/src/api/types.ts`, `ui/src/mocks/handlers.ts`, `ui/README.md`
- Modify: `.gitignore` (add `ui/node_modules/`, `ui/dist/`), `.gitattributes` (create:
  `src/evalyn/ui/static/** -text`)

**Interfaces:**
- Consumes: `ui/models.py` (Task 1) — `types.ts` mirrors it exactly.
- Produces: `npm run build` emitting to `../src/evalyn/ui/static/`; `npm run test` (Vitest);
  MSW handlers for every endpoint in the contract.

- [ ] **Step 1: Scaffold.** Vite + React 18 + TS + Tailwind. `vite.config.ts` MUST set
  `base: "./"` (relative asset URLs) and `build.sourcemap: false` (the biggest source of
  cross-machine diff noise), with `build.outDir: "../src/evalyn/ui/static"` and `emptyOutDir: true`.
- [ ] **Step 2: Pin the toolchain.** `ui/.nvmrc` with an **exact** version (`22.18.0`, matching the
  dev machine). Commit `package-lock.json`. CI will use `npm ci`, never `npm install`.
- [ ] **Step 3: Write `types.ts` by hand from `models.py`** and add a Vitest test asserting the enum
  member arrays match the Python ones verbatim (paste them as literals — a drift here silently breaks
  every page).
- [ ] **Step 4: Add MSW handlers** returning the Task-1 fixtures, so tasks 8/9/15/16/17 can build
  against a working API before the backend lands.
- [ ] **Step 5: Verify `npm ci && npm run build` produces `src/evalyn/ui/static/index.html`** plus at
  least one `static/assets/*.js`. **Do not gitignore `static/`** — hatchling respects `.gitignore`
  and a gitignored bundle would silently ship empty.
- [ ] **Step 6: Commit** the scaffold **and** the first real build output:
  `feat(ui): vite/react scaffold and committed bundle`.

---

### Task 6: `evalyn ui` command + app skeleton

**Files:**
- Create: `src/evalyn/ui/server.py`, `tests/ui/test_server.py`, `tests/ui/conftest.py`
- Modify: `src/evalyn/cli.py` (new `ui` command), `pyproject.toml` (the `[ui]` extra)
- Test: add the import-isolation guard to `tests/test_smoke.py`

**Interfaces:**
- Consumes: `ui.index` (T3), `ui.redact` (T4), the committed bundle (T5).
- Produces: `create_app(runs_dir: Path, packs: list[Path], *, allow_discover: bool = False) -> FastAPI`;
  `serve(...) -> None`; CLI `evalyn ui [--port N] [--runs-dir D] [--target P]... [--allow-discover]
  [--no-open]`.

- [ ] **Step 1: Add the extra** to `pyproject.toml`:
  `[project.optional-dependencies] ui = ["fastapi>=0.119", "uvicorn>=0.30"]` — **no `sse-starlette`**
  (starlette is already present; SSE is ~30 lines) and **no `uvicorn[standard]`**.
- [ ] **Step 2: Write the failing tests** using `httpx.ASGITransport` + `httpx.AsyncClient` — **never
  `fastapi.testclient`**. Assert: `GET /api/meta` returns version + runs_dir + a `redaction.enabled:
  true`; `GET /api/health` returns 200; an unknown `/api/*` path returns the **error envelope** shape,
  not FastAPI's `{"detail": …}`; `GET /` serves `index.html`; an unknown non-API path also serves
  `index.html` (SPA history fallback).
- [ ] **Step 3: Run — expect FAIL.** `uv run pytest tests/ui/test_server.py -v`.
- [ ] **Step 4: Implement `create_app`.** Mount `RedactingRoute` on the `/api` router; mount the
  static dir; register an exception handler producing the error envelope. Bind is **127.0.0.1 only** —
  any other `--host` is refused.
- [ ] **Step 5: Implement the CLI command** with a lazy import inside the body:
  `try: from evalyn.ui.server import serve` / `except ImportError:` → print
  `"evalyn ui: setup error: the UI extra is not installed. Install it with: pip install 'evalyn[ui]'"`
  and `raise typer.Exit(2)`. Test that branch by **monkeypatching the import** — a `skipif` marker
  would never fire, since inspect_ai already pulls fastapi in.
- [ ] **Step 6: Add the import-isolation guard** to `tests/test_smoke.py` as a **subprocess** run:
  `python -c "import evalyn.cli, sys; assert 'fastapi' not in sys.modules and 'uvicorn' not in sys.modules"`.
  In-process would be worthless once another test imports the server.
- [ ] **Step 7: Both colour modes + lint**, then commit: `feat(ui): evalyn ui command and app skeleton`.
- [ ] **Step 8: CI stage S0** — change `uv sync` to `uv sync --extra ui` in the `tests` job.

---

### Task 7: Read endpoints

**Files:**
- Modify: `src/evalyn/ui/server.py`
- Create: `tests/ui/test_read_endpoints.py`

**Interfaces:**
- Consumes: `RunIndex` (T3), `evaluate_gate`, `render_compare_report`, `render_discovery_report`.
- Produces: `GET /api/runs`, `/api/runs/{run_id}`, `/api/runs/{run_id}/gate`,
  `/api/runs/{run_id}/report`, `/api/runs/{run_id}/trials/{probe_id}/{epoch}`.

- [ ] **Step 1: Write the failing tests.** (a) `/api/runs` over the fixture dir returns all four rows
  with the legacy one `degraded`; (b) `/api/runs/{id}` on the gate fixture returns
  `capabilities.trial_records: true`, and on the legacy fixture `false`; (c) `/api/runs/{id}/gate`
  calls the real `evaluate_gate` and returns `exit_code`/`failures`/`report_md`; (d)
  `/api/runs/{id}/trials/{probe}/{epoch}` returns turns from `trial_records`, and **404s with the
  error envelope** when `trial_records` is empty; (e) a `run_id` containing `../` is rejected
  **before** any filesystem touch.
- [ ] **Step 2: Run — expect FAIL.** `uv run pytest tests/ui/test_read_endpoints.py -v`.
- [ ] **Step 3: Implement.** Every path parameter is resolved and `Path.is_relative_to`-checked
  against its root. `evaluate_gate` is called here (lazily), never in `RunIndex.list`.
- [ ] **Step 4: Extend the route-table test** from Task 4 — the new routes must all be `RedactingRoute`.
- [ ] **Step 5: Both colour modes + lint**, then commit: `feat(ui): read endpoints over runs/`.

---

### Task 8: App shell + runs table

**Files:**
- Create: `ui/src/App.tsx`, `ui/src/components/{AppShell,RunsTable,RunStatusChip,DegradedRow,RedactionBanner}.tsx`,
  `ui/src/routes.tsx`, `ui/src/api/client.ts`, `ui/src/components/__tests__/RunsTable.test.tsx`

**Interfaces:**
- Consumes: `types.ts` + MSW handlers (T5), `/api/runs` (T7).
- Produces: routes `/runs`, `/runs/:id`; `useRuns()` TanStack Query hook.

- [ ] **Step 1: Write the failing Vitest test.** `RunsTable` given the four fixture rows renders four
  rows; the degraded row renders `DegradedRow` with the reason in a tooltip and **no** metric cells;
  the status chip text matches `RunStatus`.
- [ ] **Step 2: Run — expect FAIL.** `cd ui && npm run test -- --run`.
- [ ] **Step 3: Implement** the shell (sidebar: Runs · Launch · Discoveries · Compare · Trends ·
  Judge Trust), the table, the chip, and `RedactionBanner` (always visible when
  `meta.redaction.enabled`).
- [ ] **Step 4: Verify against the real server** — `evalyn ui --no-open` and confirm the 82-row list
  renders with 27 greyed rows.
- [ ] **Step 5: Rebuild the bundle** (`npm run build`) and commit source **and** bundle together:
  `feat(ui): app shell and runs table`.

---

### Task 9: Gate run detail + transcript viewer

**Files:**
- Create: `ui/src/pages/GateRunDetail.tsx`,
  `ui/src/components/{ScenarioTable,TranscriptViewer,VerdictBadge,CheckEvidence,CostChip}.tsx`,
  plus `__tests__` for `TranscriptViewer` and `VerdictBadge`

**Interfaces:**
- Consumes: `/api/runs/{id}`, `/gate`, `/trials/{probe}/{epoch}` (T7).
- Produces: `TranscriptViewer` with an annotations prop — **one implementation**, reused by
  Discoveries (T15), Trust (T17) and the live view (T21).

- [ ] **Step 1: Write the failing tests.** `VerdictBadge` renders all four tiers including
  `abstained`; `TranscriptViewer` renders turns in order, highlights a check's evidence span, and
  shows a `RedactedChip` when `redacted: true`; the gate banner shows PASS/FAIL from `exit_code`.
- [ ] **Step 2: Run — expect FAIL.** `cd ui && npm run test -- --run`.
- [ ] **Step 3: Implement.** `ScenarioTable` rows drill into `k` trials; `CostChip` shows
  `judge_usd` against the pack ceiling (the 4d amendment freebie).
- [ ] **Step 4: Disable affordances off `capabilities`, never truthiness** — the legacy artifacts have
  no `trial_records` and their rows must show a disabled drill-down with an explanatory tooltip.
- [ ] **Step 5: Rebuild + commit:** `feat(ui): gate run detail and transcript viewer`.

---

### Task 10: Packaging + wheel proof

**Files:**
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`
- Create: `tests/ui/test_packaging.py`

**Interfaces:**
- Consumes: the committed bundle (T5).
- Produces: a wheel containing `evalyn/ui/static/**`; CI jobs `ui-frontend` (drift, advisory) and
  `wheel-clean-install`.

- [ ] **Step 1: Add the artifacts directive.** `[tool.hatch.build.targets.wheel] packages =
  ["src/evalyn"]` **plus** `artifacts = ["src/evalyn/ui/static/**"]`. Use `artifacts`, **not**
  `force-include` (that maps paths from *outside* the package).
- [ ] **Step 2: Write the failing test.** `tests/ui/test_packaging.py` runs `uv build`, opens the
  wheel as a zipfile, and asserts `evalyn/ui/static/index.html` and ≥1 `evalyn/ui/static/assets/*.js`
  are present. Mark it `ui` and `slow`.
- [ ] **Step 3: Run — expect FAIL** if the bundle is missing from the wheel.
- [ ] **Step 4: Add CI stage S2** — an `ui-frontend` job (Node only, `cache: npm` keyed on
  `ui/package-lock.json`, `node-version-file: ui/.nvmrc`) running `npm ci`, `npm run test -- --run`,
  `npm run build`, then a **path-scoped** `git diff --exit-code -- src/evalyn/ui/static` with
  **`continue-on-error: true`**. A bare `git diff` would trip over the suite's writes into `logs/`.
  The job uploads its rebuilt `static/` as an artifact.
- [ ] **Step 5: Add CI stage S5** — `wheel-clean-install`: `uv build`, install
  `dist/evalyn-*.whl[ui]` into a fresh venv, assert the bundle is on disk under `site-packages`, run
  `evalyn ui --port 0 --no-open` and kill it. Prove Node-independence with `env -i`, not by absence —
  ubuntu images ship Node.
- [ ] **Step 6: Both colour modes + lint**, then commit: `feat(ui): package the SPA bundle in the wheel`.

> **★ Stage boundary — the safe demo.** `pip install -e '.[ui]'`, browse every artifact, read a gate
> verdict, drill into a transcript. If everything below is cut, this still ships.

---

### Task 11: Pack endpoints

**Files:**
- Modify: `src/evalyn/ui/server.py`
- Create: `tests/ui/test_pack_endpoints.py`

**Interfaces:**
- Consumes: `targets.loader.load_pack`, `engine.validate.validate_pack`.
- Produces: `GET /api/packs`, `POST /api/packs/{pack_id}/validate`, `GET /api/packs/{pack_id}/axes`.

- [ ] **Step 1: Write the failing tests.** `/api/packs` lists only packs passed to `create_app` via
  `--target`; a `pack_id` not in that set 404s **without touching the filesystem** (the guard that
  stops a browser naming an arbitrary path); `/validate` returns the real `ValidationReport` fields;
  `/axes` returns objectives, personas and playbooks for `packs/example`.
- [ ] **Step 2: Run — expect FAIL.** `uv run pytest tests/ui/test_pack_endpoints.py -v`.
- [ ] **Step 3: Implement.** `pack_id` is an index into the allowlist built at server start — never a
  path from the request.
- [ ] **Step 4: Extend the route-table test.** Both colour modes + lint, then commit:
  `feat(ui): pack discovery and validation endpoints`.

---

### Task 12: Discover findings endpoints

**Files:**
- Create: `src/evalyn/ui/discoveries.py`, `tests/ui/test_discoveries.py`
- Modify: `src/evalyn/ui/server.py`

**Interfaces:**
- Consumes: `emit.load_prior_discoveries`, `DiscoveryArtifact.from_dict`, `Redactor` (T4).
- Produces: `parse_provenance(text: str) -> dict[str, str]`;
  `GET /api/discoveries`, `GET /api/discoveries/{probe_id}`.

- [ ] **Step 1: Write the failing tests.** (a) `parse_provenance` extracts all eight keys
  (`objective`, `persona`, `playbook`, `agent_model`, `stop_reason`, `usd_estimated`, `confirmation`,
  `turns`) from a **comment header** — provenance is not in the YAML body; (b) a file with no header
  returns `{}` rather than raising; (c) `/api/discoveries` joins the staged `Probe` with its
  `DiscoveryArtifact.findings[]` entry to supply `confirmed` and the replay verdict, which are
  **absent from the YAML**; (d) **the PII test** — request `/api/discoveries/{id}` for a finding whose
  `not_contains` value is a sentinel address and assert that address is **absent** from the response
  body; (e) with a valid reveal token it is **present**.
- [ ] **Step 2: Run — expect FAIL.** `uv run pytest tests/ui/test_discoveries.py -v`.
- [ ] **Step 3: Implement the parser and the join.** Warn-and-skip unparseable files, mirroring
  `load_prior_discoveries`.
- [ ] **Step 4: Wire reveal.** Token minted at server start, held on `app.state`, required in an
  `X-Evalyn-Reveal` header, logged to stderr with the probe id. **No global off switch, no env var.**
- [ ] **Step 5: Both colour modes + lint**, then commit: `feat(ui): discover findings endpoints`.

---

### Task 13: Compare + trends endpoints

**Files:**
- Create: `src/evalyn/ui/aggregate.py`, `tests/ui/test_aggregate.py`
- Modify: `src/evalyn/ui/server.py`

**Interfaces:**
- Consumes: `CompareArtifact.from_dict`, `RunIndex` (T3).
- Produces: `GET /api/compare/{run_id}`, `GET /api/trends?pack&metric`;
  `build_trends(summaries, metric) -> list[TrendSeries]`.

- [ ] **Step 1: Write the failing tests.** (a) `/api/compare/{id}` over the synthetic fixture returns
  per-category W/L/T, `flip_rate`, hard metrics **beside** verdicts, and sets a banner flag when
  `rubric_scores_untrusted`; (b) `build_trends` groups by `probe_id` across runs sorted by
  `created_at`, and **skips degraded runs entirely** rather than emitting null points; (c) a pack with
  one run yields a single-point series and does not raise.
- [ ] **Step 2: Run — expect FAIL.** `uv run pytest tests/ui/test_aggregate.py -v`.
- [ ] **Step 3: Implement.** Trends reads only `RunSummary`-level data — never re-opens `.eval` logs.
- [ ] **Step 4: Both colour modes + lint**, then commit: `feat(ui): compare scoreboard and trends endpoints`.

---

### Task 14: Judge-trust endpoint

**Files:**
- Modify: `src/evalyn/ui/server.py`, `src/evalyn/ui/aggregate.py`
- Create: `tests/ui/test_trust.py`

**Interfaces:**
- Consumes: `engine.calibrate.load_record` (:195), `engine.calibrate.is_stale` (:259).
- Produces: `GET /api/trust?pack` → `TrustReport`.

- [ ] **Step 1: Write the failing tests.** (a) over a **copied** calibration record (never the real
  `packs/twincore/calibration.json`), the endpoint returns `judge_model`, overall `agreement`,
  `per_rubric_agreement` and `per_criterion_counts`; (b) mutating a rubric hash makes `stale: true`
  with a non-null `stale_reason`; (c) a pack with no `calibration.json` returns 200 with
  `agreement: null` and a "never calibrated" reason — **not** a 404, since that is a legitimate state.
- [ ] **Step 2: Run — expect FAIL.** `uv run pytest tests/ui/test_trust.py -v`.
- [ ] **Step 3: Implement.** Report **±1-point agreement as shipped** — no Cohen's κ, and the field
  must be named `agreement`, not `kappa`, so nothing implies a certification that is not computed.
- [ ] **Step 4: Both colour modes + lint**, then commit: `feat(ui): judge-trust endpoint`.

---

### Task 15: Discoveries page

**Files:**
- Create: `ui/src/pages/{Discoveries,FindingDetail}.tsx`,
  `ui/src/components/{RedactedChip,RevealModal}.tsx`, `__tests__/FindingDetail.test.tsx`

**Interfaces:**
- Consumes: `/api/discoveries*` (T12), `TranscriptViewer` (T9).

- [ ] **Step 1: Write the failing test.** The finding detail renders objective, confirmed state,
  replay verdict and provenance; redacted values render as `RedactedChip`, **never** raw; the reveal
  button opens a confirm modal and only then sends `X-Evalyn-Reveal`.
- [ ] **Step 2: Run — expect FAIL.** `cd ui && npm run test -- --run`.
- [ ] **Step 3: Implement.** The staged probe YAML is shown as structured fields, not raw text.
- [ ] **Step 4: Manual check against the real TwinCore findings** — confirm the email is **not**
  visible by default, then reveal deliberately and confirm the stderr log line appears.
- [ ] **Step 5: Rebuild + commit:** `feat(ui): discover findings page with default-on redaction`.

---

### Task 16: Compare + trends pages

**Files:**
- Create: `ui/src/pages/{CompareScoreboard,Trends}.tsx`,
  `ui/src/components/{ScoreboardTable,TrendChart}.tsx`, `__tests__/ScoreboardTable.test.tsx`

**Interfaces:**
- Consumes: `/api/compare/{id}`, `/api/trends` (T13). Recharts.

- [ ] **Step 1: Write the failing test.** `ScoreboardTable` renders W/L/T per category, shows hard
  metrics beside verdicts, and displays the untrusted-rubric banner when flagged.
- [ ] **Step 2: Run — expect FAIL.** `cd ui && npm run test -- --run`.
- [ ] **Step 3: Implement** both pages; `TrendChart` annotates gate failures on the series.
- [ ] **Step 4: Rebuild + commit:** `feat(ui): compare scoreboard and trends pages`.

---

### Task 17: Judge Trust page

**Files:**
- Create: `ui/src/pages/JudgeTrust.tsx`, `ui/src/components/AgreementBadge.tsx`,
  `__tests__/AgreementBadge.test.tsx`

**Interfaces:**
- Consumes: `/api/trust` (T14).

- [ ] **Step 1: Write the failing test.** `AgreementBadge` renders below/above the 85% threshold
  distinctly; a stale record renders the "rubric changed" banner; a never-calibrated pack renders an
  empty state rather than an error.
- [ ] **Step 2: Run — expect FAIL.** `cd ui && npm run test -- --run`.
- [ ] **Step 3: Implement.** Label the number **"agreement (±1)"** everywhere — never "κ".
- [ ] **Step 4: Rebuild + commit:** `feat(ui): judge trust page`.
- [ ] **Step 5: CI stage S3** — flip the drift step to `continue-on-error: false`.

> **★ Stage boundary — the differentiator demo.** Findings with PII redacted and a deliberate reveal,
> compare scoreboard, trends, and the calibration story on screen.

---

### Task 18: `engine/events.py` + instrumentation

**Files:**
- Create: `src/evalyn/engine/events.py`, `tests/engine/test_events.py`,
  `tests/engine/test_events_noop.py`
- Modify: `src/evalyn/engine/{run.py,solver.py,task_builder.py,compare.py}`,
  `src/evalyn/discovery/{run.py,solver.py,loop.py}`, `src/evalyn/cli.py` (`--events`)

**Interfaces:**
- Consumes: `ui.paths.events_path` (T2).
- Produces: `EventSink` Protocol with `emit(type: str, /, **fields) -> None`; `NullSink`;
  module singleton `NULL_SINK`; `JsonlSink(path, *, run_id, mode)` with `.emit`/`.close`.
  `build_task(..., sink: EventSink = NULL_SINK)`, `session_solver(pack, *, sink=NULL_SINK)`.

- [ ] **Step 1: Write the sink tests.** `seq` starts at 1 and is strictly increasing across threads
  (spawn 8 threads × 50 emits, assert 400 unique contiguous seqs and that file order equals seq
  order); a reader skips a deliberately torn trailing line; `emit` swallows an `OSError`, warns
  **`UserWarning`** once (never `RuntimeWarning` — the suite runs `-W error::RuntimeWarning`), and
  self-demotes; reopening with a different pid raises.
- [ ] **Step 2: Write the four no-op tests** in `test_events_noop.py`: (1) **discriminating RED** — an
  `_ExplodingSink` whose `emit` raises makes each of the three modes raise, proving the call sites
  exist; (2) **constructor interdiction** — monkeypatch `JsonlSink` to a sentinel that raises, run all
  three modes on default paths, assert it is never constructed; (3) no `*.events.jsonl` or
  `*.control.json` after a default run; (4) artifact equality between a default run and an explicit
  `NULL_SINK` run, after blanking `created_at`/`log_path`.
- [ ] **Step 3: Run — expect FAIL.** `uv run pytest tests/engine/test_events.py tests/engine/test_events_noop.py -v`.
- [ ] **Step 4: Implement `events.py`.** `threading.Lock` (not asyncio — gate emits on Inspect's loop
  thread, discover from an `asyncio.to_thread` worker). `buffering=1` + explicit `flush()`, no `fsync`.
- [ ] **Step 5: Instrument, passing the sink as a constructor argument** (never a ContextVar — explicit
  passing is what makes step 2 provable). `run.py`: `run.started`/`spend.updated`/`artifact.written`/
  `run.finished`; `solver.py`: `trial.started`/`turn.sent`/`turn.received`/`trial.finished`;
  `reduce_log_to_probes`: `probe.scored` (post-hoc); `compare.py:_judge`: `pair.judged`;
  `discovery/loop.py:_drive`: `agent.step`/`agent.reply`/`confirm.result`; `discovery/run.py`:
  `finding.staged`/`replay.result`. Every trial event carries `trial_key = f"{probe_id}#{epoch}"`;
  every hunt event carries `hunt_key`.
- [ ] **Step 6: Add `--events` to `gate`/`compare`/`discover`.** Absent ⇒ `NULL_SINK`.
- [ ] **Step 7: Full suite in both colour modes — 726 + new, warning-clean** and lint, then commit:
  `feat(engine): opt-in event stream with a provable no-op default`.

---

### Task 19: `engine/control.py` — pause / resume / cancel

**Depends on Task 0's findings.** If the spike answered Q2 "no", cut pause/resume per §9 of the spec
and implement cancel as an artifact flag only.

**Files:**
- Create: `src/evalyn/engine/control.py`, `tests/engine/test_control.py`
- Modify: `src/evalyn/engine/{run.py,task_builder.py}`, `src/evalyn/discovery/{loop.py,run.py}`,
  `src/evalyn/engine/compare.py`, `src/evalyn/cli.py`

**Interfaces:**
- Consumes: `EventSink` (T18), `ui.paths.control_path` (T2).
- Produces: `RunCancelled(Exception)`; `RunController(path, sink, *, poll_seconds=0.25,
  ack_timeout=60.0)` with `.request(action)`, `async .checkpoint(*, key)`, `.cancelled` property, and
  `.as_early_stopping() -> EarlyStopping`. `RunArtifact.cancelled: bool = False`.

- [ ] **Step 1: Write the failing tests.** (a) writing `pause` then `resume` to the control file makes
  `schedule_sample` block then return `None`, and the artifact is **equal** to an unpaused run
  (mutation guard: a 2 s pause must change nothing but wall time); (b) writing `cancel` makes
  `schedule_sample` return `EarlyStop`, the run's artifact carries `cancelled=True`, and the CLI exits
  **3**; (c) a cancelled gate run **never** exits 0 — assert even when every completed probe passed;
  (d) `--update-baseline` **refuses** a cancelled artifact, joining the existing `problems` list at
  `cli.py:118-131`. Note the zero-trials entry already catches the common case, so make the test
  discriminating by cancelling **after** every probe has scored — only an explicit `cancelled` entry
  refuses that; (e) in discovery, `RunCancelled` is caught **before** the blanket `except Exception`
  (`loop.py:408`, `run.py:490`) so `stop_reason == "cancelled"`, never `"error"`.
- [ ] **Step 2: Run — expect FAIL.** `uv run pytest tests/engine/test_control.py -v`.
- [ ] **Step 3: Implement `RunController`.** Control file read via `stat` mtime first, re-read only on
  change. The `control.paused`/`control.cancelled` **event is the ack**.
- [ ] **Step 4: Feature-detect `early_stopping`.** Pass it only when a controller exists; check
  `inspect.signature(Task).parameters` and degrade with a loud warning if absent. Tighten the pin to
  `inspect_ai>=0.3.249,<0.4`.
- [ ] **Step 5: Add `RunArtifact.cancelled`** — additive with a default (the established pattern, cf.
  `expected_trials`, `eval_status`). Add a round-trip test loading a **pre-#4** artifact dict, since
  `from_dict` raises on unknown keys (`run.py:104-110`).
- [ ] **Step 6: Wire the discover and compare poll points** — `loop._drive`'s BOUNDS-FIRST block
  beside `meter.exhausted()`, and before each `_replay_finding`; `compare._judge` before its
  semaphore.
- [ ] **Step 7: Full suite both colour modes + lint**, then commit:
  `feat(engine): pause/resume/cancel via Inspect early_stopping`.

---

### Task 20: Launcher + control + SSE endpoints

**Files:**
- Create: `src/evalyn/ui/launcher.py`, `src/evalyn/ui/stream.py`,
  `tests/ui/test_launcher.py`, `tests/ui/test_stream.py`
- Modify: `src/evalyn/ui/server.py`, `pyproject.toml` (`pytest-timeout` in dev deps)

**Interfaces:**
- Consumes: `RunController` (T19), `events_path`/`control_path` (T2), `RunIndex` (T3).
- Produces: `build_argv(req: LaunchRequest) -> list[str]`; `RunLauncher` with `.launch`, `.control`,
  `.reap`; `sse_frame(record: dict) -> str`; `async event_stream(path, *, last_id, idle_timeout)`;
  `POST /api/runs`, `POST /api/runs/{id}/control`, `GET /api/runs/{id}/events`, `/stderr`.

- [ ] **Step 1: Write the SSE tests as three escalating cases** — **this is the test that can hang the
  suite.** (1) `sse_frame` **pure and sync**: `id:`/`event:`/`data:` framing, `Last-Event-ID` resume
  skipping `seq <= N`, an unparseable line skipped, a torn trailing line buffered not crashed. (2)
  **replay-only** over a fixture already ending in `run.finished` — cannot hang by construction. (3)
  **live tail**: a writer task appends three events on 50 ms delays, with **three independent stops** —
  return on `run.finished`, a production **idle timeout** emitting `: idle-timeout` and returning, and
  the test wrapped in `asyncio.wait_for(…, 10)`. Add a fourth for **early client disconnect**, the
  path that leaks tasks in production.
- [ ] **Step 2: Write the launcher tests.** `build_argv` is pure — table-test all three modes; the
  server **refuses a pack path in the body** (only allowlisted `pack_id`); `discover` launch without
  `--allow-discover` returns 400 `launch_refused`; a `discover` request asking for more than
  `pack.spec.budget.max_usd_per_run` is **clamped down**, never up; a second concurrent launch returns
  409 `busy`; the launch response's `run_id` equals the stem of the artifact that later appears.
- [ ] **Step 3: Run — expect FAIL.** `uv run pytest tests/ui/test_stream.py tests/ui/test_launcher.py -v`.
- [ ] **Step 4: Implement.** Spawn `sys.executable -m evalyn` (not a bare `evalyn` on PATH) with
  `start_new_session=True`, `EVALYN_RUN_ID` in the env, stderr to the sidecar. Cancel escalates to
  `SIGTERM` on the **process group** after 60 s unacknowledged, **after** writing `cancel` to the
  control file; **never `SIGKILL`** (it loses the Inspect log).
- [ ] **Step 5: Add `pytest-timeout` to dev deps** and pass `--timeout=120` **in CI only**, so a hang
  is a red instead of a six-hour job.
- [ ] **Step 6: Extend the route-table test.** Both colour modes + lint, then commit:
  `feat(ui): run launcher, control channel and SSE streaming`.

---

### Task 21: Live SPA layer, e2e, docs, release

**Files:**
- Create: `ui/src/hooks/useRunEvents.ts`, `ui/src/pages/Launch.tsx`,
  `ui/src/components/{LiveBanner,ControlButtons}.tsx`,
  `ui/src/hooks/__tests__/runEventsReducer.test.ts`, `ui/e2e/smoke.spec.ts`
- Modify: `README.md`, `docs/CONTEXT.md`, `docs/ROADMAP.md`, `docs/JOURNAL.md`,
  `docs/EVALYN_EXPLAINED.md`, `pyproject.toml` (version), `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: everything above.
- Produces: `runEventsReducer(state, event) -> State` exported **pure** (so Vitest needs no DOM);
  `useRunEvents(runId)`.

- [ ] **Step 1: Write the reducer tests.** Pure, no DOM: events apply in `seq` order; a replayed event
  with `seq <= lastSeq` is **idempotent** (this matters because the same endpoint replays history for
  finished runs); `run.finished` sets a terminal status; a gap in `seq` sets `connection:
  'reconnecting'`.
- [ ] **Step 2: Run — expect FAIL.** `cd ui && npm run test -- --run`.
- [ ] **Step 3: Implement** `useRunEvents` over `EventSource` with `Last-Event-ID` reconnect, the
  Launch page (mode toggle, pack picker from `/api/packs`, required max-USD for discover, type-to-
  confirm pack name), `ControlButtons`, and the live variant of `GateRunDetail`.
- [ ] **Step 4: Write the Playwright smoke** (chromium only): start `evalyn ui`, launch a gate run
  against the toy target, watch it reach a terminal state, open a transcript, open Discoveries and
  assert the sentinel address is **absent**.
- [ ] **Step 5: CI stage S4** — add the `ui-e2e` job, `if: github.event_name == 'pull_request'`, with
  Playwright browsers cached on `~/.cache/ms-playwright`.
- [ ] **Step 6: Docs + version.** Document `evalyn ui` in `README.md` (including that redaction is
  default-on and reveal is deliberate), update `CONTEXT.md` and `ROADMAP.md`, add the Plan #4 journal
  section, bump to **v0.5.0** and update the version-guard test.
- [ ] **Step 7: Full suite both colour modes + lint + wheel test**, then commit:
  `feat(ui): live run streaming, launch page, e2e smoke; docs; v0.5.0`.

---

## Acceptance

Run before requesting the PR to `dev`:

1. **Suite** ≥ 726 + new tests, green and **warning-clean** in both colour modes:
   `uv run pytest -q -W error::RuntimeWarning` and the same under `FORCE_COLOR=1`.
   `uv run ruff check src/ tests/` clean.
2. `uv run evalyn validate-pack --target packs/example` and `--target packs/twincore` both exit 0.
3. **No-op proof** — the four `test_events_noop.py` tests pass, and a `gate` run **without**
   `--events` writes no `*.events.jsonl` or `*.control.json` and produces an artifact equal (modulo
   `created_at`/`log_path`) to one produced before this branch.
4. **Import isolation** — the subprocess guard shows `import evalyn.cli` loads neither `fastapi` nor
   `uvicorn`.
5. **Packaging** — `uv build`, then `pip install 'dist/evalyn-*.whl[ui]'` into a clean venv; the
   bundle is present under `site-packages`; `evalyn ui --port 0 --no-open` starts. Node-independence
   proven with `env -i`.
6. **Redaction** — the route-table test asserts every `/api` route is redacting except exactly
   `/api/meta` and `/api/health`; an end-to-end assertion that the TwinCore PII finding's address
   never appears in any default response body.
7. **Legacy tolerance** — `RunIndex` over the real 82-file `runs/` returns 82 rows, 27 `degraded`,
   raising nothing.
8. **Live path** — browser-launch a gate run against the toy target; it appears as `running` and
   reaches `passed`, and the artifact lands at the `run_id` the browser predicted.
9. **Cancel** — cancel mid-run; exit code **3**, `cancelled=True`, and `--update-baseline` refuses it.
10. **Never `git add .`** — every commit staged explicitly; `.claude/` stays untracked.

**Outside this plan, on the demo critical path:** create a committed twincore baseline (user-gated
live spend). The demo's closing red-diff beat has nothing to diff against today —
`ci/baseline-example.json` is the only tracked baseline and `runs/baseline.json` is unloadable.
