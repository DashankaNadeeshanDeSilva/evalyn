"""End-to-end: the gate drives the live toy target and pass^k catches the flaky guard.

Amendment A2: the toy target's injection guard is deliberately flaky, so a run's
verdict is genuinely nondeterministic. These tests never assert a fixed verdict
and never accept a set of exit codes — they derive the expected verdict from the
artifact the run itself produced and require exact agreement, plus the artifact
invariants that hold regardless of the leak.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from evalyn.engine.gate import evaluate_gate
from evalyn.engine.run import RunArtifact, run_gate
from evalyn.targets.loader import load_pack

REPO = Path(__file__).resolve().parent.parent
PACK = str(REPO / "packs" / "example")
EVALYN_BIN = str(Path(sys.executable).parent / "evalyn")

# A2 invariant: every probe declared in packs/example must appear in the artifact.
EXPECTED_PROBE_IDS = {
    "injection-trust-pivot",
    "injection-control-benign",
    "inv-basic-reply",
    "grounding-work-history",
}
# A1/A2 invariant: reducer keys are labeled by the ACTUAL trial count — the task
# runs every probe at the pack-wide max epochs (3, from injection-trust-pivot).
EXPECTED_REDUCER_KEYS = {"pass_at_3", "pass_k_3", "mean"}


def _latest_artifact(runs_dir: Path) -> RunArtifact:
    artifacts = sorted(runs_dir.glob("*-example.json"))
    assert artifacts, "gate run wrote no artifact to runs/"
    return RunArtifact.from_dict(json.loads(artifacts[-1].read_text()))


def _assert_leak_independent_invariants(art: RunArtifact) -> None:
    """A2: everything here must hold whether or not the flaky guard leaked."""
    assert {p.id for p in art.probes} == EXPECTED_PROBE_IDS
    for probe in art.probes:
        assert set(probe.reducers) == EXPECTED_REDUCER_KEYS, (
            f"probe {probe.id}: reducer keys must be actual-trial-labeled, "
            f"got {sorted(probe.reducers)}")


def test_full_gate_flow_records_passk_divergence(toy_target, monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    monkeypatch.chdir(tmp_path)  # run_gate writes runs/ relative to cwd
    pack = load_pack(PACK)
    art = run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"))

    _assert_leak_independent_invariants(art)
    # the artifact on disk is the same run the engine returned (round-trips)
    assert _latest_artifact(tmp_path / "runs") == art

    inj = next(p for p in art.probes if p.id == "injection-trust-pivot")
    pass_at = min(inj.reducers["pass_at_3"].values())
    pass_k = min(inj.reducers["pass_k_3"].values())
    # pass@k >= pass^k always; the whole point of recording both
    assert pass_at >= pass_k

    result = evaluate_gate(art, baseline=None)
    assert "Evalyn gate" in result.report_md
    # A2 (replaces `exit_code in (0, 1)`): the safety probe gates on pass^k,
    # never on mean — it must appear as a SAFETY failure exactly when pass^k < 1,
    # regardless of how high its mean is.
    safety_failures = [f for f in result.failures if "injection-trust-pivot" in f]
    if pass_k < 1.0:
        assert result.exit_code == 1
        assert safety_failures and all("SAFETY" in f for f in safety_failures)
    else:
        assert not safety_failures
    # the verdict is exactly the failure list, nothing else
    assert result.exit_code == (1 if result.failures else 0)


def test_cli_gate_exit_code_equals_policy_verdict_live(toy_target, tmp_path):
    """A2 at true e2e scope: real process, real exit code, live target."""
    env = {**os.environ, "EVALYN_TARGET_URL": toy_target}
    proc = subprocess.run(
        [EVALYN_BIN, "gate", "--target", PACK,
         "--baseline", str(tmp_path / "none.json")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)

    art = _latest_artifact(tmp_path / "runs")
    _assert_leak_independent_invariants(art)
    expected = evaluate_gate(art, None)
    # exact equality with the gate policy applied to the artifact this very
    # process wrote — not merely "in (0, 1)"
    assert proc.returncode == expected.exit_code, proc.stderr
    assert "Evalyn gate" in proc.stdout
    assert ("FAIL" if expected.exit_code else "PASS") in proc.stdout


def test_cli_validate_pack_live(toy_target, tmp_path):
    env = {**os.environ, "EVALYN_TARGET_URL": toy_target}
    proc = subprocess.run(
        [EVALYN_BIN, "validate-pack", PACK],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr + proc.stdout
