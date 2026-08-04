"""The hard USD ceiling that makes an autonomous `discover` agent safe to run.

Two charging paths, deliberately different: agent reasoning calls are charged
EXACTLY from the `ModelOutput.usage` they return (via `engine.budget.price_for`);
tier-3 judge confirmations hide their usage, so they are charged a conservative
live estimate and reconciled post-hoc from the Inspect eval log. `reconcile`
must produce the SAME figure `engine/run.py` computes from the same log — one
accounting, not two.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from inspect_ai.model import ModelOutput, ModelUsage

from evalyn.discovery.meter import BudgetStop, SpendMeter, reconcile


def out_for(model: str, input_tokens: int, output_tokens: int) -> ModelOutput:
    return ModelOutput(
        model=model,
        usage=ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens,
                         total_tokens=input_tokens + output_tokens))


def test_meter_exhausts_at_cap():
    """Charge below the cap -> live; reach the cap -> exhausted (>= is the
    conservative boundary: AT the cap means no budget left to spend)."""
    meter = SpendMeter(cap_usd=0.01)
    assert not meter.exhausted()

    # gpt-5-mini PRICES: (0.00025, 0.002) per 1k tokens
    out = out_for("openai/gpt-5-mini", input_tokens=4_000, output_tokens=2_000)
    meter.charge_output("openai/gpt-5-mini", out)  # 0.001 + 0.004 = 0.005
    assert not meter.exhausted()
    assert meter.spent_usd == pytest.approx(0.005)
    assert meter.remaining_usd == pytest.approx(0.005)

    meter.charge_output("openai/gpt-5-mini", out)  # total 0.010 == cap
    assert meter.exhausted()
    assert meter.spent_usd == pytest.approx(0.010)
    assert meter.remaining_usd == 0.0


def test_charge_estimate_accumulates_and_trips():
    meter = SpendMeter(cap_usd=0.5)
    meter.charge_estimate(0.2)
    meter.charge_estimate(0.2)
    assert not meter.exhausted()
    assert meter.spent_usd == pytest.approx(0.4)
    meter.charge_estimate(0.2)
    assert meter.exhausted()
    assert meter.remaining_usd == 0.0  # clamped, never negative


def test_charge_estimate_rejects_a_negative_charge():
    """A negative "estimate" would be a refund — a raise of the effective cap."""
    meter = SpendMeter(cap_usd=1.0)
    with pytest.raises(ValueError):
        meter.charge_estimate(-0.01)


def test_missing_usage_is_loud_not_silent():
    """A ModelOutput without usage cannot be charged exactly; the meter must
    say so out loud (the log reconcile is the backstop), never swallow it."""
    meter = SpendMeter(cap_usd=1.0)
    out = ModelOutput(model="openai/gpt-5-mini")  # usage=None
    with pytest.warns(RuntimeWarning, match="usage"):
        meter.charge_output("openai/gpt-5-mini", out)
    assert meter.spent_usd == 0.0


def test_unpriced_model_charges_the_conservative_upper_bound():
    """Unknown model -> engine.budget's loud opus-tier default, not a silent
    under-charge (the safe direction for a runaway-spend boundary)."""
    meter = SpendMeter(cap_usd=1.0)
    out = out_for("mystery/model", input_tokens=1_000, output_tokens=1_000)
    with pytest.warns(RuntimeWarning, match="no price entry"):
        meter.charge_output("mystery/model", out)
    assert meter.spent_usd == pytest.approx(0.015 + 0.075)  # budget._DEFAULT


def test_zero_cap_is_exhausted_immediately():
    assert SpendMeter(cap_usd=0.0).exhausted()


def test_meter_rejects_a_negative_cap():
    with pytest.raises(ValueError):
        SpendMeter(cap_usd=-1.0)


def test_budget_stop_is_an_exception():
    assert issubclass(BudgetStop, Exception)


# --- reconcile: the log-authoritative post-hoc total --------------------------


def _fake_log(usage: dict):
    return SimpleNamespace(stats=SimpleNamespace(model_usage=usage))


def test_reconcile_reads_log_usage():
    """Same source (`log.stats.model_usage`), same arithmetic, same figure as
    `engine/run.py` — asserted against `_judge_usd` itself, not a copy of it."""
    from evalyn.engine.run import _judge_usd

    usage = {"anthropic/claude-sonnet-5": SimpleNamespace(input_tokens=88_035,
                                                          output_tokens=27_037)}
    got = reconcile(_fake_log(usage))
    # sonnet-5 PRICES: (0.003, 0.015) per 1k
    assert got == pytest.approx(88.035 * 0.003 + 27.037 * 0.015)
    assert got == _judge_usd(_fake_log(usage))


def test_reconcile_sums_across_models():
    usage = {
        "openai/gpt-5-mini": SimpleNamespace(input_tokens=10_000, output_tokens=0),
        "anthropic/claude-sonnet-5": SimpleNamespace(input_tokens=0, output_tokens=1_000),
    }
    assert reconcile(_fake_log(usage)) == pytest.approx(10 * 0.00025 + 1 * 0.015)


def test_reconcile_fail_open_is_loud():
    """A malformed log must not kill a finished run — but a silent 0.0 would
    quietly disable the post-hoc accounting, so it warns."""
    with pytest.warns(RuntimeWarning, match="reconcile"):
        assert reconcile(SimpleNamespace()) == 0.0  # no .stats
