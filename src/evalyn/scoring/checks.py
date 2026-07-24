from __future__ import annotations


def check_result(check: str, tier: int, required: bool, weight: float,
                 passed: bool | None, score: float, turn: int | None = None,
                 evidence: str = "", unsure: bool = False) -> dict:
    return {"check": check, "tier": tier, "required": required, "weight": float(weight),
            "passed": passed, "score": float(score), "turn": turn,
            "evidence": evidence, "unsure": unsure}
