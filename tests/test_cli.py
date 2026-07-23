from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from evalyn.cli import app
from evalyn.engine.baseline import save_baseline
from evalyn.engine.gate import evaluate_gate
from evalyn.engine.run import ProbeResult, RunArtifact

runner = CliRunner()

REPO = Path(__file__).resolve().parent.parent
PACK = str(REPO / "packs" / "example")


def _probe(pid: str, *, safety: bool = False, kind: str = "regression",
           pass_k: float = 1.0, mean: float = 1.0) -> ProbeResult:
    return ProbeResult(
        id=pid, category="cat", kind=kind, safety_critical=safety, samples=3,
        reducers={
            "pass_at_3": {"tier1": 1.0 if mean > 0 else 0.0},
            "pass_k_3": {"tier1": pass_k},
            "mean": {"tier1": mean},
        })


def _artifact(probes: list[ProbeResult], pack_hash: str = "a" * 64) -> RunArtifact:
    return RunArtifact(
        pack_name="example", pack_hash=pack_hash, judge_model="mockllm/model",
        created_at="2026-07-23T00:00:00+00:00", probes=probes, log_path="runs/logs")


def _fake_run_gate(art: RunArtifact):
    def fake(pack, judge_model="mockllm/model", **kwargs):
        return art
    return fake


# ---------------------------------------------------------------- validate-pack

def test_validate_pack_command_clean(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    result = runner.invoke(app, ["validate-pack", PACK])
    assert result.exit_code == 0
    assert "OK" in result.stdout or "passed" in result.stdout.lower()


def test_validate_pack_exits_1_on_bad_pack(tmp_path):
    # a structurally valid pack whose probe references an unknown invariant
    pack_dir = tmp_path / "badpack"
    (pack_dir / "probes").mkdir(parents=True)
    (pack_dir / "target.yaml").write_text(
        "name: bad\n"
        "sessions:\n"
        "  open: { method: POST, path: /session }\n"
        "env: { base_url: http://localhost:8899 }\n"
        "allowlist: [http://localhost:8899]\n")
    (pack_dir / "probes" / "p.yaml").write_text(
        "- id: p1\n"
        "  category: c\n"
        "  turns: [hi]\n"
        "  checks:\n"
        "    - { type: invariant, ref: no-such-invariant, required: true }\n")
    result = runner.invoke(app, ["validate-pack", str(pack_dir)])
    assert result.exit_code == 1


def test_validate_pack_exits_1_on_unloadable_pack(tmp_path):
    result = runner.invoke(app, ["validate-pack", str(tmp_path / "nowhere")])
    assert result.exit_code == 1


# ------------------------------------------------------------------ gate: infra

def test_gate_exit_code_2_on_bad_allowlist(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://evil.example.com")
    result = runner.invoke(app, ["gate", "--target", PACK])
    assert result.exit_code == 2


def test_gate_exit_code_2_on_pack_error(tmp_path):
    result = runner.invoke(app, ["gate", "--target", str(tmp_path / "nowhere")])
    assert result.exit_code == 2


def test_gate_exit_code_2_on_run_error(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")

    def boom(pack, judge_model="mockllm/model", **kwargs):
        raise ConnectionError("target unreachable")

    monkeypatch.setattr("evalyn.engine.run.run_gate", boom)
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == 2
    assert "run error" in result.stderr  # not a usage error


def test_gate_dry_run_makes_no_calls(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")

    def must_not_run(pack, judge_model="mockllm/model", **kwargs):
        raise AssertionError("run_gate must not be called under --dry-run")

    monkeypatch.setattr("evalyn.engine.run.run_gate", must_not_run)
    result = runner.invoke(app, ["gate", "--target", PACK, "--dry-run"])
    assert result.exit_code == 0
    assert "dry-run" in result.stdout


# ------------------------------------------------- gate: mock-judge warning

def test_gate_warns_when_mock_judge_meets_classifier_checks(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    result = runner.invoke(app, ["gate", "--target", PACK, "--dry-run"])
    assert result.exit_code == 0  # verdict-neutral: warning must not change the exit code
    assert "warning:" in result.stderr
    assert "mockllm" in result.stderr


def test_gate_no_mock_judge_warning_with_real_judge(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    result = runner.invoke(app, ["gate", "--target", PACK, "--dry-run",
                                 "--judge-model", "openai/gpt-4o-mini"])
    assert result.exit_code == 0
    assert "warning:" not in result.stderr


def test_gate_no_mock_judge_warning_without_classifier_checks(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    minipack = str(REPO / "tests" / "fixtures" / "minipack")
    result = runner.invoke(app, ["gate", "--target", minipack, "--dry-run"])
    assert result.exit_code == 0
    assert "warning:" not in result.stderr


# --------------------------------------------------- gate: exit-code mapping
# Amendment A2: derive the expected exit code from the gate policy applied to
# the artifact the CLI actually evaluated — never accept a set of codes.

def test_gate_exit_0_when_policy_passes(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("ok-probe", safety=True, pass_k=1.0)])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    expected = evaluate_gate(art, None)
    assert expected.exit_code == 0  # sanity: this synthetic artifact must pass
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == expected.exit_code
    assert "PASS" in result.stdout


def test_gate_exit_1_when_safety_probe_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("leaky", safety=True, pass_k=0.0, mean=0.5)])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    expected = evaluate_gate(art, None)
    assert expected.exit_code == 1  # sanity: this synthetic artifact must fail
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == expected.exit_code
    assert "FAIL" in result.stdout


def test_gate_live_exit_code_matches_gate_policy(toy_target, monkeypatch, tmp_path):
    # Amendment A2 strengthening of the brief's flaky-safety test: instead of
    # accepting exit_code in (0, 1), read the artifact this very run produced,
    # apply the gate policy to it, and require the CLI's exit code to be EQUAL.
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    monkeypatch.chdir(tmp_path)  # run_gate writes runs/ relative to cwd
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json")])
    artifacts = sorted((tmp_path / "runs").glob("*-example.json"))
    assert artifacts, "gate run wrote no artifact"
    art = RunArtifact.from_dict(json.loads(artifacts[-1].read_text()))
    expected = evaluate_gate(art, None)
    assert result.exit_code == expected.exit_code
    assert "gate" in result.stdout.lower()
    assert ("FAIL" if expected.exit_code else "PASS") in result.stdout


# ------------------------------------------------------------- gate: baseline

def test_gate_update_baseline_writes_and_exits_0(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("ok-probe")])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    baseline_path = tmp_path / "baseline.json"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path),
                                 "--update-baseline"])
    assert result.exit_code == 0
    saved = RunArtifact.from_dict(json.loads(baseline_path.read_text()))
    assert saved == art


# Carry-note 1: warn (not fail) when baseline pack hash differs from current.
def test_gate_warns_on_pack_hash_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    baseline_art = _artifact([_probe("ok-probe")], pack_hash="b" * 64)
    baseline_path = tmp_path / "baseline.json"
    save_baseline(baseline_art, str(baseline_path))
    current = _artifact([_probe("ok-probe")], pack_hash="a" * 64)
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(current))
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path)])
    expected = evaluate_gate(current, baseline_art)
    assert result.exit_code == expected.exit_code  # a warning, never a failure
    assert "warning:" in result.stdout
    assert "pack hash" in result.stdout


# Carry-note 2: warn about probes present in baseline but absent from current
# (they are invisible to the gate diff).
def test_gate_warns_on_probes_missing_from_current(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    baseline_art = _artifact([_probe("kept-probe"), _probe("dropped-probe")])
    baseline_path = tmp_path / "baseline.json"
    save_baseline(baseline_art, str(baseline_path))
    current = _artifact([_probe("kept-probe")])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(current))
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path)])
    expected = evaluate_gate(current, baseline_art)
    assert result.exit_code == expected.exit_code  # a warning, never a failure
    assert "warning:" in result.stdout
    warning_line = next(ln for ln in result.stdout.splitlines() if "dropped-probe" in ln)
    assert warning_line.startswith("warning:")
    assert "kept-probe" not in warning_line
