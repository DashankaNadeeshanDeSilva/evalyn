from pathlib import Path

import pytest

from evalyn.engine.run import (RunArtifact, _reduce_log_to_probes,
                               pack_fingerprint, run_gate)
from evalyn.targets.loader import Pack, load_pack
from evalyn.targets.schema import Probe, TargetSpec

EXAMPLE = "packs/example"
REPO_EXAMPLE = Path(__file__).resolve().parent.parent.parent / "packs" / "example"


# --- fake-log helpers for the reducer (no Inspect run needed) ---

class _FakeScore:
    def __init__(self, metadata):
        self.value = None  # the reducer's authority is metadata checks, never value
        self.metadata = metadata


class _FakeSample:
    def __init__(self, pid, epoch, scores):
        self.id = pid
        self.epoch = epoch
        self.metadata = {"id": pid}
        self.scores = scores


class _FakeLog:
    def __init__(self, samples):
        self.samples = samples


def _cr(check, tier, required, passed, score, weight=1.0, unsure=False):
    return {"check": check, "tier": tier, "required": required, "weight": weight,
            "passed": passed, "score": score, "turn": None, "evidence": "",
            "unsure": unsure}


# Local stand-in for Task 12's shared `minimal_pack_with_probe` fixture.
def _mini_pack(pid="p", *, safety_critical=False, kind="regression", samples=2):
    spec = TargetSpec(
        name="mini",
        sessions={"chat": {"method": "POST", "path": "/chat"}},
        allowlist=["http://localhost:1"])
    probe = Probe(id=pid, category="misc", kind=kind, safety_critical=safety_critical,
                  turns=["hi"], checks=[{"type": "contains", "value": "x"}],
                  samples=samples)
    return Pack(spec=spec, probes=[probe], root=Path("."))


def test_reducer_combines_tiers_per_trial():
    # probe "p": required tier1 pass + non-required tier3 score 0.5, over 2 epochs
    pack = _mini_pack("p", samples=2)
    samples = []
    for epoch in (1, 2):
        samples.append(_FakeSample("p", epoch, {
            "tier1": _FakeScore({"checks": [_cr("inv", 1, True, True, 1.0)]}),
            "tier3": _FakeScore({"checks": [_cr("rubric:x", 3, False, True, 0.5)]}),
        }))
    [pr] = _reduce_log_to_probes(_FakeLog(samples), pack)
    assert pr.trials == 2 and pr.pass_k == 1.0 and pr.mean_score == 0.5
    assert pr.pass_at_k == 1.0 and pr.unsure_trials == 0
    assert pr.checks  # representative checks carried for the report


def test_reducer_nonrequired_miss_lowers_mean_not_pass_k():
    # closes the Task-2 interim window: Score.value is ignored; a non-required
    # miss must lower mean_score while the binary required verdict stays a pass
    pack = _mini_pack("p", samples=1)
    sample = _FakeSample("p", 1, {
        "tier1": _FakeScore({"checks": [_cr("inv", 1, True, True, 1.0)]}),
        "tier2": _FakeScore({"checks": [_cr("classifier:0", 2, False, False, 0.0)]}),
    })
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.pass_k == 1.0          # required checks all passed
    assert pr.mean_score == 0.0      # but the non-required miss drags the mean


def test_reducer_required_unsure_counts_noanswer_not_pass():
    pack = _mini_pack("p", samples=1)
    sample = _FakeSample("p", 1, {
        "tier2": _FakeScore({"checks": [_cr("classifier:0", 2, True, None, 0.0,
                                            unsure=True)]}),
    })
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.pass_k == 0.0 and pr.pass_at_k == 0.0  # unsure is never a pass
    assert pr.unsure_trials == 1                      # but is counted distinctly


def test_reducer_mixed_epochs_pass_at_k_vs_pass_k():
    pack = _mini_pack("p", samples=2)
    samples = [
        _FakeSample("p", 1, {"tier1": _FakeScore(
            {"checks": [_cr("inv", 1, True, True, 1.0)]})}),
        _FakeSample("p", 2, {"tier1": _FakeScore(
            {"checks": [_cr("inv", 1, True, False, 0.0)]})}),
    ]
    [pr] = _reduce_log_to_probes(_FakeLog(samples), pack)
    assert pr.trials == 2
    assert pr.pass_at_k == 1.0 and pr.pass_k == 0.0
    assert pr.mean_score == 0.5  # (1.0 + 0.0) / 2 (required fail zeroes epoch 2)


def test_reducer_sample_with_no_checks_anywhere_is_not_a_trial():
    # fail-closed: an errored trial (scores present but NO checks metadata in
    # any scorer) must leave trials == 0 so the gate hard-fails it as MISSING —
    # never a silent pass
    pack = _mini_pack("p", samples=1)
    sample = _FakeSample("p", 1, {
        "tier1": _FakeScore(None),   # Score.metadata defaults to None
        "tier2": _FakeScore({}),     # or metadata without "checks"
    })
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.trials == 0
    assert pr.pass_at_k == 0.0 and pr.pass_k == 0.0 and pr.mean_score == 0.0


def test_reducer_tolerates_unknown_scorer_names():
    # tier3 arrives in Task 4; the reducer must consume whatever scorers exist
    pack = _mini_pack("p", samples=1)
    sample = _FakeSample("p", 1, {
        "some-future-scorer": _FakeScore(
            {"checks": [_cr("rubric:tone", 3, False, True, 0.8)]}),
    })
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.trials == 1 and pr.mean_score == 0.8


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


def test_run_gate_produces_artifact_with_per_probe_trial_stats(toy_target, monkeypatch,
                                                               tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(EXAMPLE)
    art = run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"))
    ids = {p.id for p in art.probes}
    assert "injection-trust-pivot" in ids
    inj = next(p for p in art.probes if p.id == "injection-trust-pivot")
    assert inj.samples == 3
    assert inj.trials == 3
    assert inj.pass_at_k >= inj.pass_k  # pass@k >= pass^k always
    assert 0.0 <= inj.mean_score <= 1.0

    # Amendment A1: trial stats reflect ACTUAL trials collected, not declared
    # samples. The task runs every probe at the pack-wide max (3), so a probe
    # declaring samples=1 still collects 3 trials.
    ctl = next(p for p in art.probes if p.id == "injection-control-benign")
    assert ctl.samples == 1  # declared value is preserved
    assert ctl.trials == 3
    # CheckResults from BOTH scorers land in the representative checks
    assert {c["tier"] for c in inj.checks} == {1, 2}
    assert all(set(c) == {"check", "tier", "required", "weight", "passed", "score",
                          "turn", "evidence", "unsure"} for c in inj.checks)

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
