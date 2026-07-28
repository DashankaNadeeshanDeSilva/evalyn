# Evalyn-pro Plan #4d — Local Web UI (Cockpit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `evalyn ui` — a local web cockpit for launching, controlling (pause/resume/cancel), live-watching, and interactively exploring Evalyn-pro runs, including review-queue labeling, run diff, trends, and the Judge Trust dashboard.

**Architecture:** Engine grows a UI-agnostic JSONL event stream + a control file (drain-and-hold); a FastAPI server (behind the `evalyn[ui]` extra) is stateless over `runs/`, tails events into SSE, and spawns `evalyn gate` subprocesses; a prebuilt React SPA (Vite + TS + Tailwind + Recharts) ships inside the wheel. Spec: `docs/superpowers/specs/2026-07-24-evalyn-pro-ui-design.md`.

**Tech Stack:** Python 3.12, `uv`, FastAPI + uvicorn + sse-starlette (or hand-rolled SSE — Task 0 decides by dependency weight), pytest; Node 22 (contributors only), Vite + React 18 + TypeScript + Tailwind + shadcn subset + TanStack Query + React Router + Recharts, Vitest, Playwright.

**Sequencing:** Execute after Plan #4c merges. Branch: `feat/pro-ui` off `dev`.

## Global Constraints

- **Parity rule:** every UI action maps to a CLI-visible artifact (subprocess invocation, control file, labels file). The server never re-implements engine logic — it calls the same functions/CLI the terminal user has.
- Server binds `127.0.0.1` ONLY in v1; any other `--host` is refused with an error naming the deferred feature.
- Event emitter is a no-op unless enabled — CLI-only users pay zero cost.
- A cancelled or invalid run is NEVER rendered as passed; status chips commit only on engine-emitted events (optimistic UI allowed, but the engine's event is authoritative).
- SPA bundle is fully self-contained (no external requests); built output committed at `src/evalyn/ui/static/` with a CI drift check.
- `fastapi`/`uvicorn`/SSE deps live behind the `[ui]` optional extra; `evalyn ui` without the extra prints an actionable install hint and exits 2.
- Test-first; `uv run pytest -q` + `uv run ruff check src/` (and `npm test` in `ui/` once it exists) before every commit; ask the user before every commit/push/PR; user-name-only commit identity.

---

### Task 0: Re-baseline against post-#4c code

**Files:** read-only pass over `src/evalyn/engine/run.py` (`run_gate` flow, artifact fields incl. `errored_fraction`), `src/evalyn/engine/solver.py` (scripted + simulated loops, transport layer), `src/evalyn/scoring/` (where per-trial verdicts materialize), `src/evalyn/review/` (#4b queue/label/promote functions), `src/evalyn/cli.py` (commands + exit codes), `pyproject.toml`.

- [ ] **Step 1:** Confirm the run directory layout post-#4c (`manifest.json`, `verdicts.jsonl`, `review_queue.jsonl`, `labels.jsonl`, `report.html`, Inspect log path) — the server reads all of these; record exact names/shapes in this plan.
- [ ] **Step 2:** Decide **where `verdict` events can be emitted live**: if tier-1/2/3 scorers run per-sample during eval (Inspect scores as samples complete), wrap scorers to emit; if scoring is post-hoc, verdict events are emitted during reduction (degraded liveness — document in the plan and spec §2.1 note). Confirm with a spike against Inspect's actual scoring order.
- [ ] **Step 3:** Confirm pause/cancel insertion point: Inspect owns the sample/epoch loop, so control polling lives at `solve()` entry per trial (drain-and-hold: in-flight solves finish, new solves hold/cancel). Verify a raised `RunCancelled` in `solve()` errors remaining samples without aborting the whole eval log, and that `run_gate` can distinguish it from real errors.
- [ ] **Step 4:** Decide SSE dependency (`sse-starlette` vs ~30-line hand-rolled async generator) and pin Node/Vite/React versions available at execution time.
- [ ] **Step 5:** Amend this plan inline where reality diverges; ask user, then commit `docs: re-baseline evalyn-pro plan 4d`.

---

### Task 1: Engine event emitter (`events.py`)

**Files:**
- Create: `src/evalyn/engine/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Produces:

```python
# events.py
"""Append-only JSONL run event stream (spec 4d §2.1). UI-agnostic."""
import contextvars, json, threading
from datetime import datetime, timezone
from pathlib import Path


class EventEmitter:
    def __init__(self, path: Path | None):        # None -> no-op emitter
        self._path, self._seq, self._lock = path, 0, threading.Lock()

    @property
    def enabled(self) -> bool: return self._path is not None

    def emit(self, type: str, **payload) -> None:
        if self._path is None:
            return
        with self._lock:
            self._seq += 1
            rec = {"seq": self._seq,
                   "ts": datetime.now(timezone.utc).isoformat(), "type": type,
                   **payload}
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


_current: contextvars.ContextVar[EventEmitter] = contextvars.ContextVar(
    "evalyn_events", default=EventEmitter(None))

def current_emitter() -> EventEmitter: return _current.get()
def set_emitter(e: EventEmitter): return _current.set(e)
```

Event vocabulary (payload keys fixed here, used by Tasks 2–3 and the server):
`run_started(pack, target_model, sim_model, judge_model, trials, probes)` ·
`scenario_started/finished(probe_id[, reducers])` · `trial_started/finished(probe_id, epoch[, stop_reason, error])` ·
`user_turn/assistant_turn(probe_id, epoch, turn, content, latency_ms)` ·
`trace_event(probe_id, epoch, turn, event)` · `verdict(probe_id, epoch, name, verdict, tier, rationale, confidence)` ·
`run_paused()/run_resumed()` · `run_finished(outcome, totals)` with `outcome ∈ {passed, gate_failed, invalid, cancelled}`.

- [ ] **Step 1: Write failing tests:** no-op emitter writes nothing and `enabled` is False; enabled emitter writes valid JSONL with monotonic `seq` starting at 1; concurrent `emit` from threads keeps seq gapless and lines unmangled (threaded hammer test); contextvar get/set round-trips.
- [ ] **Step 2:** Run `uv run pytest tests/test_events.py -q` — expect FAIL.
- [ ] **Step 3:** Implement as above.
- [ ] **Step 4:** Run — expect PASS; `uv run ruff check src/`.
- [ ] **Step 5:** Ask user, then commit `feat: append-only JSONL run event emitter`.

---

### Task 2: Wire events + control channel into the engine

**Files:**
- Create: `src/evalyn/engine/control.py`
- Modify: `src/evalyn/engine/run.py`, `src/evalyn/engine/solver.py`, scorer modules (per Task 0 Step 2), `src/evalyn/cli.py` (`--events` on `gate`)
- Test: `tests/test_engine_events_integration.py`, `tests/test_control.py`

**Interfaces:**
- Produces:

```python
# control.py
class RunCancelled(Exception): ...

def read_command(run_dir: Path) -> str | None       # "pause"|"resume"|"cancel"|None
async def wait_if_paused(run_dir: Path) -> None:
    """At solve() entry: if control says pause -> emit run_paused once, poll
    (1s) until resume (emit run_resumed) or cancel (raise RunCancelled)."""
```

`run_gate(..., events: bool = False)`: when True, creates the run dir up front, sets
`EventEmitter(run_dir / "events.jsonl")`, emits `run_started` before eval and `run_finished`
after gate-diff (outcome mapped from gate result / error budget / cancellation). Solver emits
`trial_started`, `user_turn`/`assistant_turn` (both loops), `trace_event`, `trial_finished`,
and calls `await wait_if_paused(run_dir)` at `solve()` entry. Cancellation: `RunCancelled`
raised in `solve()` → remaining samples error with a distinguishable error type → `run_gate`
marks the artifact `cancelled` (never gate-passed, exit code = run-invalid family per #4c).
CLI: `evalyn gate PACK --events` enables emission (also usable headless — parity with UI-launched runs).

- [ ] **Step 1: Write failing tests:** full `run_gate(events=True)` against MockTarget produces an events file whose sequence is exactly `run_started → (trial_started → user/assistant turns → trial_finished)+ → verdict* → run_finished(outcome=passed|gate_failed)` with per-probe/epoch tags (adjust expected verdict position per Task 0 Step 2 decision); `events=False` creates no file; control round-trip with a fake slow target — write `pause` mid-run → `run_paused` emitted and no new `trial_started` until `resume` written; write `cancel` → `RunCancelled` path → `run_finished(outcome=cancelled)` and artifact marked cancelled.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement (emitter access via `current_emitter()` — no signature threading through Inspect).
- [ ] **Step 4:** `uv run pytest -q` — full suite green (events default-off path proves zero regression).
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: engine event emission and pause/resume/cancel control channel`.

---

### Task 3: FastAPI server skeleton — `evalyn ui`, runs listing/detail, path safety

**Files:**
- Create: `src/evalyn/ui/__init__.py`, `src/evalyn/ui/server.py`, `src/evalyn/ui/runs_index.py`, `src/evalyn/ui/static/index.html` (placeholder until Task 6)
- Modify: `pyproject.toml` (`[project.optional-dependencies] ui = [...]`), `src/evalyn/cli.py` (`ui` command)
- Test: `tests/test_ui_server.py` (mark `ui`; skipped when extra not installed)

**Interfaces:**
- Produces: `create_app(runs_dir: Path, packs_dir: Path) -> FastAPI`;
  `GET /api/runs` → `[{run_id, status, pack, pass_at_1, pass_k, abstained, errored, cost, started_at, duration, parent_run}]`;
  `GET /api/runs/{id}` → scenario-table payload from the artifact;
  `GET /api/runs/{id}/transcripts/{probe}/{epoch}` → merged transcript (turns + verdicts + trace + perturbation markers, merged server-side in `runs_index.py` from artifact + Inspect log + events file);
  static mount at `/` with SPA fallback. Status derivation: `running` (pid alive), `interrupted` (manifest without finish + pid dead), `failed_to_start`, else from artifact outcome.
  CLI `evalyn ui [--port N] [--runs-dir runs/] [--no-open]`: loopback-only guard, free-port pick, browser open, actionable hint + exit 2 when extra missing.

- [ ] **Step 1: Write failing tests** against two fixture run dirs (one finished, one manifest-only "interrupted"): list endpoint statuses/fields; detail endpoint scenario rows; transcript merge contains turn annotations from fixture verdicts; `GET /api/runs/../../etc` → 404 (traversal guard); missing-extra CLI behavior (monkeypatch import failure).
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `uv run pytest -q` — green (ui tests auto-skip without extra; CI installs the extra).
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: evalyn ui server skeleton with runs API`.

---

### Task 4: SSE streaming + launch/control/rerun endpoints

**Files:**
- Create: `src/evalyn/ui/stream.py`, `src/evalyn/ui/launcher.py`
- Modify: `src/evalyn/ui/server.py`
- Test: `tests/test_ui_stream.py`, `tests/test_ui_launcher.py`

**Interfaces:**
- Produces:

```python
# stream.py
async def event_stream(run_dir: Path, last_event_id: int = 0):
    """Async generator: yield historical events with seq > last_event_id, then
    live-tail (0.25s poll) until run_finished seen or client disconnects.
    Incomplete trailing line -> wait; malformed line -> skip + log warning."""

# launcher.py
def launch_run(pack: str, runs_dir: Path, *, trials=None, sim_model=None,
               judge_model=None, tags=None, budget=None) -> dict:
    """Spawn `evalyn gate <pack> --events ...` via subprocess.Popen (stderr to
    runs/<ts>/launch-stderr.log); return {run_id, pid}."""
def is_alive(pid: int) -> bool
def send_control(run_dir: Path, action: str, pid: int) -> None
    # writes control file; for cancel: escalate to SIGTERM if no
    # run_paused/run_finished ack event within 30s (background task)
def rerun_failed(run_id: str, runs_dir: Path) -> dict
    # failed ∪ errored ∪ abstained probe ids from artifact -> launch_run with
    # probe filter + parent_run in manifest
```

Endpoints: `GET /api/runs/{id}/events` (SSE, `Last-Event-ID` honored), `POST /api/runs`,
`POST /api/runs/{id}/control`, `POST /api/runs/{id}/rerun-failed`, `GET /api/packs`,
`POST /api/packs/validate` (wraps `validate_pack`).

- [ ] **Step 1: Write failing tests:** `event_stream` replays a fixture file then picks up lines appended mid-test (live-tail proof) and terminates on `run_finished`; resumes correctly from `last_event_id`; malformed + partial line handling; `launch_run` with a stub `evalyn` script creates run dir and returns live pid; `send_control` writes the file and the SIGTERM escalation fires on a silent stub; `rerun_failed` computes the probe set from a fixture artifact and records `parent_run`; packs validate endpoint surfaces `validate_pack` errors as JSON.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: SSE event streaming, run launch/control/rerun endpoints`.

---

### Task 5: Review, trends, and calibration endpoints

**Files:**
- Create: `src/evalyn/ui/aggregate.py`
- Modify: `src/evalyn/ui/server.py`
- Test: `tests/test_ui_review_api.py`, `tests/test_ui_aggregate.py`

**Interfaces:**
- Produces: `GET /api/review/{run_id}` (queue + existing labels merged); `POST /api/review/{run_id}/label` `{item_id, label, note?}` → same `evalyn.review` save path as CLI (file lock, idempotent per item); `POST /api/review/{run_id}/promote` `{item_id, as: "anchor"|"probe"}` → `{written_path}`; `GET /api/trends?pack=NAME` → per-probe + per-dimension series across all runs of that pack `[{run_id, started_at, values...}]` (computed in `aggregate.py`, artifacts only — no Inspect log reads); `GET /api/calibration?pack=NAME` → #4b calibration record + per-dimension staleness (recompute rubric hashes, compare) + anchor counts + worst disagreements with `{probe_id, epoch}` pointers for deep links.

- [ ] **Step 1: Write failing tests:** label via API then via CLI function → single consistent labels file (concurrency/idempotency); promote returns a path that exists and parses; trends over 3 fixture runs orders by `started_at` and carries pass^k per probe; calibration endpoint flags a stale dimension when the fixture rubric hash differs.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: review, trends and calibration APIs`.

---

### Task 6: SPA scaffold + Runs/Launch/Run Detail with live streaming

**Files:**
- Create: `ui/` (Vite + React + TS project: `package.json`, `vite.config.ts` with build outDir `../src/evalyn/ui/static`, Tailwind config, `src/main.tsx`, `src/App.tsx`, `src/api.ts`, `src/hooks/useRunEvents.ts`, `src/components/{TranscriptViewer,ScenarioTable,RunStatusChip,VerdictBadge}.tsx`, `src/pages/{RunsPage,RunDetailPage,LaunchPage}.tsx`), `ui/README.md`
- Create: `.github/workflows/` addition (or Makefile target) for the bundle drift check: `npm ci && npm run build && git diff --exit-code src/evalyn/ui/static`
- Test: `ui/src/hooks/useRunEvents.test.ts` (Vitest)

**Interfaces:**
- Produces: routes `/runs`, `/runs/:id`, `/runs/:id/trial/:probe/:epoch`, `/launch`; the `useRunEvents` reducer contract (consumed by Task 7 pages too):

```typescript
// useRunEvents.ts — reduces SSE events into live view state
export interface LiveRunState {
  status: "connecting" | "running" | "paused" | "finished" | "reconnecting";
  outcome?: "passed" | "gate_failed" | "invalid" | "cancelled";
  scenarios: Record<string, {status: string; trials: Record<number, TrialLive>}>;
}
export interface TrialLive {
  turns: {role: "user" | "assistant"; content: string; turn: number;
          trace?: object[]}[];
  verdicts: {name: string; verdict: string; tier: number; rationale: string}[];
  stopReason?: string;
}
export function useRunEvents(runId: string): LiveRunState
// EventSource with Last-Event-ID resume; "reconnecting" state on error;
// autoscroll pin handled by TranscriptViewer, not the hook.
```

`TranscriptViewer({turns, verdicts, traceByTurn, perturbedTurns, live})` — single component reused by Run Detail (historical + live), Review (Task 7), and Judge Trust deep links.

- [ ] **Step 1:** Scaffold the Vite project; wire build → `src/evalyn/ui/static/`; verify `evalyn ui` serves the built placeholder; add drift check.
- [ ] **Step 2: Write failing Vitest tests for the `useRunEvents` reducer** (pure reducer function extracted from the hook): feeds a scripted event array → expected `LiveRunState` (turn ordering, verdict attachment, paused status, finished outcome); malformed event ignored; resume from mid-sequence.
- [ ] **Step 3:** Implement reducer + hook + the three pages against the Task 3–4 APIs (TanStack Query for REST; Launch form with localStorage recents and inline validate errors; Run Detail with controls wired to `POST /control`, status chip committed only on engine events; TranscriptViewer with evidence highlighting, tier/abstained `VerdictBadge`, trace chips, autoscroll+pin).
- [ ] **Step 4:** `npm test` (Vitest) green; `npm run build`; manual check: `uv run evalyn ui` → launch a MockTarget run from the browser, watch it stream, pause/resume/cancel it, open a finished trial.
- [ ] **Step 5:** Ask user, then commit `feat: SPA scaffold with runs, launch, and live run detail` (bundle included).

---

### Task 7: Review, Diff, Trends, Judge Trust pages

**Files:**
- Create: `ui/src/pages/{ReviewPage,DiffPage,TrendsPage,JudgeTrustPage}.tsx`, `ui/src/components/{DiffTable,KappaBadge}.tsx`
- Test: `ui/src/pages/review.test.tsx` (Vitest, labeling state machine)

**Interfaces:**
- Consumes: Task 5 endpoints; `TranscriptViewer`, `useRunEvents` (Task 6).
- Produces: routes `/review/:runId?`, `/diff/:a/:b`, `/trends`, `/judge-trust`. Review: filterable queue, keyboard flow (`j`/`k`/`p`/`f`/`n`), transcript + rationale side-by-side, promote buttons showing written path, progress bar. Diff: two-run picker (from Runs page buttons), per-scenario/per-dimension deltas, CI-overlap greying, "new failures" / "fixed" groups first. Trends: Recharts lines per probe/dimension with gate-failure markers. Judge Trust: κ/weighted-κ `KappaBadge` per dimension + certification state, staleness banner, confusion tables, worst disagreements → deep link `/runs/:id/trial/:probe/:epoch`, "label more anchors" → `/review/:runId`.

- [ ] **Step 1: Write failing Vitest test** for the review labeling state machine (label → optimistic update → rollback on API error; keyboard navigation order; skip preserves position).
- [ ] **Step 2:** Implement the four pages.
- [ ] **Step 3:** `npm test` green; `npm run build`; manual pass over each page against fixture runs.
- [ ] **Step 4:** Accessibility + dark-mode sweep (keyboard focus order on Review, `prefers-color-scheme` on all pages, chart color contrast).
- [ ] **Step 5:** Ask user, then commit `feat: review, diff, trends and judge-trust pages`.

---

### Task 8: Playwright smoke, packaging polish, docs

**Files:**
- Create: `ui/e2e/smoke.spec.ts`, CI job running it (install `[ui]` extra + Node, build, run server against MockTarget scaffold)
- Modify: `README.md` (UI section + screenshots), `ui/README.md` (contributor guide incl. `evalyn ui --dev` Vite proxy), `docs/JOURNAL.md`, `docs/ROADMAP.md`, `pyproject.toml` (wheel includes `ui/static`)
- Test: the smoke itself

**Interfaces:** none new.

- [ ] **Step 1: Write the Playwright smoke:** `evalyn init` scaffold → start server → launch run from Launch page → assert streaming turns appear → run finishes → open a trial transcript → label one review item → promote to anchor → assert file exists. All against MockTarget/mockllm (no API keys).
- [ ] **Step 2:** Wire the CI job (build bundle, drift check, pytest with `[ui]`, Vitest, Playwright smoke).
- [ ] **Step 3:** Run the full matrix locally: `uv run pytest -q`, `uv run ruff check src/`, `npm test`, `npx playwright test` — all green; verify `uv build` wheel contains `evalyn/ui/static/` and installs+runs in a clean venv without Node.
- [ ] **Step 4:** README/JOURNAL/ROADMAP updates (Evalyn-pro v2 UI delivered; remaining v2 items: dual-control, OTel ingestion, pytest adapter…).
- [ ] **Step 5:** Ask user, then commit `feat: e2e smoke, CI, packaging and docs for evalyn ui`. Then `superpowers:finishing-a-development-branch` (ask before PR).

---

## Acceptance (whole plan)

- Full Python suite + ruff green; Vitest + Playwright green in CI; bundle drift check passing.
- `pip install evalyn[ui]` in a clean venv (no Node) → `evalyn ui` → launch, watch live turns stream, pause/resume/cancel, drill into annotated transcripts — with the engine equally controllable from a plain terminal (`--events` + control file).
- Review labeling and promotion work identically from UI and CLI on the same run.
- Judge Trust page renders κ, certification, staleness, and deep-links disagreements into transcripts.
- Nothing in core Evalyn requires the UI extra; `events=False` paths are byte-identical to pre-#4d behavior.

---

## Amendment (2026-07-28) — Plan #2b additions: cost meter + compare scoreboard

User-requested during Plan #2b brainstorming. **Visual design deliberately NOT locked yet**
— discuss at #4d execution time; the notes below record intent + data contracts only.

### A1. Cost meter (judge spend)

- **Why now:** Plan #2b's first task fixes `judge_usd` metering (read `log.stats.model_usage`
  from the returned EvalLog) — the artifact's `judge_usd` becomes real, and the $5
  `max_usd_per_run` cap becomes enforceable. The UI should surface it.
- **Where:** Runs list (per-run `judge_usd` column), Run Detail (spend vs pack budget cap,
  e.g. `$0.69 / $5.00` with a warning state near cap), and the compare scoreboard (judge
  spend of the comparison itself).
- **Data:** `RunArtifact.judge_usd` + pack `budget.max_usd_per_run`; live-run updates ride
  the Task 1 event stream if a spend event is added (decide at design time — post-run-only
  is an acceptable v1).

### A2. Compare scoreboard (Plan #2b `compare` artifacts)

- **Distinct from DiffPage** (Task 7): DiffPage diffs two *gate* runs (absolute per-scenario
  deltas). The scoreboard renders a #2b **CompareArtifact**: blind pairwise per-category
  win/loss/tie/unsure counts, per-probe/per-criterion verdicts + justifications + `flipped`
  flags, flip→tie rate telemetry, hard-metric deltas (latency mean/p95, tokens,
  invariant-violation counts) shown BESIDE verdicts (never blended), `rubric_scores_untrusted`
  banner, `judge_usd`.
- **Layout intent (user sketch, to be designed later):** an **overview front** (per-category
  W/L/T summary + headline hard-metric deltas + trust banners) with **tabs to hide detail**
  (per-probe verdicts/justifications; flip telemetry; hard metrics; run metadata).
- **Data:** the §2.3 CompareArtifact JSON from `runs/` (see
  `docs/superpowers/specs/2026-07-28-evalyn-plan2b-design.md`); server needs a
  compare-artifact listing/detail endpoint (Task 5 family) and a route like
  `/compare/:artifact`.
