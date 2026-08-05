"""CLI `evalyn discover` — preflight refusals and exit-code contract (Task 10).

Every test here is zero-spend: `CliRunner` drives the command, and the run seam
`evalyn.discovery.run.run_discovery` is monkeypatched (either to a crafted
`DiscoveryArtifact` or to a guard that raises if it is ever reached). No real
model is called and no target server is needed.

Exit-code contract (R10-0): 0 = completed (findings never fail it), 2 =
setup/preflight refusal before any spend, 3 = the run ran but every session
errored.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from evalyn.cli import app
from evalyn.discovery.run import DiscoveryArtifact

runner = CliRunner()

REPO = Path(__file__).resolve().parent.parent.parent
PACK = str(REPO / "packs" / "example")

INJ = "prompt-injection-bypass"   # tier 1, deterministic (no rubric judge)
PII = "pii-leak"                  # tier 1, deterministic
HALL = "hallucination"           # tier 3, needs a rubric judge


def _artifact(*, sessions_total: int, error_count: int,
              confirmed: int = 0) -> DiscoveryArtifact:
    """A minimal completed-run record for exit-code / proceed assertions."""
    return DiscoveryArtifact(
        pack_name="example", pack_hash="a" * 64,
        agent_model="openai/gpt-5-mini", judge_model="mockllm/model",
        rubric_judge_model=None, created_at="2026-08-05T00:00:00+00:00",
        findings=[], error_count=error_count, sessions_total=sessions_total,
        confirmed_count=confirmed, live_spend_usd=0.0, reconciled_spend_usd=0.0,
        budget_exhausted=False, partial=False, objectives=[INJ],
        log_path="runs/logs")


def _no_spend(monkeypatch):
    """Install a run seam that fails loudly if any preflight lets a run start."""
    async def guard(pack, cfg):
        raise AssertionError("run_discovery must not be called — preflight "
                             "should have refused before any spend")
    monkeypatch.setattr("evalyn.discovery.run.run_discovery", guard)


def _returns(monkeypatch, art: DiscoveryArtifact):
    async def fake(pack, cfg):
        return art
    monkeypatch.setattr("evalyn.discovery.run.run_discovery", fake)


# --------------------------------------------------------------- help / smoke

def test_discover_help_lists_flags():
    result = runner.invoke(app, ["discover", "--help"])
    assert result.exit_code == 0
    assert "--objective" in result.stdout
    assert "--allow-family-collision" in result.stdout


# ------------------------------------------------------------- R10-6 dry-run

def test_dry_run_exits_0_and_makes_no_calls(monkeypatch):
    _no_spend(monkeypatch)  # asserts run_discovery is never reached
    result = runner.invoke(app, ["discover", "--target", PACK, "--dry-run"])
    assert result.exception is None
    assert result.exit_code == 0
    out = result.stdout
    assert "dry-run" in out
    assert "curious-auditor" in out          # persona axis
    assert "8899" in out                     # resolved + allowlist-checked target
    assert "discoveries" in out              # staging dir


def test_dry_run_shows_selected_objectives(monkeypatch):
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ, "--dry-run"])
    assert result.exit_code == 0
    assert INJ in result.stdout


# ------------------------------------------------- R10-1 family collision

def test_family_collision_refuses_exit_2(monkeypatch):
    # discovery agent and rubric judge share the openai family → REFUSE.
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--agent-model", "openai/gpt-5-mini",
                                 "--rubric-judge-model", "openai/gpt-4o",
                                 "--dry-run"])
    assert result.exit_code == 2
    assert "family" in result.stderr.lower()


def test_family_collision_allowed_proceeds(monkeypatch):
    # Same collision, but --allow-family-collision downgrades it to a warning
    # and the command proceeds (here to the dry-run plan).
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--agent-model", "openai/gpt-5-mini",
                                 "--rubric-judge-model", "openai/gpt-4o",
                                 "--allow-family-collision", "--dry-run"])
    assert result.exit_code == 0
    assert "warning" in result.stderr.lower()


def test_family_refuse_discriminates(monkeypatch):
    # Discrimination guard: WITHOUT the R10-1 preflight this exact invocation
    # would proceed to the dry-run plan and exit 0. The refusal is what makes
    # it exit 2 — so this test would fail (green at 0) if the preflight vanished.
    _no_spend(monkeypatch)
    ok = runner.invoke(app, ["discover", "--target", PACK,
                             "--agent-model", "openai/gpt-5-mini",
                             "--rubric-judge-model", "anthropic/claude-sonnet-5",
                             "--dry-run"])
    assert ok.exit_code == 0          # different families → no collision → plan
    bad = runner.invoke(app, ["discover", "--target", PACK,
                              "--agent-model", "openai/gpt-5-mini",
                              "--rubric-judge-model", "openai/gpt-4o",
                              "--dry-run"])
    assert bad.exit_code == 2         # same family → refuse


# ------------------------------------------- R10-2 rubric objective, no judge

def test_rubric_objective_without_judge_refuses_exit_2(monkeypatch):
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", HALL])
    assert result.exit_code == 2
    assert "rubric" in result.stderr.lower()


def test_deterministic_only_selection_does_not_trigger_rubric_refuse(monkeypatch):
    # A deterministic objective needs no rubric judge → R10-2 must stay silent,
    # and the run proceeds (completed run → exit 0).
    _returns(monkeypatch, _artifact(sessions_total=1, error_count=0))
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ])
    assert result.exit_code == 0


# ----------------------------------------------- R10-5 tier-3 staleness gate

def test_tier3_on_uncalibrated_pack_refuses_exit_2(monkeypatch):
    # hallucination is tier-3; packs/example is uncalibrated. A rubric judge IS
    # supplied so R10-2 passes and the staleness gate (R10-5) is what refuses.
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", HALL,
                                 "--rubric-judge-model", "anthropic/claude-sonnet-5"])
    assert result.exit_code == 2
    assert "calibrat" in result.stderr.lower()


def test_tier3_staleness_allow_uncalibrated_proceeds_with_banner(monkeypatch):
    _returns(monkeypatch, _artifact(sessions_total=1, error_count=0))
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", HALL,
                                 "--rubric-judge-model", "anthropic/claude-sonnet-5",
                                 "--allow-uncalibrated"])
    assert result.exit_code == 0
    assert "uncalibrated" in result.stderr.lower()


def test_deterministic_only_selection_does_not_trigger_staleness(monkeypatch):
    # tier-1 only, uncalibrated pack → staleness gate must not fire; run proceeds.
    _returns(monkeypatch, _artifact(sessions_total=1, error_count=0))
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ])
    assert result.exit_code == 0
    assert "calibrat" not in result.stderr.lower()


# --------------------------------------------------- R10-4 --max-usd 0 reject

def test_max_usd_zero_rejected_exit_2(monkeypatch):
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ, "--max-usd", "0"])
    assert result.exit_code == 2
    assert "max_usd_per_run" in result.stderr   # points to the pack field


# ------------------------------------------------ R10-3 cap drops hunts loudly

def test_session_cap_drops_objectives_prints_notice(monkeypatch):
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ, "--objective", PII,
                                 "--max-sessions", "1", "--dry-run"])
    assert result.exit_code == 0
    # one persona, cap 1 → only the first objective is scheduled; PII is dropped
    # and the operator must be told, by name, in a dedicated notice (not merely
    # by appearing in the objectives listing).
    assert "dropped" in result.stderr.lower()
    assert PII in result.stderr


def test_max_sessions_zero_is_setup_error_exit_2(monkeypatch):
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ, "--max-sessions", "0"])
    assert result.exit_code == 2


# --------------------------------------------------- R10-0 exit-code contract

def test_completed_run_with_findings_exits_0(monkeypatch):
    _returns(monkeypatch, _artifact(sessions_total=2, error_count=0, confirmed=1))
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ])
    assert result.exit_code == 0     # findings never fail the command


def test_completed_run_without_findings_exits_0(monkeypatch):
    _returns(monkeypatch, _artifact(sessions_total=2, error_count=0, confirmed=0))
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ])
    assert result.exit_code == 0


def test_all_sessions_errored_exits_3(monkeypatch):
    _returns(monkeypatch, _artifact(sessions_total=2, error_count=2))
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ])
    assert result.exit_code == 3


def test_some_but_not_all_sessions_errored_still_exits_0(monkeypatch):
    # error_count < sessions_total is a completed (partial) run, not run-invalid.
    _returns(monkeypatch, _artifact(sessions_total=2, error_count=1))
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ])
    assert result.exit_code == 0


# ----------------------------------------------------- setup errors (exit 2)

def test_bad_pack_exits_2(tmp_path):
    result = runner.invoke(app, ["discover", "--target", str(tmp_path / "none")])
    assert result.exit_code == 2


def test_bad_allowlist_exits_2(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://evil.example.com")
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", INJ, "--dry-run"])
    assert result.exit_code == 2


def test_unknown_objective_exits_2(monkeypatch):
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", "no-such-objective", "--dry-run"])
    assert result.exit_code == 2


def test_unknown_persona_exits_2(monkeypatch):
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--persona", "no-such-persona", "--dry-run"])
    assert result.exit_code == 2
    assert "persona" in result.stderr.lower()


def test_unknown_playbook_exits_2(monkeypatch):
    _no_spend(monkeypatch)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--playbook", "no-such-playbook", "--dry-run"])
    assert result.exit_code == 2
    assert "playbook" in result.stderr.lower()
