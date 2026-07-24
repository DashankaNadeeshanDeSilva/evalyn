# Evalyn-pro Plan #4b — Trustworthy Judging (Panels, κ Calibration, Abstention, Review Loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Evalyn's judging from single rubric judge + ±1-point calibration (Plan #2a) to diverse-family judge panels with escalation, Cohen's-κ certification, first-class abstention excluded from pass rates, and a review-queue → anchor/probe promotion loop.

**Architecture:** Panel escalation wraps the Plan-#2a Tier-3 rubric judge as a second stage; abstention becomes a distinct score state that the reduction layer (`run.py`) and gate layer (`gate.py`) understand; calibration gains κ statistics and a certification record; a new `evalyn.review` package owns the queue/label/promote loop. Spec: `docs/superpowers/specs/2026-07-24-evalyn-pro-design.md` §5.3–5.5, §6.4, §13.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, Inspect AI scorers (`NOANSWER` score state), typer CLI, pytest. No numpy/scipy — κ is ~20 lines of stdlib.

**Sequencing:** Execute after Plan #4a merges. Branch: `feat/pro-judging-trust` off `dev`. **Hard dependency on Plan #2a's** Tier-3 rubric judge (`type: rubric` checks, self-consistency k=3, `unsure` state) and calibration harness (`packs/*/anchors/*.yaml`, `evalyn calibrate`).

## Global Constraints

- Judge model family ≠ generator family by default (existing locked rule); a panel must span ≥2 distinct model families or validation fails.
- Abstained verdicts are EXCLUDED from pass-rate denominators, never counted as pass or fail (spec D9).
- Judge/API failure → bounded retries → abstention. Never a silent default score (spec §8).
- Safety-critical probes still gate on pass^k over NON-abstained trials, and gate policy bounds the abstained fraction.
- Test-first; `uv run pytest -q` + `uv run ruff check src/` before every commit; ask user before every commit/push/PR; user-name-only commit identity.

---

### Task 0: Re-baseline against post-#2a/#3/#4a code

**Files:** read-only pass over `src/evalyn/scoring/` (tier2, tier3/rubric module name, self-consistency implementation), calibration module + `evalyn calibrate` CLI, anchors YAML format, `run.py` reduction, `gate.py` policy, `Check` schema (`weight`/`required` semantics from #2a).

- [ ] **Step 1:** Record the actual names this plan must call: the Tier-3 rubric scorer entrypoint, its per-call verdict struct (score 1–5, `unsure` flag, self-consistency spread), the anchors file schema, and the calibration record path/format from #2a.
- [ ] **Step 2:** Confirm how Inspect represents abstention in scores (`NOANSWER` value constant and how `_reduce_log_to_probes` currently treats it) — the abstention plumbing in Tasks 3–4 keys off this.
- [ ] **Step 3:** Identify where #2a threads `--rubric-judge-model`; the panel config extends the same path.
- [ ] **Step 4:** Amend this plan file inline where reality diverges; ask user, then commit `docs: re-baseline evalyn-pro plan 4b`.

---

### Task 1: κ statistics module

**Files:**
- Create: `src/evalyn/scoring/kappa.py`
- Test: `tests/test_kappa.py`

**Interfaces:**
- Produces:

```python
def cohens_kappa(a: list[str], b: list[str]) -> float          # nominal labels
def weighted_kappa(a: list[int], b: list[int],
                   min_label: int = 1, max_label: int = 5) -> float  # linear weights
def agreement_table(a: list[str], b: list[str]) -> dict[tuple[str, str], int]
```

Both raise `ValueError` on empty or unequal-length inputs. Perfect agreement → 1.0; chance-level → ~0.0.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_kappa.py
import pytest
from evalyn.scoring.kappa import cohens_kappa, weighted_kappa, agreement_table


def test_perfect_agreement():
    assert cohens_kappa(["p", "f", "p"], ["p", "f", "p"]) == pytest.approx(1.0)

def test_known_value():
    # Classic worked example: po=0.7, pe=0.5 -> kappa=0.4
    a = ["y"] * 25 + ["y"] * 15 + ["n"] * 15 + ["n"] * 45
    b = ["y"] * 25 + ["n"] * 15 + ["y"] * 15 + ["n"] * 45
    assert cohens_kappa(a, b) == pytest.approx(0.4, abs=1e-9)

def test_all_one_label_degenerate_is_1():
    assert cohens_kappa(["p", "p"], ["p", "p"]) == pytest.approx(1.0)

def test_weighted_penalizes_distance():
    near = weighted_kappa([1, 2, 3, 4, 5], [2, 3, 4, 5, 5])
    far = weighted_kappa([1, 2, 3, 4, 5], [5, 5, 1, 1, 1])
    assert near > far

def test_unequal_lengths_raise():
    with pytest.raises(ValueError):
        cohens_kappa(["p"], ["p", "f"])

def test_agreement_table_counts():
    t = agreement_table(["p", "p", "f"], ["p", "f", "f"])
    assert t[("p", "p")] == 1 and t[("p", "f")] == 1 and t[("f", "f")] == 1
```

- [ ] **Step 2:** Run `uv run pytest tests/test_kappa.py -q` — expect FAIL.
- [ ] **Step 3: Implement**

```python
# src/evalyn/scoring/kappa.py
"""Judge-vs-human agreement statistics (spec §5.4). Stdlib only."""
from collections import Counter


def _validate(a, b):
    if not a or len(a) != len(b):
        raise ValueError(f"need equal non-empty label lists, got {len(a)}/{len(b)}")


def cohens_kappa(a: list[str], b: list[str]) -> float:
    _validate(a, b)
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[l] / n) * (cb[l] / n) for l in set(ca) | set(cb))
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def weighted_kappa(a: list[int], b: list[int],
                   min_label: int = 1, max_label: int = 5) -> float:
    _validate(a, b)
    labels = list(range(min_label, max_label + 1))
    span = max_label - min_label or 1
    n = len(a)
    ca, cb = Counter(a), Counter(b)
    obs = Counter(zip(a, b))
    w = {(i, j): abs(i - j) / span for i in labels for j in labels}
    num = sum(w[i, j] * obs.get((i, j), 0) / n for i in labels for j in labels)
    den = sum(w[i, j] * (ca[i] / n) * (cb[j] / n) for i in labels for j in labels)
    if den == 0:
        return 1.0
    return 1 - num / den


def agreement_table(a: list[str], b: list[str]) -> dict[tuple[str, str], int]:
    _validate(a, b)
    return dict(Counter(zip(a, b)))
```

- [ ] **Step 4:** Run `uv run pytest tests/test_kappa.py -q` — expect PASS.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: cohen's and weighted kappa agreement statistics`.

---

### Task 2: Panel config schema + panel voting core

**Files:**
- Modify: `src/evalyn/targets/schema.py` (add `JudgingSpec` to `TargetSpec`), `src/evalyn/engine/validate.py`
- Create: `src/evalyn/scoring/panel.py`
- Test: `tests/test_panel.py`

**Interfaces:**
- Produces:

```python
class JudgingSpec(BaseModel):                      # in schema.py
    panel_models: list[str] = Field(default_factory=list)   # >=3, >=2 families
    escalate_below_confidence: float = 0.7
    abstain_below_agreement: float = 0.67          # majority fraction floor
# TargetSpec gains: judging: JudgingSpec = Field(default_factory=JudgingSpec)

# panel.py
@dataclass
class PanelResult:
    verdict: Literal["pass", "fail", "abstain"]
    votes: list[tuple[str, str]]        # (model_name, "pass"|"fail"|"unsure")
    agreement: float                    # winning-vote fraction over non-unsure votes

async def run_panel(models: list, prompt: str,
                    abstain_below_agreement: float) -> PanelResult
```

Voting rule: `unsure` votes are discarded; majority of the rest wins; if fewer than 2 usable votes OR winning fraction < `abstain_below_agreement` → `abstain`. A judge call that errors after 2 retries counts as `unsure`.

- [ ] **Step 1: Write failing tests** — model-family validation (`["openai/a","openai/b","openai/c"]` → validate error, mixed families ok; <3 models with non-empty list → error); voting: 3×pass → (`pass`, 1.0); pass/pass/fail → (`pass`, 2/3); pass/fail/unsure → abstain (1/2 < 0.67 with 2 usable... assert per rule: agreement=0.5 → abstain); all-unsure → abstain; erroring judge model (mock raises) → counted as unsure, no exception.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3: Implement.** Family extraction = provider prefix before `/` (reuse #2a's judge≠generator family helper if one exists — check at Task 0). `run_panel` fires all judges concurrently (`asyncio.gather(..., return_exceptions=True)`), parses each with the same strict parse as the #2a rubric judge (reuse its parser), applies the voting rule above.
- [ ] **Step 4:** `uv run pytest tests/test_panel.py -q` — expect PASS; full suite green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: judge panel schema and majority-vote core`.

---

### Task 3: Escalation wiring — Tier-3 verdicts escalate to panel, then abstain

**Files:**
- Modify: the #2a Tier-3 rubric scorer module (name per Task 0)
- Test: `tests/test_escalation.py`

**Interfaces:**
- Consumes: `run_panel`, `JudgingSpec` (Task 2); #2a rubric-judge verdict struct (score, `unsure`, self-consistency spread).
- Produces: final Tier-3 Inspect `Score` where: confident single-judge verdict → unchanged (tier recorded as 2 in metadata); low-confidence (self-consistency spread ≥ threshold, `unsure`, or configured `escalate_below_confidence`) → panel verdict (tier 3); panel abstain → Inspect `NOANSWER` score with metadata `{"abstained": true, "votes": [...]}`.

- [ ] **Step 1: Write failing tests** (mockllm judges): confident rubric verdict never calls the panel (assert 1 judge call); high-spread verdict triggers panel and takes its majority; panel disagreement below floor yields `NOANSWER` with `abstained` metadata; empty `panel_models` disables escalation (pure #2a behavior — regression).
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3: Implement** inside the rubric scorer: after the #2a self-consistency verdict, compute `confidence = 1 - spread/4` (1–5 scale; exact formula: agreement of the k=3 samples — reuse #2a's spread), escalate when `confidence < pack.spec.judging.escalate_below_confidence` or verdict is `unsure`, building the panel prompt from the same rubric prompt used by the single judge.
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: tier-3 panel escalation with abstention`.

---

### Task 4: Abstention-aware reduction and gate policy

**Files:**
- Modify: `src/evalyn/engine/run.py` (`_reduce_log_to_probes`, `ProbeResult`), `src/evalyn/engine/gate.py`, `src/evalyn/targets/schema.py` (gate knobs)
- Test: `tests/test_abstention_gate.py`

**Interfaces:**
- Produces: `ProbeResult` gains `abstained: int` (count of abstained trials) and reducers computed over non-abstained trials only; `GateSpec` knobs on the pack (or gate config, per #2b's layout — Task 0): `max_abstained_fraction: float = 0.25` and `uncalibrated_dimensions: Literal["warn","block"] = "warn"`. Gate rules: probe abstained-fraction > max → probe fails with reason `too many abstentions`; safety-critical pass^k evaluated over non-abstained trials AND requires ≥1 non-abstained trial.

- [ ] **Step 1: Write failing tests:** build synthetic per-sample scores (repo's reduction test pattern): 4 trials with 1 `NOANSWER` + 3 pass → `abstained == 1`, `pass_k` computed over 3, probe passes; 4 trials with 3 `NOANSWER` → abstained fraction 0.75 > 0.25 → gate failure listing the probe; safety-critical probe with all trials abstained → gate failure (`no scoreable trials`).
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3: Implement** in `_reduce_log_to_probes`: partition sample-epoch scores into abstained (`NOANSWER`) vs scored; recompute pass_at/pass_k/mean over scored only; store `abstained`. In `evaluate_gate`: the two rules above, with report lines like `sim-1: ABSTAINED 3/4 trials (max_abstained_fraction=0.25)`.
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: abstention-aware reduction and gate rules`.

---

### Task 5: κ certification in `evalyn calibrate`

**Files:**
- Modify: #2a's calibration module + `evalyn calibrate` CLI command
- Test: `tests/test_calibrate_kappa.py`

**Interfaces:**
- Consumes: `cohens_kappa`, `weighted_kappa`, `agreement_table` (Task 1); #2a anchors format + calibration record.
- Produces: calibration record (the #2a committed file) gains per-dimension `{"kappa": float, "weighted_kappa": float, "n_anchors": int, "certified": bool, "rubric_hash": str}` with `certified = kappa >= threshold` (CLI `--min-kappa`, default 0.6). Gate consumes it per Task 4's `uncalibrated_dimensions` knob: `warn` prints to stderr; `block` fails the gate for probes using uncertified rubric dimensions. A rubric-file hash mismatch versus the record marks the dimension uncertified (stale).

- [ ] **Step 1: Write failing tests:** given anchors with known labels and scripted judge outputs — κ computed matches hand value; below `--min-kappa` → `certified: false` and CLI exit non-zero with per-dimension table; rubric hash change invalidates certification; gate `block` mode fails when a probe's rubric dimension is uncertified, `warn` mode passes with stderr warning.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3: Implement:** extend the #2a calibrate flow — after collecting judge verdicts vs human labels per dimension: binary pass/fail → `cohens_kappa`; 1–5 rubric scores → `weighted_kappa`; write the enriched record; print table `dimension | n | κ | weighted κ | certified`; worst 3 disagreements printed with anchor ids (from `agreement_table` + per-anchor diff).
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: kappa certification in calibrate with stale-rubric invalidation`.

---

### Task 6: Review queue emission + `evalyn review` labeling CLI

**Files:**
- Create: `src/evalyn/review/__init__.py`, `src/evalyn/review/queue.py`
- Modify: `src/evalyn/engine/run.py` (emit queue), `src/evalyn/cli.py` (add `review` command)
- Test: `tests/test_review_queue.py`

**Interfaces:**
- Produces:

```python
# queue.py
class QueueItem(BaseModel):
    probe_id: str
    epoch: int
    reason: Literal["abstained", "failed"]
    dimension: str | None            # rubric dimension or check type
    rationale: str                   # judge/check explanation
    transcript: list[dict]           # [{"role": ..., "content": ...}]
    label: str | None = None         # filled by review
    label_note: str | None = None

def write_queue(items: list[QueueItem], run_dir: Path) -> Path      # review_queue.jsonl
def load_queue(run_dir: Path) -> list[QueueItem]
def save_labels(items: list[QueueItem], run_dir: Path) -> Path      # labels.jsonl
```

CLI: `evalyn review runs/<ts>/` — iterates unlabeled items, prints transcript + rationale, prompts `label (pass/fail/skip)` and optional note via `typer.prompt`, writes `labels.jsonl` incrementally (resume-safe).

- [ ] **Step 1: Write failing tests:** `run_gate` on a pack with one failing + one abstaining probe emits `review_queue.jsonl` with 2 items incl. transcripts; `load_queue`/`save_labels` round-trip; review CLI driven via `typer.testing.CliRunner` with scripted input labels one item and skips another; re-running resumes at the skipped item.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3: Implement** — queue emission in `run_gate` after reduction (transcripts pulled from the Inspect eval log via `read_eval_log(log_path)` sample messages); CLI loop as specified.
- [ ] **Step 4:** `uv run pytest -q` — green.
- [ ] **Step 5:** `uv run ruff check src/`; ask user, then commit `feat: review queue emission and labeling CLI`.

---

### Task 7: Promotion — label → calibration anchor or draft probe; dogfood meta-eval

**Files:**
- Create: `src/evalyn/review/promote.py`
- Modify: `src/evalyn/cli.py` (add `promote` command), `docs/JOURNAL.md`, `docs/ROADMAP.md`, `README.md`
- Test: `tests/test_promote.py`

**Interfaces:**
- Consumes: `QueueItem` + labels (Task 6); anchors format (#2a); `Probe` schema (4a).
- Produces: `evalyn promote runs/<ts>/ --item <probe_id>:<epoch> --as anchor|probe [--out packs/<name>]`:
  - `--as anchor`: writes an anchors YAML entry (transcript + human label) in the #2a anchor schema → feeds the next `evalyn calibrate`.
  - `--as probe`: writes `probes/drafted/<probe_id>-r<n>.yaml` — a DRAFT simulated probe: goal auto-drafted from the queue item's scenario goal (or first user turn for scripted), persona carried over, failing check reproduced, `# DRAFT — review before enabling` header comment, and NOT loaded by `load_pack` until moved out of `drafted/`.

- [ ] **Step 1: Write failing tests:** promoting a labeled item as anchor produces a file `evalyn calibrate` accepts (run the loader on it); promoting as probe produces YAML that parses into a valid `Probe` once moved out of `drafted/`; promoting an unlabeled item errors; `drafted/` is ignored by `load_pack`.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement `promote.py` + CLI.
- [ ] **Step 4:** `uv run pytest -q`, `uv run ruff check src/` — green. **Dogfood check:** run `evalyn calibrate` on the example pack's anchors and paste the κ table into the JOURNAL entry.
- [ ] **Step 5:** Update README (Trustworthy judging section: panels, κ, abstention, review loop), JOURNAL, ROADMAP. Ask user, then commit `feat: review promotion to anchors and draft probes; plan 4b docs`. Then `superpowers:finishing-a-development-branch` (ask before PR).

---

## Acceptance (whole plan)

- Full suite green, ruff clean.
- A low-confidence rubric verdict escalates to a ≥2-family panel; persistent disagreement produces `NOANSWER` scores that are visibly excluded from pass rates and bounded by gate policy.
- `evalyn calibrate` prints per-dimension κ and refuses certification below `--min-kappa`; stale rubric hashes invalidate certification; gate can block on uncertified dimensions.
- `evalyn review` → `evalyn promote` turns a real failure into an anchor or a draft probe without hand-editing JSON.
