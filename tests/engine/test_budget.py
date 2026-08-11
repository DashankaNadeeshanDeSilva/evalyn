import json
from pathlib import Path

import pytest

from evalyn.engine.budget import BudgetExceeded, estimate_cost, price_for
from evalyn.targets.loader import load_pack

REPO_EXAMPLE = Path(__file__).resolve().parent.parent.parent / "packs" / "example"


class _U:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


def test_price_for_known_model():
    assert price_for("anthropic/claude-3-5-sonnet-latest")[0] > 0


def test_price_table_has_claude_sonnet_5_and_keeps_retired_key():
    # Task 12: current-generation judge model priced EXPLICITLY (not via the
    # unknown-model default); the retired claude-3-5-sonnet key stays (old
    # baselines/records may still name it)
    from evalyn.engine.budget import PRICES

    assert PRICES.get("claude-sonnet-5") == (0.003, 0.015)
    assert "claude-3-5-sonnet" in PRICES
    assert price_for("anthropic/claude-sonnet-5") == (0.003, 0.015)


def test_unknown_model_warns_and_gets_conservative_upper_bound():
    # PR #4 fix #8: the fallback must be a genuine UPPER bound (opus-tier), not
    # mid-tier sonnet pricing (an opus judge would cost ~5x and never trip the
    # cap) — and it must warn loudly instead of silently guessing.
    with pytest.warns(RuntimeWarning, match="no price entry"):
        assert price_for("someprovider/never-heard-of-this-model") == (0.015, 0.075)


def test_price_for_matches_longest_key_first_not_dict_order():
    # "gpt-4o-mini" contains "gpt-4o": correctness must come from longest-key
    # matching, never from dict insertion order (alphabetizing must not break it)
    assert price_for("openai/gpt-4o-mini") == (0.00015, 0.0006)
    assert price_for("openai/gpt-4o") == (0.0025, 0.010)


def test_estimate_cost_sums_models():
    usage = {"anthropic/claude-3-5-sonnet-latest": _U(1000, 1000)}
    cost = estimate_cost(usage)
    assert cost > 0


# --- fail-open canaries: _judge_usd(log) returns 0.0 on ANY metering failure
# (per the brief), which silently disables the budget cap. These tests make an
# Inspect upgrade that moves the log.stats.model_usage seam a RED test, not a
# silent no-op.

def test_inspect_evallog_stats_model_usage_canary():
    # Plan #2b Task 1 seam: _judge_usd reads log.stats.model_usage from the
    # RETURNED EvalLog (per-eval by construction — never the process-global
    # model_usage() ContextVar, which is invisible outside the eval loop and
    # accumulates across evals).
    from inspect_ai.log import EvalLog, EvalStats

    assert "stats" in EvalLog.model_fields
    assert "model_usage" in EvalStats.model_fields
    assert isinstance(EvalStats().model_usage, dict)


def test_judge_usd_does_not_hit_fallback_on_real_evalstats():
    import warnings
    from types import SimpleNamespace

    from inspect_ai.log import EvalStats

    from evalyn.engine.run import _judge_usd

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # a real (empty) EvalStats traverses cleanly: empty usage -> 0.0
        assert _judge_usd(SimpleNamespace(stats=EvalStats())) == 0.0
    assert caught == []  # the except-path warning must NOT fire


def test_judge_usd_warns_loudly_when_metering_unavailable(monkeypatch):
    from types import SimpleNamespace

    from evalyn.engine import run as run_mod

    def boom(_usage):
        raise RuntimeError("inspect internals moved")

    monkeypatch.setattr(run_mod, "estimate_cost", boom)
    log = SimpleNamespace(stats=SimpleNamespace(model_usage={}))
    with pytest.warns(RuntimeWarning, match="budget cap not enforced"):
        assert run_mod._judge_usd(log) == 0.0  # return value contract unchanged


# --- post-hoc metering in run_gate (budget is checked AFTER the eval; the
# artifact must be written BEFORE BudgetExceeded is raised) ---

def test_run_gate_over_cap_writes_artifact_then_raises(toy_target, monkeypatch,
                                                       tmp_path, live_pack_dir):
    from evalyn.engine.run import run_gate

    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    monkeypatch.chdir(tmp_path)  # keep runs/ writes out of the repo
    # example pack cap is the default max_usd_per_run=5.0; meter above it
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 7.5)
    pack = load_pack(live_pack_dir(REPO_EXAMPLE))
    with pytest.raises(BudgetExceeded, match="max_usd_per_run"):
        run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"),
                 out_dir=str(tmp_path / "runs"))
    # the partial artifact survives the breach, with the spend recorded
    [artifact] = (tmp_path / "runs").glob("*.json")
    assert json.loads(artifact.read_text())["judge_usd"] == 7.5


def test_run_gate_under_cap_records_judge_usd(toy_target, monkeypatch, tmp_path,
                                              live_pack_dir):
    from evalyn.engine.run import run_gate

    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.25)
    pack = load_pack(live_pack_dir(REPO_EXAMPLE))
    art = run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"),
                   out_dir=str(tmp_path / "runs"))
    assert art.judge_usd == 0.25
