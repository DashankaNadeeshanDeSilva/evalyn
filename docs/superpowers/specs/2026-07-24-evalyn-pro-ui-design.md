# Evalyn-pro Local Web UI (Plan #4d) — Design Spec

**Date:** 2026-07-24
**Status:** Approved design, pre-implementation
**Parent spec:** `docs/superpowers/specs/2026-07-24-evalyn-pro-design.md` (v2 roadmap item #1)
**Sequencing:** Plan #4d — executes after Plan #4c merges. Branch `feat/pro-ui` off `dev`.
**Plan doc (to be written):** `docs/superpowers/plans/2026-07-24-evalyn-pro-4d-ui.md`

---

## 1. What this is

A **local web cockpit** for Evalyn-pro: launch and control eval runs, watch conversations stream
live, explore results interactively, label the review queue, and inspect judge trust — served by
`evalyn ui` on the engineer's own machine. The CLI remains fully functional without it; the UI is
an optional extra (`pip install evalyn[ui]`).

**Locked product decisions (brainstorm 2026-07-24):**

| Decision | Choice |
|---|---|
| Form factor | Local single-user cockpit; `127.0.0.1` only; zero auth; dies with the terminal |
| Run control | Launch, live progress, cancel + live transcript streaming + rerun-failed-subset + pause/resume (drain-and-hold) |
| Reporting | Run explorer/drill-down + review & labeling UI + run diff + cross-run trends + calibration ("Judge Trust") dashboard |
| Calibration dashboard scope | READ-ONLY render of the #4b calibration record + deep links into transcripts/review; no calibration-run orchestration in v1 |
| Stack | FastAPI backend; React SPA (Vite + TypeScript + Tailwind + shadcn subset + Recharts), prebuilt bundle shipped in the wheel |
| Run execution | Subprocess + event log: server spawns `evalyn gate`; engine writes `events.jsonl`; server tails → SSE. UI can attach to terminal-started runs |
| Deferred | Shareable read-only host mode, in-UI scenario editing, calibration-run orchestration, pack authoring, auth, run database |

**Parity rule (design invariant):** every UI action maps to a CLI-visible artifact — a subprocess
invocation, a control file, a labels file. The UI can never produce a run the CLI couldn't, and
anything the UI shows is derivable from files in `runs/` + the pack.

---

## 2. System architecture

Three pieces:

```
┌────────────────────────────┐   spawn `evalyn gate --events`   ┌──────────────────┐
│  FastAPI server (evalyn ui)│ ───────────────────────────────▶ │ engine subprocess │
│  127.0.0.1:<free port>     │                                  │  (unchanged CLI   │
│  - scans runs/ + packs     │   writes runs/<ts>/control ────▶ │   run loop +      │
│  - tails events.jsonl → SSE│ ◀─── appends runs/<ts>/events.jsonl  event emitter)  │
│  - review/promote wrappers │                                  └──────────────────┘
└─────────────┬──────────────┘
              │ one origin: /api + static
      ┌───────▼────────┐
      │  React SPA     │  prebuilt into src/evalyn/ui/static/
      └────────────────┘
```

### 2.1 Engine event stream (the contract everything hangs on)

New module `src/evalyn/engine/events.py`. When a run starts with events enabled
(`--events` flag / `events=True` in `run_gate`), the engine appends one JSON object per line to
`runs/<ts>/events.jsonl`. **Engine-side, UI-agnostic, append-only** — it doubles as a
machine-readable run log and costs nothing when disabled (no-op emitter).

Every event: `{"seq": int, "ts": iso8601, "type": str, ...payload}`. `seq` is monotonic per run
and doubles as the SSE event id (reconnect resume). Event types:

| type | payload |
|---|---|
| `run_started` | pack, models (target/sim/judge), trials, probe count, manifest hash |
| `scenario_started` / `scenario_finished` | probe_id (+ per-probe reducer summary on finish) |
| `trial_started` / `trial_finished` | probe_id, epoch (+ stop_reason, cost, error state on finish) |
| `user_turn` / `assistant_turn` | probe_id, epoch, turn index, content, latency_ms |
| `trace_event` | probe_id, epoch, turn index, TraceEvent dump |
| `verdict` | probe_id, epoch, check/dimension, verdict, tier, rationale, confidence |
| `run_paused` / `run_resumed` | — |
| `run_finished` | gate outcome (passed / gate_failed / invalid / cancelled), totals |

### 2.2 Control channel (pause / resume / cancel)

`runs/<ts>/control` — a one-line file the engine's run loop polls **between trials**:

- `pause` → finish in-flight trials, emit `run_paused`, hold the queue, poll for next command.
- `resume` → emit `run_resumed`, continue the queue.
- `cancel` → drain in-flight trials, score what completed, emit `run_finished` with
  `cancelled` (a cancelled run NEVER counts as gate-passed).

Drain-and-hold only — no mid-trial checkpointing (a trial is atomic). SIGTERM on the subprocess
remains the hard-cancel fallback; the server uses it if the control file goes unacknowledged
(no event within a timeout). This is the one substantive change to #4a–4c engine code, and it
benefits the plain CLI too (Ctrl-free cancel of a terminal run by writing the file).

### 2.3 FastAPI server

`evalyn ui [--port N] [--runs-dir runs/] [--no-open]` — binds `127.0.0.1` only (v1 refuses other
`--host` values), picks a free port, opens the browser. **Stateless over the filesystem**: the
`runs/` directory is the database; killing the server loses nothing. Responsibilities: scan
runs/packs; tail event files → SSE; spawn `evalyn gate` subprocesses; write control files; wrap
`evalyn.review` functions for labeling/promotion; aggregate trends; serve the calibration record.
FastAPI + uvicorn live behind the `evalyn[ui]` extra so the core keeps its tiny-dependency story.

### 2.4 React SPA

Prebuilt static bundle committed at `src/evalyn/ui/static/` and shipped in the wheel — end users
never need Node; only UI contributors do (`ui/` Node project in-repo). One origin, zero external
requests (same self-contained rule as the #4c HTML report).

---

## 3. Screens & navigation

Left sidebar: **Runs / Launch / Review / Trends / Judge Trust.**

1. **Runs (home).** Table over `runs/`: status chip (running / passed / gate-failed / invalid /
   cancelled / paused / interrupted / failed-to-start), pack, pass@1/pass^k summary,
   abstained/errored counts, cost, duration. Live rows update via SSE. Per completed run:
   *Diff against…* (pick second run → Diff view) and *Rerun failed subset*.

2. **Run Detail (centerpiece).** Header: gate verdict banner (incl. RUN INVALID), live controls
   (pause/resume/cancel), manifest (models, seeds, pack hash, parent_run link for reruns). Body:
   scenario table (per-probe pass@1, pass^k, dimensions, abstentions, cost) → expand → k trials →
   **TranscriptViewer**: chat-style turns with inline annotations — check hits with evidence
   highlighting, judge verdicts with rationale + tier badge (1 / 2 / 3-panel / abstained), trace
   events as collapsible chips between turns, perturbation-injection markers, simulator
   goal-progress ticks. Live runs stream new turns into the same viewer.

3. **Launch.** Pack picker (validated on selection; `validate-pack` errors inline), trials /
   sim model / judge model / budget / tag filter, launch → redirect to live Run Detail. Recent
   launch configs in localStorage.

4. **Review.** The #4b queue in the browser: filters (abstained/failed, scenario, dimension),
   keyboard-driven labeling (`j`/`k` navigate, `p`/`f` label, `n` note), transcript beside judge
   rationale, promote buttons (→ calibration anchor, → draft probe) showing the written file
   path, queue progress bar.

5. **Trends.** Per-scenario and per-dimension score/pass^k lines across all runs of a pack
   (Recharts), gate-failure annotations on the time axis.

6. **Judge Trust.** Read-only calibration dashboard: per-dimension κ / weighted-κ badges with
   certification status, "stale — rubric changed since certification" banner on hash mismatch,
   judge-vs-human confusion tables, worst disagreements deep-linked into TranscriptViewer, and a
   "label more anchors" button that jumps into Review. Rationale: this page is the visible proof
   of the trustworthy-judging differentiator; #4b computes everything it shows, so it is ~90%
   presentation. Deep links make it actionable rather than decorative.

**Diff view** (`/diff/:a/:b`): two-column per-scenario/per-dimension deltas, CI-aware coloring
(grey when confidence intervals overlap), grouped "new failures" and "fixed" sections first.

---

## 4. Server API

All JSON under `/api`; SPA served from `/`.

| Endpoint | Behavior |
|---|---|
| `GET /api/runs` | run list from manifests + reduced artifacts |
| `GET /api/runs/{id}` | run detail (scenario table data) |
| `GET /api/runs/{id}/transcripts/{probe}/{epoch}` | one trial, server-side merged: transcript + verdicts + trace + perturbation markers (SPA stays dumb) |
| `GET /api/runs/{id}/events` | **SSE**: replay `events.jsonl` from 0 (or `Last-Event-ID`), then live-tail until `run_finished`. Same endpoint for historical and live runs |
| `POST /api/runs` | launch: `{pack, trials?, sim_model?, judge_model?, tags?, budget?}` → spawn `evalyn gate --events` → `{run_id, pid}` |
| `POST /api/runs/{id}/control` | `{action: pause\|resume\|cancel}` → write control file; SIGTERM fallback on ack timeout |
| `POST /api/runs/{id}/rerun-failed` | failed ∪ errored ∪ abstained probe set → filtered launch; `parent_run` recorded in new manifest |
| `GET /api/packs` / `POST /api/packs/validate` | discovery + validation for Launch |
| `GET /api/review/{run_id}` | queue items |
| `POST /api/review/{run_id}/label` | write label (idempotent per item; file lock during append; last-writer-wins vs CLI) |
| `POST /api/review/{run_id}/promote` | `{item, as: anchor\|probe}` → same `evalyn.review.promote` functions as CLI; returns written path |
| `GET /api/trends?pack=…` | cross-run aggregation |
| `GET /api/calibration?pack=…` | calibration record + anchor stats + staleness vs current rubric hashes |

Path safety: every run/pack path resolved and checked against its root (no traversal).

---

## 5. Frontend architecture

- **State:** TanStack Query for REST (caching, refetch, optimistic label updates); one
  `useRunEvents(runId)` hook wrapping `EventSource`, reducing events into live run state
  (scenario statuses, streaming transcripts). No global state library — server state + URL is
  the state.
- **Routes:** `/runs`, `/runs/:id`, `/runs/:id/trial/:probe/:epoch`, `/launch`,
  `/review/:runId?`, `/trends`, `/judge-trust`, `/diff/:a/:b`. Everything deep-linkable.
- **Component spine:** `TranscriptViewer` (single implementation reused by Run Detail, Review,
  Judge Trust disagreements, live streaming — annotations as props), `ScenarioTable`,
  `RunStatusChip`, `VerdictBadge` (tier 1/2/3-panel + abstained), `KappaBadge`, `DiffTable`,
  Recharts wrappers. Tailwind + shadcn subset (table, dialog, tabs, toast). Dark mode via
  `prefers-color-scheme`.
- **Live UX rules:** SSE auto-reconnect with `Last-Event-ID` resume + visible "reconnecting…"
  banner (a frozen-but-alive-looking view is the worst failure mode); streaming transcripts
  autoscroll with pin-to-bottom toggle; global "run finished" toast.

---

## 6. Error handling

- **Tailer robustness:** incomplete last JSONL line → wait for more bytes; malformed line →
  skip + server log warning; never crash the SSE stream.
- **Subprocess death pre-events** → run shown `failed to start` with captured stderr.
  **Process vanished** (externally killed; pid-liveness check) → `interrupted`; artifacts remain
  browsable.
- **Control acknowledgment:** UI updates optimistically but the status chip only commits on the
  engine's own `run_paused` / `run_resumed` / `run_finished(cancelled)` event; unacknowledged
  cancel escalates to SIGTERM after timeout.
- **Concurrent labeling** (UI + CLI on the same queue): idempotent per-item writes, file lock
  during append, last-writer-wins per item.
- A cancelled or invalid run is never rendered as passed; RUN INVALID banner mirrors the #4c
  exit-code semantics.

---

## 7. Packaging, build & dev workflow

- Repo: `ui/` Node project (`node_modules` gitignored); `npm run build` → emits to
  `src/evalyn/ui/static/`, which **is committed** (reviewable; `pip install` from git works
  without Node). CI check rebuilds and fails on drift so the committed bundle can't go stale.
- Python deps: `fastapi` + `uvicorn` behind the `[ui]` extra; core install unchanged.
- Dev: `evalyn ui --dev` proxies to the Vite dev server for UI contributors (hot reload);
  documented in `ui/README.md`.

---

## 8. Testing

- **Engine events:** unit tests — seq monotonicity, event ordering, no-op mode costs nothing,
  control-file polling (pause → drain → hold → resume; cancel → drain → cancelled). Pure
  Python, main suite.
- **Server:** endpoint tests against fixture run directories via FastAPI TestClient/httpx —
  including a live-tail test (fixture `events.jsonl` appended during the test) and a control
  round-trip against a fake engine loop.
- **Frontend:** Vitest for the SSE reducer + annotation merge; one Playwright smoke
  (launch MockTarget run → watch stream → open transcript → label → promote) against the real
  server in CI.

---

## 9. Scope ledger

**v1 (Plan #4d):** everything above.
**Deferred:** shareable read-only host mode (`--host` beyond loopback), in-UI scenario/pack
editing, calibration-run orchestration from the UI, auth of any kind, run database /
multi-machine aggregation, mobile layouts.

---

## 10. Open questions for the implementation plan

1. Exact SSE library choice server-side (`sse-starlette` vs hand-rolled generator) — decide at
   plan Task 0 by dependency weight.
2. Recharts vs uPlot if trend datasets get large — start Recharts, revisit only on evidence.
3. Whether `rerun-failed` reuses #2b compare machinery for parent/child linking — check at
   re-baseline.

---

## 11. Decision log

| # | Decision | Why |
|---|---|---|
| U1 | Local single-user cockpit, loopback-only, no auth | Matches OSS engineer-first identity; avoids access-control scope |
| U2 | Subprocess + event log (not in-process, not daemon) | Crash-proof by construction; CLI/UI parity; attach to terminal runs free |
| U3 | Event stream is engine-side and UI-agnostic | Doubles as machine-readable run log; UI is a consumer, not a dependency |
| U4 | Pause = drain-and-hold between trials; trials atomic | Real control without mid-trial checkpointing complexity |
| U5 | React SPA prebuilt into wheel; Node only for contributors | Best interactivity for streaming/diff/labeling; zero end-user toolchain |
| U6 | `runs/` is the database; server stateless | Kill server, lose nothing; no migration/schema burden |
| U7 | Judge Trust page read-only + deep links | Visible proof of the differentiator at ~10% of the cost; links make it actionable |
| U8 | UI behind `evalyn[ui]` extra | Preserves the core's tiny-dependency neutrality story |
| U9 | Committed static bundle + CI drift check | `pip install` from git works; bundle can't silently go stale |
