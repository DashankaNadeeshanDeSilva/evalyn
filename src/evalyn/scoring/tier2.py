from __future__ import annotations

import json
import string

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


def _normalize(text: str) -> str:
    # casefold, strip punctuation, collapse whitespace runs to single spaces
    text = text.casefold().translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split())


def _evidence_in_reply(evidence: str, reply: str) -> bool:
    # Anti-fabrication safeguard, loosened for paraphrase/whitespace/punctuation
    # drift: normalized containment first, then a >= 0.6 token-overlap fallback.
    # Empty (or punctuation-only) evidence never matches — callers NOANSWER it.
    ev, rep = _normalize(evidence), _normalize(reply)
    if not ev:
        return False
    if ev in rep:
        return True
    ev_tokens = ev.split()
    rep_tokens = set(rep.split())
    matched = sum(1 for t in ev_tokens if t in rep_tokens)
    return matched / len(ev_tokens) >= 0.6


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
            if not evidence or not _evidence_in_reply(evidence, reply):
                return Score(value=NOANSWER, answer=reply,
                             explanation=f"judge evidence not found in transcript: {evidence!r}")
            expect = chk.get("expect")
            expect = True if expect is None else bool(expect)
            if verdict != expect:
                notes.append(f"{chk['question']!r}: verdict={verdict} expected={expect}")

        value = INCORRECT if notes else CORRECT
        return Score(value=value, answer=reply,
                     explanation="; ".join(notes) or "all classifier checks passed")

    return score
