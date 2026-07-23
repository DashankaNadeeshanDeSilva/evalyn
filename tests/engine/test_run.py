from pathlib import Path

import pytest

from evalyn.engine.run import RunArtifact, pack_fingerprint, run_gate
from evalyn.targets.loader import load_pack

EXAMPLE = "packs/example"
REPO_EXAMPLE = Path(__file__).resolve().parent.parent.parent / "packs" / "example"


def test_run_gate_raises_on_non_success_eval_status(monkeypatch, tmp_path):
    """A failed Inspect eval must raise (CLI maps it to exit 2), not reduce an empty log."""
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    monkeypatch.chdir(tmp_path)  # keep any runs/ writes out of the repo
    pack = load_pack(str(REPO_EXAMPLE))

    class FakeLog:
        status = "error"
        samples = None
        location = None

    monkeypatch.setattr("evalyn.engine.run.inspect_eval", lambda *a, **k: [FakeLog()])
    with pytest.raises(RuntimeError, match="error"):
        run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"))


def test_run_gate_produces_artifact_with_per_probe_reducers(toy_target, monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(EXAMPLE)
    art = run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"))
    ids = {p.id for p in art.probes}
    assert "injection-trust-pivot" in ids
    inj = next(p for p in art.probes if p.id == "injection-trust-pivot")
    # the flaky injection probe ran 3 samples and has both pass@k and pass^k recorded
    assert inj.samples == 3
    assert any(r.startswith("pass_k") for r in inj.reducers)
    assert any(r.startswith("pass_at") for r in inj.reducers)

    # Amendment A1: reducer labels reflect ACTUAL trials, not declared samples.
    # Task 8 runs every probe at the pack-wide max (3), so a probe declaring
    # samples=1 still collects 3 trials and must be labeled pass_at_3/pass_k_3.
    ctl = next(p for p in art.probes if p.id == "injection-control-benign")
    assert ctl.samples == 1  # declared value is preserved
    assert "pass_at_3" in ctl.reducers
    assert "pass_k_3" in ctl.reducers
    assert "pass_at_1" not in ctl.reducers
    # each reducer entry carries both scorers' accuracies
    assert {"tier1", "tier2"} <= inj.reducers["pass_k_3"].keys()

    # artifact is self-contained and round-trips
    assert art.pack_name == pack.spec.name
    assert art.pack_hash == pack_fingerprint(pack)
    roundtrip = RunArtifact.from_dict(art.to_dict())
    assert roundtrip == art


def test_fingerprint_is_stable_and_pack_sensitive(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(EXAMPLE)
    assert pack_fingerprint(pack) == pack_fingerprint(load_pack(EXAMPLE))
    # sensitive to probe changes
    mutated = load_pack(EXAMPLE)
    mutated.probes[0].samples += 1
    assert pack_fingerprint(mutated) != pack_fingerprint(pack)
