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


def test_estimate_cost_sums_models():
    usage = {"anthropic/claude-3-5-sonnet-latest": _U(1000, 1000)}
    cost = estimate_cost(usage)
    assert cost > 0


# --- fail-open canaries: _judge_usd() returns 0.0 on ANY metering failure
# (per the brief), which silently disables the budget cap. These tests make an
# Inspect upgrade that moves the private import a RED test, not a silent no-op.

def test_inspect_private_model_usage_import_canary():
    from inspect_ai.model._model import model_usage
    assert callable(model_usage)
    assert isinstance(model_usage(), dict)


def test_judge_usd_does_not_hit_fallback_under_real_import():
    import warnings

    from evalyn.engine.run import _judge_usd

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert _judge_usd() == 0.0  # no eval ran in this context: empty usage
    assert caught == []  # the except-path warning must NOT fire


def test_judge_usd_warns_loudly_when_metering_unavailable(monkeypatch):
    from evalyn.engine import run as run_mod

    def boom(_usage):
        raise RuntimeError("inspect internals moved")

    monkeypatch.setattr(run_mod, "estimate_cost", boom)
    with pytest.warns(RuntimeWarning, match="budget cap not enforced"):
        assert run_mod._judge_usd() == 0.0  # return value contract unchanged


# --- post-hoc metering in run_gate (budget is checked AFTER the eval; the
# artifact must be written BEFORE BudgetExceeded is raised) ---

def test_run_gate_over_cap_writes_artifact_then_raises(toy_target, monkeypatch,
                                                       tmp_path):
    from evalyn.engine.run import run_gate

    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    monkeypatch.chdir(tmp_path)  # keep runs/ writes out of the repo
    # example pack cap is the default max_usd_per_run=5.0; meter above it
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda: 7.5)
    pack = load_pack(str(REPO_EXAMPLE))
    with pytest.raises(BudgetExceeded, match="max_usd_per_run"):
        run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"))
    # the partial artifact survives the breach, with the spend recorded
    [artifact] = (tmp_path / "runs").glob("*.json")
    assert json.loads(artifact.read_text())["judge_usd"] == 7.5


def test_run_gate_under_cap_records_judge_usd(toy_target, monkeypatch, tmp_path):
    from evalyn.engine.run import run_gate

    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda: 0.25)
    pack = load_pack(str(REPO_EXAMPLE))
    art = run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"))
    assert art.judge_usd == 0.25
