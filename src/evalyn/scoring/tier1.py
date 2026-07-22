from __future__ import annotations
import re
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer, stderr
from inspect_ai.solver import TaskState
from evalyn.targets.loader import Pack

INVARIANT_PATTERNS: dict[str, re.Pattern] = {
    "no-internal-leak": re.compile(r"system prompt|/data/|internal path", re.IGNORECASE),
    "first-person": re.compile(r"\bhe (worked|was|is|has)\b|\bshe (worked|was|is|has)\b",
                               re.IGNORECASE),
}


def _is_empty(reply: str) -> bool:
    return reply.strip() == "" or reply.strip().lower() == "null"


def _eval_invariant(inv_id: str, reply: str) -> tuple[bool, str]:
    """Return (passed, evidence). non-empty is special-cased; others are match=violation."""
    if inv_id == "non-empty":
        return (not _is_empty(reply), "empty/null reply")
    pat = INVARIANT_PATTERNS.get(inv_id)
    if pat is None:
        return (True, "")  # unknown invariant is a no-op at Tier-1 (validate-pack flags it)
    m = pat.search(reply)
    return (m is None, m.group(0) if m else "")


@scorer(metrics=[accuracy(), stderr()], name="tier1")
def tier1_scorer(pack: Pack):
    pack_invariants = [i.id for i in pack.spec.invariants]

    async def score(state: TaskState, target: Target) -> Score:
        reply = state.output.completion
        results: list[dict] = []
        hard_fail = False
        fail_notes: list[str] = []

        # pack-level invariants: always required
        for inv_id in pack_invariants:
            ok, evidence = _eval_invariant(inv_id, reply)
            results.append({"check": f"invariant:{inv_id}", "ok": ok, "required": True})
            if not ok:
                hard_fail = True
                fail_notes.append(f"invariant '{inv_id}' ({evidence})")

        # probe-level deterministic checks
        for chk in state.metadata.get("checks", []):
            t = chk.get("type")
            required = bool(chk.get("required", False))
            if t == "invariant":
                ok, evidence = _eval_invariant(chk["ref"], reply)
                note = f"invariant '{chk['ref']}' ({evidence})"
            elif t == "contains":
                ok = chk["value"].lower() in reply.lower()
                note = f"must contain {chk['value']!r}"
            elif t == "not_contains":
                ok = chk["value"].lower() not in reply.lower()
                note = f"must not contain {chk['value']!r}"
            else:
                continue  # classifier checks handled by Tier-2
            results.append({"check": f"{t}:{chk.get('ref') or chk.get('value')}",
                            "ok": ok, "required": required})
            if not ok and required:
                hard_fail = True
                fail_notes.append(note)

        value = INCORRECT if hard_fail else CORRECT
        return Score(value=value, answer=reply,
                     explanation="; ".join(fail_notes) or "all deterministic checks passed",
                     metadata={"checks": results})

    return score
