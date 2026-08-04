"""Live USD metering for `discover` — the hard ceiling on an autonomous agent.

The discovery loop checks `meter.exhausted()` at the TOP of every step and
stops the session with `stop_reason="budget"` when it trips; `BudgetStop` is
always caught inside the session runner so budget exhaustion yields a partial
result, never destroys gathered evidence.

Two charging paths, deliberately different:

- **Agent reasoning calls** are charged EXACTLY from the `ModelOutput.usage`
  the call returns, priced by `engine.budget.price_for` (`charge_output`).
- **Tier-3 judge confirmations** hide their usage (`tier3.score_transcript`
  does not surface it), so they are charged a conservative live estimate
  (`charge_estimate`) and reconciled post-hoc from the Inspect eval log via
  `reconcile` — the same `log.stats.model_usage` source and `estimate_cost`
  arithmetic as `engine/run.py`'s `_judge_usd`, so `discover` and `gate` keep
  ONE accounting. (Never `inspect_ai.model.model_usage()`: it returned `{}`
  on real runs — live-confirmed 2026-07-28.)

The ceiling is a safety boundary: when in doubt, charge MORE, not less. A
meter that under-reports is a runaway spend.
"""
from __future__ import annotations

import warnings

from inspect_ai.model import ModelOutput, ModelUsage

from evalyn.engine.budget import estimate_cost

#: Safety constant: pessimistic per-call usage charged when a `ModelOutput`
#: carries no usage. A discover reasoning prompt (persona + objective +
#: playbook + the full labeled transcript at the pack turn cap) measures in
#: the low thousands of input tokens and the JSON action reply in the
#: hundreds; 16k in / 4k out is several times any such call — a deliberate
#: OVERcharge, because a provider that omits usage omits it on EVERY call,
#: and a 0.0 live charge would mean `exhausted()` could never trip while the
#: loop spends real money (the runaway the budget exists to stop).
_PESSIMISTIC_USAGE = ModelUsage(
    input_tokens=16_000, output_tokens=4_000, total_tokens=20_000)


class BudgetStop(Exception):
    """The meter tripped mid-step. Caught inside the session runner — a budget
    stop always yields a partial result, never an exception out of the loop."""


class SpendMeter:
    """Accumulating USD meter with a hard cap. `exhausted()` is conservative:
    AT the cap counts as exhausted — there is no budget left to spend."""

    def __init__(self, cap_usd: float) -> None:
        if cap_usd < 0:
            raise ValueError(f"cap_usd must be >= 0, got {cap_usd}")
        self.cap_usd = cap_usd
        self._spent = 0.0

    @property
    def spent_usd(self) -> float:
        return self._spent

    @property
    def remaining_usd(self) -> float:
        return max(self.cap_usd - self._spent, 0.0)

    def exhausted(self) -> bool:
        return self._spent >= self.cap_usd

    def charge_output(self, model: str, out: ModelOutput) -> None:
        """Charge an agent reasoning call exactly, from its returned usage."""
        usage = getattr(out, "usage", None)
        if usage is None:
            # Charge a pessimistic worst-case, never 0.0: live charging must
            # stand on its own (reasoning calls may not appear in the tier-3
            # eval log, so the post-hoc reconcile is no backstop for them).
            warnings.warn(
                f"model output from {model!r} carries no usage — charging a "
                f"pessimistic estimate ({_PESSIMISTIC_USAGE.input_tokens} in / "
                f"{_PESSIMISTIC_USAGE.output_tokens} out tokens) instead of "
                f"an exact figure", RuntimeWarning, stacklevel=2)
            usage = _PESSIMISTIC_USAGE
        # estimate_cost, not hand-rolled token->USD arithmetic: one accounting
        # shared with `reconcile` and `engine/run.py`, no drift surface.
        self._spent += estimate_cost({model: usage})

    def charge_estimate(self, usd: float) -> None:
        """Charge a conservative estimate for a call whose usage is hidden
        (tier-3 confirmations). Reconciled post-hoc from the eval log."""
        if usd < 0:
            # A negative "estimate" is a refund — a raise of the effective cap.
            raise ValueError(f"estimate must be >= 0, got {usd}")
        self._spent += usd


def reconcile(log) -> float:
    """Authoritative post-run judge spend, read from the returned eval log.

    Same source (`log.stats.model_usage`) and same arithmetic (`estimate_cost`)
    as `engine/run.py`'s `_judge_usd` — this figure must agree with `gate`,
    not invent a second accounting.
    """
    try:
        return estimate_cost(log.stats.model_usage)
    except Exception as e:
        # Fail-open: a malformed log must not kill a finished run — but be
        # LOUD, a silent 0.0 would quietly disable the post-hoc accounting.
        warnings.warn(
            f"spend reconcile unavailable — usd_from_log unreliable for this "
            f"run ({type(e).__name__}: {e})", RuntimeWarning, stacklevel=2)
        return 0.0
