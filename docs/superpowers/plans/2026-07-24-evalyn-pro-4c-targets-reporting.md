# Evalyn-pro Plan #4c — Product-Agnostic Targets, Trace Enrichment & Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make any conversational system a first-class target (in-process Python callables beside HTTP), score agent internals when targets expose them (trace events → tool-call checks), separate infrastructure errors from quality failures in the gate, and ship a self-contained HTML drill-down report.

**Architecture:** `TargetSpec` gains a `type` discriminator (`http` | `python`); the session solver delegates transport to a small target-transport layer; replies become `(text, trace_events)`; a new `evalyn.report` package renders RunArtifact + Inspect log into one HTML file. Spec: `docs/superpowers/specs/2026-07-24-evalyn-pro-design.md` §3.1, §5.1, §6.2, §8, §13.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, Inspect AI (`read_eval_log`), stdlib `html`/`json` templating (no JS framework, no CDN), typer, pytest.

**Sequencing:** Execute after Plan #4b merges. Branch: `feat/pro-targets-reporting` off `dev`.

## Global Constraints

- Async-only target IO; Python targets must expose an async callable (sync callables wrapped via `asyncio.to_thread` — never block the loop).
- Allowlist enforcement is HTTP-specific; Python targets bypass URL allowlisting but are named in the pack (explicit, reviewable) — never import arbitrary code not declared in the pack.
- Trace events are OPTIONAL enrichment: every feature in this plan degrades gracefully when a target sends none (spec §3.1).
- `errored` ≠ `failed`; a run over its error budget refuses to gate — CI must distinguish "quality failed" from "run invalid" (spec D10).
- HTML report is fully self-contained: inline CSS/JS, embedded JSON, zero external requests.
- Test-first; `uv run pytest -q` + `uv run ruff check src/` before every commit; ask user before every commit/push/PR; user-name-only commit identity.

---

### Task 0: Re-baseline against post-#4b code

**Files:** read-only pass over `src/evalyn/engine/solver.py` (post-#4a simulated loop + #2a configurable session shapes), `src/evalyn/targets/` (schema/loader/streams), `src/evalyn/engine/run.py` + `gate.py` (post-#4b abstention fields), `cli.py`, and #2b's compare/CI output formats.

- [ ] **Step 1:** Confirm the solver's transport seams: `_open(client)` / `_send(client, session_id, message)` (or their #2a-renamed equivalents) — Task 2 extracts these into a transport protocol; note every call site.
- [ ] **Step 2:** Confirm `ProbeResult`/`RunArtifact` fields post-#4b (`abstained` added) — Tasks 5–6 extend them.
- [ ] **Step 3:** Confirm #2b's `compare` report format so the HTML report (Task 6) links rather than duplicates; confirm exit-code allocation in `cli.py` (0/1/2 today) before adding run-invalid.
- [ ] **Step 4:** Amend plan inline; ask user, then commit `docs: re-baseline evalyn-pro plan 4c`.

---

### Task 1: `TargetSpec.type` discriminator + Python target schema

**Files:**
- Modify: `src/evalyn/targets/schema.py`, `src/evalyn/engine/validate.py`
- Test: `tests/test_target_type_schema.py`

**Interfaces:**
- Produces: `TargetSpec` gains `type: Literal["http", "python"] = "http"` and `entrypoint: str | None = None` (format `"package.module:factory"`). Validation: `type=python` requires `entrypoint` and ignores `sessions`/`allowlist` (warn if present); `type=http` keeps current required fields.

- [ ] **Step 1: Write failing tests:** `TargetSpec(type="python", entrypoint="examples.toy_agent:make_agent", name="t")` valid without `sessions`/`allowlist`; `type=python` without `entrypoint` → `ValidationError`; `type=http` without `sessions` → error (existing behavior preserved); `validate_pack` warns when a python pack declares an allowlist.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement: make `sessions`/`allowlist` optional at the pydantic level with a `model_validator` enforcing per-type requirements (so http packs keep exactly today's errors).
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: target type discriminator with python entrypoint`.

---

### Task 2: Target transport layer — `PythonTransport` beside `HttpTransport`

**Files:**
- Create: `src/evalyn/targets/transport.py`
- Modify: `src/evalyn/engine/solver.py`
- Test: `tests/test_transport.py`

**Interfaces:**
- Produces:

```python
# transport.py
@dataclass
class TargetReply:
    text: str
    trace: list[TraceEvent] = field(default_factory=list)   # TraceEvent from Task 3
                                                            # (Task 2 lands with trace=[] always)

class TargetTransport(Protocol):
    async def open(self) -> str: ...                        # session id
    async def send(self, session_id: str, message: str) -> TargetReply: ...
    async def close(self) -> None: ...

class HttpTransport:      # wraps the existing _open/_send solver logic verbatim
    def __init__(self, pack: Pack): ...

class PythonTransport:
    def __init__(self, pack: Pack): ...
    # entrypoint "pkg.mod:factory" -> factory() returns an object with:
    #   async open() -> str | None      (optional; default: uuid4 session)
    #   async send(session_id, message) -> str | dict
    # dict form: {"reply": str, "trace": [ ... ]}  (trace parsed in Task 3)

def make_transport(pack: Pack) -> TargetTransport   # dispatch on spec.type
```

- Consumes: solver seams from Task 0; the solver's scripted and simulated loops call `transport.send(...)` and read `.text`, replacing direct `_send` calls. Behavior of HTTP packs must be byte-identical (same requests, same allowlist enforcement — `resolve_base_url` still called in `HttpTransport.__init__`).

- [ ] **Step 1: Write failing tests:** `make_transport` dispatches by type; `PythonTransport` loads `tests/fixtures/toy_agent.py:make_agent` (a tiny in-repo echo agent fixture — create it in this step) and round-trips a message; sync `send` on the target object is wrapped via `asyncio.to_thread`; string return and `{"reply": ...}` dict return both yield `TargetReply.text`; missing/bad entrypoint → clear `PackError` naming the entrypoint. Solver regression: existing solver tests pass unchanged against `HttpTransport`.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement `transport.py` (entrypoint import via `importlib.import_module` + `getattr`); refactor `session_solver` to build `make_transport(pack)` once and use it in both loops; keep `concurrency()` bounding around HTTP sends only (python targets are in-process).
- [ ] **Step 4:** `uv run pytest -q` — green (whole suite: proves HTTP path unchanged).
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: pluggable target transport with in-process python targets`.

---### Task 3: TraceEvent schema + trace capture into state

**Files:**
- Create: `src/evalyn/targets/trace.py`
- Modify: `src/evalyn/targets/transport.py` (parse dict replies), `src/evalyn/engine/solver.py` (accumulate per-turn traces)
- Test: `tests/test_trace_capture.py`

**Interfaces:**
- Produces:

```python
# trace.py
class TraceEvent(BaseModel):
    kind: Literal["tool_call", "retrieval", "agent_step", "custom"]
    name: str
    args: dict | None = None
    result: str | None = None
    error: str | None = None

def parse_trace(raw: object) -> list[TraceEvent]   # lenient: non-list/invalid -> [] + warning
```

Solver records `state.metadata["trace"] = [[TraceEvent-dump, ...], ...]` — one list per assistant turn (empty lists when the target sends none), aligned with assistant messages.

- [ ] **Step 1: Write failing tests:** python target returning `{"reply": "ok", "trace": [{"kind": "tool_call", "name": "lookup_order", "args": {"email": "a@x.com"}}]}` → `state.metadata["trace"][0][0]["name"] == "lookup_order"`; malformed trace entries dropped with warning, reply still delivered; HTTP targets (no trace channel yet) produce aligned empty lists; multi-turn alignment matches assistant turn count.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement `trace.py`; `PythonTransport.send` parses dict replies through `parse_trace`; solver appends `reply.trace` dumps per turn in both loops.
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: trace event capture from python targets`.

---

### Task 4: Tool-call checks (Tier-1)

**Files:**
- Modify: `src/evalyn/targets/schema.py` (CheckType + fields), `src/evalyn/scoring/tier1.py`, `src/evalyn/engine/validate.py`
- Test: `tests/test_tool_checks.py`

**Interfaces:**
- Consumes: `state.metadata["trace"]` (Task 3).
- Produces: check types `tool_called` / `tool_not_called`:

```yaml
- {type: tool_called, name: lookup_order, args_contain: {email: "a@x.com"}, required: true}
- {type: tool_not_called, name: delete_account, required: true}
```

`Check` gains `name: str | None` and `args_contain: dict | None`. Semantics: `tool_called` passes iff any `tool_call` event across ALL turns matches `name` and (when given) every `args_contain` key/value appears in the event's `args` (`"*"` value = key present with any value). `tool_not_called` passes iff no matching event. **Graceful degradation:** on a transcript with NO trace events at all, `tool_called` scores NOANSWER (abstained — can't know) with explanation `target sent no trace events`, and `tool_not_called` passes (vacuous) with the same note in the explanation.

- [ ] **Step 1: Write failing tests:** matching call passes; wrong args fail with detail; `"*"` wildcard matches presence; forbidden tool called anywhere fails `tool_not_called`; traceless transcript → `tool_called` = NOANSWER, `tool_not_called` = pass; `validate_pack` errors on `tool_called` without `name`.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement in `tier1.py` (flatten `state.metadata["trace"]`, match per semantics above); extend `CheckType` literal + validation.
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: tool_called/tool_not_called tier-1 checks`.

---

### Task 5: Error taxonomy — error budget, run-invalid exit code

**Files:**
- Modify: `src/evalyn/targets/schema.py` (`Budget.max_error_fraction`), `src/evalyn/engine/run.py`, `src/evalyn/engine/gate.py`, `src/evalyn/cli.py`
- Test: `tests/test_error_budget.py`

**Interfaces:**
- Produces: `Budget.max_error_fraction: float = 0.1`; `ProbeResult.errored: int` (trials whose sample errored — target exceptions, `SimulatorError`); reducers computed over non-errored, non-abstained trials; `RunArtifact.errored_fraction: float`. Gate: if `errored_fraction > max_error_fraction` → `GateResult` carries `run_invalid=True` and CLI exits **3** (`gate` today: 0 pass / 1 gate-fail / 2 validation error — confirmed in Task 0; 3 = run invalid). Report line: `RUN INVALID: 5/16 trials errored (max_error_fraction=0.1) — gate not evaluated`.

- [ ] **Step 1: Write failing tests:** synthetic log with errored samples → `errored` counts and exclusion from reducers; fraction over budget → `run_invalid=True`, no probe pass/fail judgments emitted, CLI exit 3; fraction under budget → normal gating with errored trials excluded; solver target 5xx path produces an errored sample not a failed score (integration via fake target that 500s).
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement — Inspect records sample errors when the solver raises; run eval with `fail_on_error` set so the eval completes despite sample errors (exact Inspect knob confirmed at Task 0), partition in `_reduce_log_to_probes`, add gate rule + exit code.
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: error budget with run-invalid gate outcome`.

---

### Task 6: Self-contained HTML drill-down report

**Files:**
- Create: `src/evalyn/report/__init__.py`, `src/evalyn/report/html.py`
- Modify: `src/evalyn/engine/run.py` (auto-emit), `src/evalyn/cli.py` (`evalyn report` command)
- Test: `tests/test_html_report.py`

**Interfaces:**
- Consumes: `RunArtifact` (+ `abstained`/`errored` fields), Inspect log via `read_eval_log(log_path)` for transcripts, `review_queue.jsonl` (#4b) if present.
- Produces: `render_report(artifact: RunArtifact, log_path: str) -> str` (one HTML document) and `write_report(artifact, log_path, out_dir: Path) -> Path` (`runs/<ts>/report.html`); CLI `evalyn report runs/<ts>/` regenerates it. Content: run header (pack, models, timestamps, totals, gate outcome incl. run-invalid), scenario table (probe × pass@1 / pass^k / abstained / errored / cost), and per-probe `<details>` drill-down: each trial's full transcript with per-turn annotations (check hits with evidence, judge rationale + tier, trace events, perturbation-injection turns from #4a notes). Inline CSS only; data embedded as one `<script type="application/json">` blob + ~40 lines of vanilla JS for expand/collapse; `html.escape` everything user-generated.

- [ ] **Step 1: Write failing tests:** `render_report` output contains no `http(s)://` resource references (regex over `src=`/`href=` attributes); probe ids and pass^k values present; a transcript with `<script>alert(1)</script>` content appears escaped (no raw `<script>alert` in output); `write_report` after `run_gate` produces `report.html`; run-invalid runs render the RUN INVALID banner instead of a gate verdict.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement `html.py` (string templating, no dependency); wire auto-emit at the end of `run_gate` and the `report` CLI command.
- [ ] **Step 4:** `uv run pytest -q` — green. Manual check: `uv run evalyn gate packs/example --sim-model mockllm/model` then open `runs/<ts>/report.html` in a browser; verify drill-down works offline.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: self-contained HTML drill-down report`.

---

### Task 7: `evalyn init` scaffold + product-agnostic audit + launch docs

**Files:**
- Modify: `src/evalyn/cli.py` (add `init`), `README.md`, `docs/JOURNAL.md`, `docs/ROADMAP.md`
- Create: `src/evalyn/scaffold/` (template pack files packaged as data)
- Test: `tests/test_init_scaffold.py`

**Interfaces:**
- Produces: `evalyn init <dir>` writes a runnable starter suite: `pack.yaml` (python target pointing at a bundled demo agent module `evalyn.scaffold.demo_agent:make_agent` that exhibits 2 scripted failure modes — forgets an instruction, calls a forbidden tool), one scripted probe, one simulated probe using a preset persona, one anchors example, and a README. `evalyn gate <dir> --sim-model mockllm/model` must pass out-of-the-box with NO API keys (mockllm sim + demo agent + deterministic checks only) — the 10-minute-to-value path (spec §9).

- [ ] **Step 1: Write failing tests:** `init` into tmp dir → `load_pack` + `validate_pack` succeed; full `run_gate` on the scaffolded dir with mockllm models completes and produces `report.html`; scaffolding into a non-empty dir refuses with a clear error.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement scaffold templates + `init` command + demo agent.
- [ ] **Step 4:** **Product-agnostic audit (concrete checklist, fix inline or file JOURNAL deferrals):** grep `src/evalyn` for `twincore`, `niuwn`, hardcoded URLs/ports, hardcoded session keys (`"session_id"`), and TwinCore-shaped assumptions outside `packs/twincore/`; confirm every remaining hardcoding is either pack-configurable (via #2a fields) or removed. Run `uv run pytest -q` + `uv run ruff check src/` — green.
- [ ] **Step 5:** README rewrite for the OSS launch story (what it is, 10-minute quickstart via `init`, simulation + trustworthy judging sections, v2 roadmap incl. local web UI / dual-control / OTel ingestion). Update JOURNAL + ROADMAP (Evalyn-pro complete). Ask user, then commit `feat: init scaffold, product-agnostic audit, launch docs`. Then `superpowers:finishing-a-development-branch` (ask before PR).

---

## Acceptance (whole plan)

- Full suite green, ruff clean.
- A pure-Python agent evaluates with zero HTTP config; an HTTP chatbot evaluates exactly as before.
- Targets that emit traces get tool-call gating; targets that don't still get everything else (tool checks abstain/vacuous-pass, never crash).
- Infra failures can never fail the quality gate: over-budget runs exit 3 with RUN INVALID, never 1.
- `evalyn init` → `evalyn gate` → open `report.html`: a stranger reaches a drill-down report in under 10 minutes with no API keys.
