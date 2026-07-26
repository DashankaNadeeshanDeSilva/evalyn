from __future__ import annotations


def check_result(check: str, tier: int, required: bool, weight: float,
                 passed: bool | None, score: float, turn: int | None = None,
                 evidence: str = "", unsure: bool = False) -> dict:
    return {"check": check, "tier": tier, "required": required, "weight": float(weight),
            "passed": passed, "score": float(score), "turn": turn,
            "evidence": evidence, "unsure": unsure}


def aggregate_trial(check_results: list[dict]) -> tuple[bool, bool, float | None]:
    """Shared-Contract trial aggregation over one (probe_id, epoch)'s CheckResults.

    Returns (required_pass, trial_unsure, trial_score):
    - required_pass: True iff EVERY required check has passed is True (a
      required False, unsure, or malformed passed=None => not a pass);
      trivially True with no required checks.
    - trial_unsure: no required check failed outright but at least one required
      check is unsure, OR non-required checks exist and ALL of them are unsure
      (a no-signal trial — NOANSWER accounting, distinct from a product failure).
    - trial_score: 0.0 if any required check failed; else the weighted mean
      over non-required checks, excluding unsure ones from numerator AND
      denominator; 1.0 if the probe declares NO non-required checks (required
      checks alone gate); None when non-required checks exist but ALL are
      unsure — there is no score signal, so the reducer must EXCLUDE the trial
      from mean_score (returning 1.0 there would score a judge outage as a
      perfect trial — fail-open, PR #4 fix #1).
    """
    required = [c for c in check_results if c["required"]]
    req_failed = any(c["passed"] is False for c in required)
    req_unsure = any(c["unsure"] for c in required)
    # contract-literal: pass iff EVERY required check has passed is True — a
    # malformed passed=None with unsure=False must not fail open into a pass
    required_pass = all(c["passed"] is True for c in required)
    trial_unsure = (not req_failed) and req_unsure

    if req_failed:
        return (False, trial_unsure, 0.0)

    non_required = [c for c in check_results if not c["required"]]
    usable = [c for c in non_required if not c["unsure"]]
    if non_required and not usable:
        # every non-required check is unsure: no score signal at all — an
        # unsure trial with no trial_score, never a fail-open 1.0
        return (required_pass, True, None)
    if not usable:
        # the probe has no non-required checks: required checks alone gate
        return (required_pass, trial_unsure, 1.0)
    num = sum(c["weight"] * c["score"] for c in usable)
    den = sum(c["weight"] for c in usable)
    return (required_pass, trial_unsure, num / den if den else 1.0)
