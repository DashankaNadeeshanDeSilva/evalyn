"""Judge-spend metering against the pack's ``budget.max_usd_per_run``.

Metering is POST-HOC: cost is computed after ``inspect_eval`` returns, so a
run can overshoot the cap — there is no mid-run stop. The cap bounds what a
run is allowed to have spent before its results are trusted/used; the breach
is raised after metering (and after the run artifact is written, so a partial
artifact survives for inspection). Only Evalyn's OWN judge-model spend
(Tier-2/3 LLM calls) is metered; target-side HTTP spend is the product under
test and is never counted.
"""

from __future__ import annotations

import warnings

# (usd per 1k input tokens, usd per 1k output tokens). Substring match on model
# id, LONGEST key first (never dict order — "gpt-4o-mini" must beat "gpt-4o").
# Static table, alphabetized; update as pricing changes.
PRICES: dict[str, tuple[float, float]] = {
    "claude-3-5-haiku": (0.0008, 0.004),
    "claude-3-5-sonnet": (0.003, 0.015),  # retired id: old baselines/records
    "claude-sonnet-5": (0.003, 0.015),
    "gpt-4o": (0.0025, 0.010),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-5-mini": (0.00025, 0.002),
    "gpt-5-nano": (0.00005, 0.0004),
}
# Unknown-model fallback: a genuine conservative UPPER bound (opus-tier). A
# mid-tier guess would under-meter an expensive judge ~5x and silently keep the
# cap from ever tripping (PR #4 fix #8).
_DEFAULT = (0.015, 0.075)


class BudgetExceeded(Exception): ...


def price_for(model_id: str) -> tuple[float, float]:
    # longest key first so the most specific substring wins regardless of
    # dict insertion order
    for key in sorted(PRICES, key=len, reverse=True):
        if key in model_id:
            return PRICES[key]
    warnings.warn(
        f"no price entry for model {model_id!r} — metering with the "
        f"conservative upper-bound default {_DEFAULT} USD per 1k tokens; add "
        f"the model to evalyn.engine.budget.PRICES for accurate budgeting",
        RuntimeWarning, stacklevel=2)
    return _DEFAULT


def estimate_cost(usage_by_model: dict) -> float:
    total = 0.0
    for model_id, u in usage_by_model.items():
        pin, pout = price_for(model_id)
        total += (getattr(u, "input_tokens", 0) / 1000.0) * pin
        total += (getattr(u, "output_tokens", 0) / 1000.0) * pout
    return total
