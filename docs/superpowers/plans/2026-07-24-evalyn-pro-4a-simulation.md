# Evalyn-pro Plan #4a — Persona-Driven User Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scripted probe `turns` with an LLM-simulated user (persona + goal + knowledge inventory + behavior policy + perturbations) driving live multi-turn conversations through the existing Inspect session solver.

**Architecture:** A new `evalyn.simulation` package generates user turns; the existing `session_solver` grows a simulated-user loop beside its scripted loop. Personas are pack content (YAML) validated like probes. Stop reasons and goal-progress become scoreable signals via a new Tier-1 check type. Spec: `docs/superpowers/specs/2026-07-24-evalyn-pro-design.md` §3.2–3.3, §4, §13.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, Inspect AI (`inspect_ai>=0.3.249`) `get_model()` for the simulator LLM, async `httpx` (already in solver), pytest.

**Sequencing:** Execute ONLY after Plans #2a, #2b, #3 are merged to `dev`. Branch: `feat/pro-simulation` off `dev`.

## Global Constraints

- Inspect AI spine: simulator is called from inside the existing `@solver session_solver`; no new eval loop.
- Async `httpx` only for target traffic; simulator LLM calls go through Inspect `get_model()`.
- Simulator model is configurable and independent of judge and target families (spec §4.4).
- Simulator failures are `errored`, never `failed` — no silently fabricated user turns (spec §8).
- All work test-first; run `uv run pytest -q` and `uv run ruff check src/` before every commit.
- Ask the user before every `git commit` / `git push` / PR (user rule 2026-07-24).
- Commits under `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com'`; no Co-Authored-By.

---

### Task 0: Re-baseline against post-Plan-#3 code

Plans #2a/#2b/#3 will have changed files this plan touches. This plan's code blocks were written against Plan-#1 code (commit `d4ce297` merge); verify each integration point and amend the plan file inline (commit the amendments as `docs:`) before starting Task 1.

**Files:** Read-only pass over `src/evalyn/targets/schema.py`, `src/evalyn/targets/loader.py`, `src/evalyn/engine/solver.py`, `src/evalyn/engine/task_builder.py`, `src/evalyn/engine/validate.py`, `src/evalyn/scoring/tier1.py`, `src/evalyn/cli.py`.

- [ ] **Step 1:** Confirm these Plan-#1 signatures still hold (adjust plan code if not): `Probe(id, category, kind, safety_critical, turns, checks, samples, reference)`; `Pack(spec, probes, root)` in `loader.py`; `session_solver(pack)` reads `state.metadata["turns"]`, appends `ChatMessageUser`/`ChatMessageAssistant` to `state.messages`; `build_task(pack, judge_model=...)`; Tier-1 scorer iterates `probe.checks` by `type`.
- [ ] **Step 2:** Confirm what Plan #2a delivered for configurable session shapes (open body, session-id key, message payload) and reuse those fields — do NOT re-implement.
- [ ] **Step 3:** Confirm whether Plan #2/#3 introduced a persona or user-simulation concept anywhere (Plan #3 `discover` uses personas for attack strategies). If yes, reconcile naming — pack-level `Persona` defined here must be the single shared model.
- [ ] **Step 4:** Note how `Budget.max_turns_per_session` is enforced post-#2a and reuse that enforcement in the simulated loop.
- [ ] **Step 5:** Amend this plan file where reality diverges; ask user, then commit `docs: re-baseline evalyn-pro plan 4a against post-plan-3 code`.

---

### Task 1: Persona + Perturbations + scenario fields on Probe

**Files:**
- Modify: `src/evalyn/targets/schema.py`
- Modify: `src/evalyn/engine/validate.py`
- Test: `tests/test_scenario_schema.py`

**Interfaces:**
- Produces: `Persona(id, traits, tone, behavior, knowledge, patience_turns)`; `Perturbations(typos, topic_drift, self_contradiction, goal_shift)`; `Probe` gains `persona: str | None`, `goal: str | None`, `environment: dict[str,str]`, `max_turns: int`, `perturbations: Perturbations | None`, and `turns` becomes `list[str] = []`. Validation rule: scripted XOR simulated.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scenario_schema.py
import pytest
from pydantic import ValidationError
from evalyn.targets.schema import Persona, Perturbations, Probe
from evalyn.engine.validate import validate_pack


def _check():
    return {"type": "contains", "value": "refund", "required": True}


def test_persona_model_defaults():
    p = Persona(id="frustrated-buyer", traits="impatient small-business owner")
    assert p.tone == "casual" and p.behavior == "cooperative"
    assert p.knowledge == {} and p.patience_turns == 8


def test_persona_rejects_unknown_behavior():
    with pytest.raises(ValidationError):
        Persona(id="x", traits="t", behavior="chaotic")


def test_probe_simulated_mode_valid():
    p = Probe(id="p1", category="billing", checks=[_check()],
              persona="frustrated-buyer", goal="get a refund", max_turns=10)
    assert p.turns == [] and p.goal == "get a refund"


def test_probe_scripted_mode_still_valid():
    p = Probe(id="p2", category="billing", turns=["hi"], checks=[_check()])
    assert p.persona is None


def test_probe_rejects_both_modes():
    with pytest.raises(ValidationError):
        Probe(id="p3", category="billing", turns=["hi"], checks=[_check()],
              persona="frustrated-buyer", goal="get a refund")


def test_probe_rejects_neither_mode():
    with pytest.raises(ValidationError):
        Probe(id="p4", category="billing", checks=[_check()])


def test_probe_rejects_persona_without_goal():
    with pytest.raises(ValidationError):
        Probe(id="p5", category="billing", checks=[_check()], persona="frustrated-buyer")
```

- [ ] **Step 2:** Run `uv run pytest tests/test_scenario_schema.py -q` — expect FAIL (`ImportError: cannot import name 'Persona'`).
- [ ] **Step 3: Implement in `src/evalyn/targets/schema.py`**

```python
class Persona(BaseModel):
    id: str
    traits: str
    tone: Literal["formal", "casual", "terse", "verbose"] = "casual"
    behavior: Literal["cooperative", "underspecified", "distracted",
                      "frustrated", "adversarial"] = "cooperative"
    # Knowledge inventory: facts this user knows. The simulator may disclose an
    # item only when conversationally warranted (spec §4.1). What the persona
    # does NOT know is as important as what it knows.
    knowledge: dict[str, str] = Field(default_factory=dict)
    patience_turns: int = Field(default=8, ge=1)   # unhelpful turns before giving up


class Perturbations(BaseModel):
    typos: Literal["off", "light", "heavy"] = "off"
    topic_drift: Literal["never", "once"] = "never"
    self_contradiction: bool = False
    goal_shift: bool = False
```

And on `Probe` (keep existing fields; `turns` gets a default):

```python
    turns: list[str] = Field(default_factory=list)   # scripted mode
    persona: str | None = None                       # simulated mode: persona id
    goal: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    max_turns: int = Field(default=12, ge=1)
    perturbations: Perturbations | None = None

    @model_validator(mode="after")
    def _scripted_xor_simulated(self) -> "Probe":
        scripted, simulated = bool(self.turns), self.persona is not None
        if scripted == simulated:
            raise ValueError(
                f"probe {self.id}: declare either scripted 'turns' or a "
                f"'persona' (simulated), not both / neither")
        if simulated and not self.goal:
            raise ValueError(f"probe {self.id}: simulated probes require 'goal'")
        return self
```

(`from pydantic import model_validator` added to imports.)

- [ ] **Step 4:** Run `uv run pytest tests/test_scenario_schema.py -q` — expect PASS; then `uv run pytest -q` (full suite: existing packs all use scripted `turns`, must stay green).
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: persona/perturbation schema and simulated-scenario probe fields`.

---

### Task 2: Persona loading — pack `personas/` dir + built-in presets

**Files:**
- Modify: `src/evalyn/targets/loader.py` (add `personas` to `Pack`, load them)
- Modify: `src/evalyn/engine/validate.py` (unknown-persona reference = validation failure)
- Create: `src/evalyn/simulation/__init__.py`, `src/evalyn/simulation/presets/underspecified_customer.yaml`, `.../frustrated_customer.yaml`, `.../distracted_customer.yaml` (packaged data)
- Test: `tests/test_persona_loading.py`

**Interfaces:**
- Consumes: `Persona` (Task 1); `Pack`, `load_pack(path)` (existing).
- Produces: `Pack.personas: dict[str, Persona]` — pack-local `personas/*.yaml` merged over built-ins from `evalyn/simulation/presets/` (pack-local wins on id collision); `validate_pack` reports `probe X references unknown persona 'Y'`.

- [ ] **Step 1: Write failing tests** — a tmp pack fixture with one persona YAML

```python
# tests/test_persona_loading.py
import textwrap
from evalyn.targets.loader import load_pack
from evalyn.engine.validate import validate_pack


def _write_pack(tmp_path, probe_yaml, persona_yaml=None):
    (tmp_path / "pack.yaml").write_text(textwrap.dedent("""
        name: t
        sessions:
          open: {method: POST, path: /open}
          message: {method: POST, path: /msg}
        allowlist: ["http://127.0.0.1:8899"]
    """))
    (tmp_path / "probes").mkdir()
    (tmp_path / "probes" / "p.yaml").write_text(textwrap.dedent(probe_yaml))
    if persona_yaml:
        (tmp_path / "personas").mkdir()
        (tmp_path / "personas" / "u.yaml").write_text(textwrap.dedent(persona_yaml))
    return tmp_path

SIM_PROBE = """
    id: sim-1
    category: billing
    persona: angry-alice
    goal: get a refund
    checks: [{type: contains, value: refund, required: true}]
"""
ALICE = """
    id: angry-alice
    traits: furious repeat customer
    behavior: frustrated
    knowledge: {email: alice@example.com}
"""

def test_pack_local_persona_loaded(tmp_path):
    pack = load_pack(_write_pack(tmp_path, SIM_PROBE, ALICE))
    assert pack.personas["angry-alice"].behavior == "frustrated"

def test_builtin_presets_always_available(tmp_path):
    pack = load_pack(_write_pack(tmp_path, SIM_PROBE, ALICE))
    assert "underspecified-customer" in pack.personas   # packaged preset

def test_unknown_persona_reference_fails_validation(tmp_path):
    pack = load_pack(_write_pack(tmp_path, SIM_PROBE))  # no personas dir
    report = validate_pack(pack)
    assert not report.ok
    assert any("unknown persona" in e for e in report.errors)
```

(Adapt `_write_pack` to the real pack layout confirmed in Task 0 — reuse the existing test fixture helper if the suite already has one.)

- [ ] **Step 2:** Run `uv run pytest tests/test_persona_loading.py -q` — expect FAIL.
- [ ] **Step 3: Implement.** In `loader.py`: add `personas: dict[str, Persona]` to `Pack`; in `load_pack`, after probes, load `<root>/personas/*.yaml` each as one `Persona`, merged over built-ins loaded via `importlib.resources.files("evalyn.simulation") / "presets"`. In `validate.py`: for each simulated probe, `probe.persona in pack.personas` else error. Preset example:

```yaml
# src/evalyn/simulation/presets/underspecified_customer.yaml
id: underspecified-customer
traits: >
  Ordinary customer in a mild hurry. Opens with a vague one-line request and
  assumes the assistant will ask for whatever it needs.
tone: terse
behavior: underspecified
patience_turns: 6
```

(`frustrated_customer.yaml` → id `frustrated-customer`, behavior `frustrated`; `distracted_customer.yaml` → id `distracted-customer`, behavior `distracted`.) Add the presets dir to package data in `pyproject.toml` if `uv build` doesn't include YAML by default.

- [ ] **Step 4:** `uv run pytest -q` — full suite green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: load pack personas with built-in preset library`.

---

### Task 3: Perturbation note generator (deterministic)

**Files:**
- Create: `src/evalyn/simulation/perturb.py`
- Test: `tests/test_perturb.py`

**Interfaces:**
- Consumes: `Perturbations` (Task 1).
- Produces: `perturbation_notes(cfg: Perturbations, probe_id: str, max_turns: int) -> dict[int, str]` — maps turn number (0-based) → an instruction string injected into the simulator prompt for that turn; deterministic per `probe_id` (seeded RNG) so trials are reproducible and the injection point is loggable.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_perturb.py
from evalyn.simulation.perturb import perturbation_notes
from evalyn.targets.schema import Perturbations


def test_off_produces_no_notes():
    assert perturbation_notes(Perturbations(), "p1", 10) == {}

def test_deterministic_per_probe_id():
    cfg = Perturbations(typos="light", topic_drift="once", self_contradiction=True)
    assert perturbation_notes(cfg, "p1", 10) == perturbation_notes(cfg, "p1", 10)

def test_typos_apply_every_turn_drift_once():
    cfg = Perturbations(typos="light", topic_drift="once")
    notes = perturbation_notes(cfg, "p1", 8)
    assert all("typo" in notes[t].lower() for t in range(8))
    assert sum("unrelated" in n.lower() for n in notes.values()) == 1

def test_goal_shift_lands_mid_conversation():
    notes = perturbation_notes(Perturbations(goal_shift=True), "p2", 10)
    shift_turns = [t for t, n in notes.items() if "change your goal" in n.lower()]
    assert len(shift_turns) == 1 and 2 <= shift_turns[0] <= 7
```

- [ ] **Step 2:** Run `uv run pytest tests/test_perturb.py -q` — expect FAIL.
- [ ] **Step 3: Implement**

```python
# src/evalyn/simulation/perturb.py
"""Deterministic perturbation notes injected into the simulator prompt.

Notes are keyed by turn index so the run log can distinguish user-side noise
from target failure (spec §4.3)."""
import random
from evalyn.targets.schema import Perturbations

_TYPO = {"light": "Include one small typo or informal spelling in your message.",
         "heavy": "Write sloppily: several typos, lowercase, abbreviations."}
_DRIFT = ("Briefly bring up an unrelated topic in this message before "
          "returning to your goal next turn.")
_CONTRA = ("In this message, contradict one factual detail you stated earlier "
           "(then stick to the corrected version if challenged).")
_SHIFT = ("Change your goal from now on: you now also want the outcome adjusted "
          "(e.g. store credit instead of refund). State the change naturally.")


def perturbation_notes(cfg: Perturbations, probe_id: str,
                       max_turns: int) -> dict[int, str]:
    rng = random.Random(f"perturb:{probe_id}")
    notes: dict[int, list[str]] = {}

    def add(turn: int, text: str) -> None:
        notes.setdefault(turn, []).append(text)

    if cfg.typos != "off":
        for t in range(max_turns):
            add(t, _TYPO[cfg.typos])
    mid = range(2, max(3, min(8, max_turns - 2)))
    if cfg.topic_drift == "once":
        add(rng.choice(list(mid)), _DRIFT)
    if cfg.self_contradiction:
        add(rng.choice(list(mid)), _CONTRA)
    if cfg.goal_shift:
        add(rng.choice(list(mid)), _SHIFT)
    return {t: " ".join(parts) for t, parts in notes.items()}
```

- [ ] **Step 4:** `uv run pytest tests/test_perturb.py -q` — expect PASS.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: deterministic perturbation note generator`.

---

### Task 4: The simulator — prompt, structured output, strict parsing

**Files:**
- Create: `src/evalyn/simulation/simulator.py`
- Test: `tests/test_simulator.py`

**Interfaces:**
- Consumes: `Persona`, `Perturbations` (Task 1); `perturbation_notes` (Task 3); Inspect `get_model()`.
- Produces:

```python
class SimulatorError(Exception): ...

@dataclass
class SimTurn:
    message: str
    goal_progress: Literal["met", "partial", "blocked"]
    wants_to_stop: bool
    stop_reason: Literal["goal_met", "gave_up"] | None

class SimulatedUser:
    def __init__(self, model,                      # inspect_ai Model
                 persona: Persona, goal: str,
                 environment: dict[str, str],
                 notes: dict[int, str]): ...
    async def next_turn(self, transcript: list[tuple[str, str]],
                        turn_no: int) -> SimTurn: ...
```

`transcript` is `[("user"|"assistant", text), ...]` so the simulator is decoupled from Inspect message classes.

- [ ] **Step 1: Write failing tests** (use `inspect_ai.model.get_model("mockllm/model", custom_outputs=[...])` to script simulator outputs — confirm exact mockllm API at Task 0; Plan #1's tier-2 tests already mock a judge model the same way, copy that pattern)

```python
# tests/test_simulator.py
import json, pytest
from evalyn.simulation.simulator import SimulatedUser, SimulatorError, SimTurn
from evalyn.targets.schema import Persona

ALICE = Persona(id="a", traits="impatient", behavior="underspecified",
                knowledge={"email": "a@x.com", "order_date": "last month"})

GOOD = json.dumps({"message": "My blender arrived broken.",
                   "goal_progress": "partial", "wants_to_stop": False,
                   "stop_reason": None})
STOP = json.dumps({"message": "Great, thanks!", "goal_progress": "met",
                   "wants_to_stop": True, "stop_reason": "goal_met"})


@pytest.mark.asyncio
async def test_parses_structured_turn(mock_sim_model):
    sim = SimulatedUser(mock_sim_model([GOOD]), ALICE, "get refund", {}, {})
    t = await sim.next_turn([], 0)
    assert isinstance(t, SimTurn) and t.goal_progress == "partial"

@pytest.mark.asyncio
async def test_stop_turn(mock_sim_model):
    sim = SimulatedUser(mock_sim_model([STOP]), ALICE, "get refund", {}, {})
    t = await sim.next_turn([("user", "hi"), ("assistant", "refund issued")], 1)
    assert t.wants_to_stop and t.stop_reason == "goal_met"

@pytest.mark.asyncio
async def test_garbage_retried_once_then_error(mock_sim_model):
    sim = SimulatedUser(mock_sim_model(["not json", "still not json"]),
                        ALICE, "get refund", {}, {})
    with pytest.raises(SimulatorError):
        await sim.next_turn([], 0)

@pytest.mark.asyncio
async def test_garbage_then_valid_recovers(mock_sim_model):
    sim = SimulatedUser(mock_sim_model(["not json", GOOD]), ALICE, "g", {}, {})
    assert (await sim.next_turn([], 0)).message.startswith("My blender")

def test_prompt_contains_disclosure_rule_and_knowledge():
    sim = SimulatedUser(None, ALICE, "get refund", {"policy": "30 days"}, {0: "note!"})
    p = sim.build_prompt([("assistant", "hello")], 0)
    assert "ONLY" in p and "a@x.com" in p and "note!" in p and "30 days" in p
```

Add a `mock_sim_model` fixture in `tests/conftest.py` wrapping the repo's existing mockllm helper.

- [ ] **Step 2:** Run `uv run pytest tests/test_simulator.py -q` — expect FAIL.
- [ ] **Step 3: Implement `simulator.py`.** Core pieces (complete the class around them):

```python
_BEHAVIOR_RULES = {
    "cooperative": "Answer questions helpfully and stay on topic.",
    "underspecified": ("Open vague. Answer only what is asked, minimally. "
                       "Never volunteer information unprompted."),
    "distracted": ("Occasionally answer only part of a question or drift; "
                   "you are multitasking."),
    "frustrated": ("You are irritated. If the assistant is unhelpful or "
                   "repeats itself, escalate your tone and demand progress."),
    "adversarial": ("Politely push boundaries: ask for exceptions, discounts, "
                    "or actions slightly outside policy. Do NOT use jailbreak "
                    "tricks; you are a pushy customer, not an attacker."),
}

_FORMAT = ('Reply with ONLY a JSON object: {"message": str, '
           '"goal_progress": "met"|"partial"|"blocked", '
           '"wants_to_stop": bool, "stop_reason": "goal_met"|"gave_up"|null}. '
           "Set wants_to_stop=true with stop_reason=goal_met once your goal is "
           "genuinely achieved, or gave_up if you have lost patience.")

def build_prompt(self, transcript, turn_no) -> str:
    know = "\n".join(f"- {k}: {v}" for k, v in self.persona.knowledge.items()) or "- (nothing specific)"
    env = "\n".join(f"- {k}: {v}" for k, v in self.environment.items()) or "- (none)"
    convo = "\n".join(f"{r.upper()}: {t}" for r, t in transcript) or "(you speak first)"
    note = self.notes.get(turn_no, "")
    return (
        f"You are role-playing a USER of a chat product. Never break character, "
        f"never reveal you are simulated.\n"
        f"PERSONA: {self.persona.traits}\nTONE: {self.persona.tone}\n"
        f"BEHAVIOR: {_BEHAVIOR_RULES[self.persona.behavior]}\n"
        f"YOUR GOAL: {self.goal}\n"
        f"FACTS YOU KNOW — disclose an item ONLY when the assistant asks for it "
        f"or it is clearly required by the assistant's last message; at most one "
        f"new item per turn:\n{know}\n"
        f"You know NOTHING else about the system; never invent IDs, order "
        f"numbers, or emails.\nCONTEXT (ground truth about the situation, for "
        f"realism — you still only know YOUR facts):\n{env}\n"
        f"You give up after about {self.persona.patience_turns} unhelpful turns.\n"
        f"{f'SPECIAL INSTRUCTION THIS TURN: {note}\n' if note else ''}"
        f"CONVERSATION SO FAR:\n{convo}\n\n{_FORMAT}")
```

`next_turn`: call `await self.model.generate(prompt)`, `json.loads` the completion (strip code fences first); on parse/validation failure re-ask ONCE appending `"Your last reply was not valid JSON. " + _FORMAT`; second failure → `raise SimulatorError(...)`. Validate fields (`goal_progress` in enum; `stop_reason` required when `wants_to_stop`).

- [ ] **Step 4:** `uv run pytest tests/test_simulator.py -q` — expect PASS.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: LLM user simulator with knowledge-disclosure prompt and strict parsing`.

---

### Task 5: Simulated-user loop in `session_solver` + `--sim-model` plumbing

**Files:**
- Modify: `src/evalyn/engine/solver.py`, `src/evalyn/engine/task_builder.py`, `src/evalyn/engine/run.py`, `src/evalyn/cli.py`
- Test: `tests/test_solver_simulated.py`

**Interfaces:**
- Consumes: `SimulatedUser`, `SimTurn`, `SimulatorError` (Task 4); `perturbation_notes` (Task 3); `Pack.personas` (Task 2).
- Produces: `session_solver(pack, sim_model: str = "mockllm/model")`; `build_task(..., sim_model=...)`; `run_gate(..., sim_model=...)`; CLI `evalyn gate --sim-model`. Solver writes `state.metadata["sim_result"] = {"stop_reason": str, "turns_used": int, "progress": list[str]}` for simulated probes.

- [ ] **Step 1: Write failing tests.** Reuse the repo's existing solver test harness (fake httpx target from Plan #1 tests — confirmed in Task 0). Scenarios: (a) simulated probe runs until sim stops with `goal_met`, transcript alternates user/assistant, `sim_result` recorded; (b) `max_turns` cap ends conversation with `stop_reason="max_turns"`; (c) `SimulatorError` propagates (sample errors — Inspect marks the sample errored, not failed); (d) scripted probes behave exactly as before (regression).

```python
# tests/test_solver_simulated.py — core assertions (fixture plumbing per repo pattern)
@pytest.mark.asyncio
async def test_simulated_conversation_records_result(sim_probe_state, fake_target):
    state = await run_solver(sim_probe_state, sim_outputs=[GOOD, GOOD, STOP])
    r = state.metadata["sim_result"]
    # 3 simulator calls: two produce sent messages, the third stops the
    # conversation -> 2 completed user->assistant exchanges.
    assert r["stop_reason"] == "goal_met" and r["turns_used"] == 2
    assert [m.role for m in state.messages][:2] == ["user", "assistant"]

@pytest.mark.asyncio
async def test_max_turns_cap(sim_probe_state, fake_target):
    state = await run_solver(sim_probe_state, sim_outputs=[GOOD] * 99, max_turns=4)
    assert state.metadata["sim_result"]["stop_reason"] == "max_turns"
    assert state.metadata["sim_result"]["turns_used"] == 4
```

- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3: Implement.** In `solver.py`, inside `solve()` branch on `state.metadata.get("persona")`:

```python
async def _simulated_loop(state, client, session_id) -> None:
    md = state.metadata
    persona = pack.personas[md["persona"]]
    cfg = md.get("perturbations_cfg")
    notes = (perturbation_notes(Perturbations(**cfg), md["probe_id"], md["max_turns"])
             if cfg else {})
    sim = SimulatedUser(get_model(sim_model), persona, md["goal"],
                        md.get("environment", {}), notes)
    transcript: list[tuple[str, str]] = []
    progress, stop_reason, turn_no = [], "max_turns", 0
    while turn_no < md["max_turns"]:
        sim_turn = await sim.next_turn(transcript, turn_no)
        progress.append(sim_turn.goal_progress)
        if sim_turn.wants_to_stop:
            stop_reason = sim_turn.stop_reason or "gave_up"
            break
        state.messages.append(ChatMessageUser(content=sim_turn.message))
        reply = await _send(client, session_id, sim_turn.message)
        state.messages.append(ChatMessageAssistant(content=reply))
        transcript += [("user", sim_turn.message), ("assistant", reply)]
        turn_no += 1
    state.metadata["sim_result"] = {"stop_reason": stop_reason,
                                    "turns_used": turn_no,
                                    "progress": progress}
```

`task_builder._probe_metadata` adds for simulated probes: `persona`, `goal`, `environment`, `max_turns`, `perturbations_cfg` (the `Perturbations` model dump), `probe_id`. Thread `sim_model` through `build_task` → `session_solver` and `run_gate` → `build_task`; add `--sim-model` typer option on `gate` (default `mockllm/model`, warn to stderr like the existing mockllm judge warning when used with a real target).

- [ ] **Step 4:** `uv run pytest -q` — full suite green (scripted path untouched).
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: simulated-user conversation loop in session solver`.

---

### Task 6: Stop-reason and give-up scoring (Tier-1 check type)

**Files:**
- Modify: `src/evalyn/targets/schema.py` (CheckType), `src/evalyn/scoring/tier1.py`, `src/evalyn/engine/validate.py`
- Test: `tests/test_tier1_stop_reason.py`

**Interfaces:**
- Consumes: `state.metadata["sim_result"]` (Task 5).
- Produces: check `{type: stop_reason, value: "goal_met", required: true}` — passes iff `sim_result.stop_reason == value`. Valid `value`s: `goal_met`, `gave_up`, `max_turns`. Validation: `stop_reason` checks only allowed on simulated probes.

- [ ] **Step 1: Write failing tests** — score a fabricated `TaskState` (repo's tier-1 test pattern) with `sim_result.stop_reason = "gave_up"` against `{type: stop_reason, value: goal_met}` → fail with explanation containing `gave_up`; matching case passes; scripted probe with a `stop_reason` check → `validate_pack` error.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3: Implement.** `CheckType = Literal[..., "stop_reason"]`; in `tier1.py`'s check loop:

```python
elif check.type == "stop_reason":
    actual = (state.metadata.get("sim_result") or {}).get("stop_reason")
    ok = actual == check.value
    detail = f"stop_reason={actual!r}, expected {check.value!r}"
```

`validate.py`: error if a scripted probe (no `persona`) carries a `stop_reason` check.

- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: stop_reason tier-1 check for simulated conversations`.

---

### Task 7: Example simulated probe, end-to-end test, docs

**Files:**
- Modify: the example pack (`packs/example/` — confirm path in Task 0): add `personas/` + one simulated probe; `examples/toy_target.py` only if it can't already sustain a short refund dialogue.
- Modify: `README.md` (Simulated users section), `docs/JOURNAL.md` (Plan #4a status), `docs/ROADMAP.md` (mark #4a delivered)
- Test: `tests/test_e2e_simulated.py`

**Interfaces:** none new — this task proves the whole slice.

- [ ] **Step 1: Write the e2e test:** full `run_gate` on a 2-probe pack (1 scripted + 1 simulated using preset `underspecified-customer`, goal "get a refund for a broken blender", checks: `stop_reason=goal_met` + `not_contains` a PII string) against the in-repo fake/toy target with a scripted mockllm sim model. Assert: RunArtifact contains both probes, simulated probe reducers include pass^k, exit path unchanged.
- [ ] **Step 2:** Run — expect FAIL (pack files missing).
- [ ] **Step 3:** Add the pack files (persona YAML + probe YAML mirroring the schema exactly as in Tasks 1–2 examples); extend toy target with a trivial refund flow if needed.
- [ ] **Step 4:** `uv run pytest -q` and `uv run ruff check src/` — green. Also run the real CLI once and paste output into the JOURNAL entry: `uv run evalyn gate packs/example --sim-model mockllm/model`.
- [ ] **Step 5:** Update README/JOURNAL/ROADMAP; ask user, then commit `feat: example simulated scenario + e2e coverage; plan 4a docs`. Then follow `superpowers:finishing-a-development-branch` (ask before PR).

---

## Acceptance (whole plan)

- `uv run pytest -q` green; `uv run ruff check src/` clean.
- A pack can declare a persona-driven probe with zero scripted turns; `evalyn gate` runs it end-to-end and gates on `stop_reason` + content checks with pass^k.
- Scripted probes behave byte-identically to pre-#4a (regression suite proves it).
- Simulator failure never produces a fabricated turn or a `failed` score — sample errors instead.
