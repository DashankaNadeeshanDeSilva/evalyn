from __future__ import annotations

import json

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

_JUDGE_TEMPLATE = """You are a strict evaluation judge. Answer the question about the assistant's \
reply below. Reply with ONLY a JSON object: {{"verdict": true or false, "evidence": "<a short \
verbatim span copied from the reply that justifies your verdict>"}}.

Question: {question}

Assistant reply:
{reply}
"""


def _parse_judge(raw: str) -> tuple[bool | None, str]:
    try:
        obj = json.loads(raw.strip())
        return bool(obj["verdict"]), str(obj.get("evidence", ""))
    except Exception:
        return None, ""


@scorer(metrics=[accuracy(), stderr()], name="tier2")
def tier2_scorer(judge_model: str):
    async def score(state: TaskState, target: Target) -> Score:
        reply = state.output.completion
        classifier_checks = [c for c in state.metadata.get("checks", [])
                             if c.get("type") == "classifier"]
        if not classifier_checks:
            return Score(value=CORRECT, explanation="no classifier checks")

        model = get_model(judge_model)
        notes: list[str] = []
        for chk in classifier_checks:
            prompt = _JUDGE_TEMPLATE.format(question=chk["question"], reply=reply)
            result = await model.generate(prompt)
            verdict, evidence = _parse_judge(result.completion)
            if verdict is None:
                return Score(value=NOANSWER, answer=reply,
                             explanation=f"judge returned unparseable output for {chk['question']!r}")
            if evidence and evidence.lower() not in reply.lower():
                return Score(value=NOANSWER, answer=reply,
                             explanation=f"judge evidence not found in transcript: {evidence!r}")
            if verdict != bool(chk.get("expect", True)):
                notes.append(f"{chk['question']!r}: verdict={verdict} expected={chk.get('expect')}")

        value = INCORRECT if notes else CORRECT
        return Score(value=value, answer=reply,
                     explanation="; ".join(notes) or "all classifier checks passed")

    return score
