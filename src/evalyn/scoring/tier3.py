from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from inspect_ai.model import get_model
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    NOANSWER,
    Score,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState

from evalyn.scoring.checks import check_result
from evalyn.scoring.rubrics import grading_steps, load_rubric, parse_criteria
from evalyn.scoring.transcript import assistant_turns, labeled_transcript

_SCORE_PROMPT = """You are a strict evaluation judge. Score the assistant's behavior in the
conversation on the rubric criteria below, following these evaluation steps:
{steps}

Criteria to score: {criteria}

Score EACH criterion with an integer 1-5 (1=poor, 5=excellent). Reply with ONLY a
JSON object of the form:
{{"scores": {{"<criterion>": {{"score": <int 1-5>, "justification": "<one sentence>"}}, ...}}}}
with exactly one entry per listed criterion.

Conversation:
{transcript}
"""


def _normalize_score(s: int) -> float:
    return (max(1, min(5, int(s))) - 1) / 4.0


def _median(xs: list[int]) -> int:
    return int(statistics.median(sorted(xs)))


def _spread(xs: list[int]) -> int:
    return max(xs) - min(xs) if xs else 0


def _parse(raw: str, criteria: list[str]) -> dict[str, int] | None:
    """Strict per-criterion parse: every criterion present with an int score in
    1..5, else the whole sample is unparseable (None)."""
    try:
        scores = json.loads(raw.strip())["scores"]
        out: dict[str, int] = {}
        for name in criteria:
            v = scores[name]["score"]
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5:
                return None
            out[name] = v
        return out
    except Exception:
        return None


@dataclass
class RubricScore:
    """Per-criterion G-Eval outcome (reused by the Task-5 calibration harness)."""

    medians: dict[str, int] | None  # per-criterion medians; None when unsure
    samples: list[dict[str, int]]   # parsed per-sample scores (k self-consistency draws)
    steps: list[str]                # grading steps the judge followed
    rubric_hash: str
    unsure: bool = False
    reason: str = ""

    @property
    def score(self) -> float:
        """Normalized [0,1] check score: mean over criteria of (median-1)/4."""
        if not self.medians:
            raise ValueError(
                "RubricScore.score is undefined without medians (unsure result "
                "— check `unsure` before reading the score)")
        return sum(_normalize_score(m) for m in self.medians.values()) / len(self.medians)

    @property
    def passed(self) -> bool:
        """Binary verdict: mean of per-criterion medians >= 4."""
        if not self.medians:
            raise ValueError(
                "RubricScore.passed is undefined without medians (unsure result "
                "— check `unsure` before reading the verdict)")
        return sum(self.medians.values()) / len(self.medians) >= 4


async def score_transcript(rubric_text: str, rubric_hash: str, transcript: str,
                           judge_model: str, k: int = 3,
                           cache_dir: Path | None = None) -> RubricScore:
    """G-Eval phase 2: k self-consistency judge draws, per-criterion medians.

    Unsure (never averaged away) when any sample is unparseable or any
    criterion's spread across the k draws is >= 2.
    """
    criteria = parse_criteria(rubric_text)
    steps = await grading_steps(rubric_text, rubric_hash, judge_model, cache_dir)
    model = get_model(judge_model)
    prompt = _SCORE_PROMPT.format(
        steps="\n".join(f"- {s}" for s in steps),
        criteria=", ".join(criteria), transcript=transcript)
    samples: list[dict[str, int]] = []
    for _ in range(k):
        out = await model.generate(prompt)
        parsed = _parse(out.completion, criteria)
        if parsed is not None:
            samples.append(parsed)
    if len(samples) < k:
        return RubricScore(None, samples, steps, rubric_hash, unsure=True,
                           reason=f"{k - len(samples)}/{k} samples unparseable")
    spreads = {c: _spread([s[c] for s in samples]) for c in criteria}
    disagreed = [c for c, sp in spreads.items() if sp >= 2]
    if disagreed:
        return RubricScore(None, samples, steps, rubric_hash, unsure=True,
                           reason=f"judge disagreement (spread >= 2) on {disagreed}")
    medians = {c: _median([s[c] for s in samples]) for c in criteria}
    return RubricScore(medians, samples, steps, rubric_hash)


@scorer(metrics=[accuracy(), stderr()], name="tier3")
def tier3_scorer(pack, judge_model: str, k: int = 3,
                 cache_dir: Path | None = None):
    async def score(state: TaskState, target: Target) -> Score:
        checks = [c for c in (state.metadata or {}).get("checks", [])
                  if c.get("type") == "rubric"]
        if not checks:
            return Score(value=CORRECT, explanation="no rubric checks",
                         metadata={"checks": []})
        transcript = labeled_transcript(state)
        if not assistant_turns(state):
            # states without message history (single-shot solvers/tests) still
            # carry the reply in output — never hand the judge an empty transcript
            completion = state.output.completion if state.output else ""
            transcript = (transcript + "\n" if transcript else "") + \
                f"Assistant: {completion}"

        results: list[dict] = []
        rubric_meta: dict[str, dict] = {}
        req_fail, req_unsure = False, False
        notes: list[str] = []
        for chk in checks:
            rid = chk["rubric"]
            required = bool(chk.get("required", False))
            weight = float(chk.get("weight", 1.0))
            label = f"rubric:{rid}"
            rubric_text, rhash = load_rubric(pack, rid)
            res = await score_transcript(rubric_text, rhash, transcript,
                                         judge_model, k=k, cache_dir=cache_dir)
            rubric_meta[rid] = {"hash": rhash, "steps": res.steps}
            if res.unsure:
                results.append(check_result(label, 3, required, weight, None, 0.0,
                                            evidence=f"{res.reason}; samples={res.samples}",
                                            unsure=True))
                notes.append(f"{rid}: UNSURE {res.reason}")
                req_unsure = req_unsure or required
                continue
            passed = res.passed
            results.append(check_result(
                label, 3, required, weight, passed, res.score,
                evidence=f"medians={res.medians} samples={res.samples}"))
            if required and not passed:
                req_fail = True
                notes.append(f"{rid}: medians={res.medians} (mean < 4)")

        # viewer value: NOANSWER if a REQUIRED check was unsure; INCORRECT if a
        # required check failed; else CORRECT. (Reducer is the authority via metadata.)
        value = NOANSWER if (req_unsure and not req_fail) \
            else (INCORRECT if req_fail else CORRECT)
        return Score(value=value, answer=state.output.completion,
                     explanation="; ".join(notes) or "all rubric checks passed",
                     metadata={"checks": results, "rubrics": rubric_meta})

    return score
