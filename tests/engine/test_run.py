import json
import shutil
from pathlib import Path

import pytest

from evalyn.engine.run import (RunArtifact, _reduce_log_to_probes,
                               pack_fingerprint, run_gate)
from evalyn.targets.loader import load_pack

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


def test_reducer_combines_tiers_per_trial(minimal_pack_with_probe):
    # probe "p": required tier1 pass + non-required tier3 score 0.5, over 2 epochs
    pack = minimal_pack_with_probe("p", samples=2)
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


def test_reducer_nonrequired_miss_lowers_mean_not_pass_k(minimal_pack_with_probe):
    # closes the Task-2 interim window: Score.value is ignored; a non-required
    # miss must lower mean_score while the binary required verdict stays a pass
    pack = minimal_pack_with_probe("p", samples=1)
    sample = _FakeSample("p", 1, {
        "tier1": _FakeScore({"checks": [_cr("inv", 1, True, True, 1.0)]}),
        "tier2": _FakeScore({"checks": [_cr("classifier:0", 2, False, False, 0.0)]}),
    })
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.pass_k == 1.0          # required checks all passed
    assert pr.mean_score == 0.0      # but the non-required miss drags the mean


def test_reducer_required_unsure_counts_noanswer_not_pass(minimal_pack_with_probe):
    pack = minimal_pack_with_probe("p", samples=1)
    sample = _FakeSample("p", 1, {
        "tier2": _FakeScore({"checks": [_cr("classifier:0", 2, True, None, 0.0,
                                            unsure=True)]}),
    })
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.pass_k == 0.0 and pr.pass_at_k == 0.0  # unsure is never a pass
    assert pr.unsure_trials == 1                      # but is counted distinctly


def test_reducer_mixed_epochs_pass_at_k_vs_pass_k(minimal_pack_with_probe):
    pack = minimal_pack_with_probe("p", samples=2)
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


def test_reducer_sample_with_no_checks_anywhere_is_not_a_trial(minimal_pack_with_probe):
    # fail-closed: an errored trial (scores present but NO checks metadata in
    # any scorer) must leave trials == 0 so the gate hard-fails it as MISSING —
    # never a silent pass
    pack = minimal_pack_with_probe("p", samples=1)
    sample = _FakeSample("p", 1, {
        "tier1": _FakeScore(None),   # Score.metadata defaults to None
        "tier2": _FakeScore({}),     # or metadata without "checks"
    })
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.trials == 0
    assert pr.pass_at_k == 0.0 and pr.pass_k == 0.0 and pr.mean_score == 0.0


def test_reducer_tolerates_unknown_scorer_names(minimal_pack_with_probe):
    # tier3 arrives in Task 4; the reducer must consume whatever scorers exist
    pack = minimal_pack_with_probe("p", samples=1)
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
    art = run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"),
                   out_dir=str(tmp_path / "runs"))  # keep runs/ out of the repo CWD
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


def test_fingerprint_is_stable_and_pack_sensitive(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(EXAMPLE)
    assert pack_fingerprint(pack) == pack_fingerprint(load_pack(EXAMPLE))
    # sensitive to probe FILE changes (the fingerprint is over raw pack bytes)
    copy = tmp_path / "example"
    shutil.copytree(REPO_EXAMPLE, copy)
    probe_file = sorted((copy / "probes").glob("*.yaml"))[0]
    probe_file.write_bytes(probe_file.read_bytes() + b"\n# mutated\n")
    assert pack_fingerprint(load_pack(copy)) != pack_fingerprint(pack)


# --- Task 8: raw-bytes fingerprint, out_dir, atomic write, NOANSWER totals ---

_TWO_ENV_TARGET_YAML = """\
name: mini
sessions:
  message: { method: POST, path: /chat }
env:
  base_url: ${EVALYN_TARGET_URL:-http://localhost:8899}
allowlist:
  - http://localhost:8899
  - http://127.0.0.1:8899
"""

_TWO_ENV_PROBE_YAML = """\
- id: p1
  category: misc
  kind: regression
  turns: ["hi"]
  checks:
    - { type: contains, value: "x" }
  samples: 1
"""


@pytest.fixture
def tmp_pack_two_envs(tmp_path, monkeypatch):
    """The SAME pack files loaded under two env resolutions of base_url."""
    src = tmp_path / "pack"
    (src / "probes").mkdir(parents=True)
    (src / "target.yaml").write_text(_TWO_ENV_TARGET_YAML)
    (src / "probes" / "p.yaml").write_text(_TWO_ENV_PROBE_YAML)
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    p1 = load_pack(src)
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://127.0.0.1:8899")
    p2 = load_pack(src)
    return p1, p2


def test_fingerprint_ignores_env_localhost_vs_127(tmp_pack_two_envs):
    p1, p2 = tmp_pack_two_envs  # identical files, base_url localhost vs 127.0.0.1 via ${ENV}
    assert pack_fingerprint(p1) == pack_fingerprint(p2)


def test_run_gate_out_dir_writes_artifact_there_not_cwd(toy_target, monkeypatch,
                                                        tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    monkeypatch.chdir(tmp_path)  # a CWD runs/ write would be visible here
    pack = load_pack(str(REPO_EXAMPLE))
    out = tmp_path / "artifacts"
    art = run_gate(pack, judge_model="mockllm/model",
                   log_dir=str(tmp_path / "logs"), out_dir=str(out))
    [written] = list(out.iterdir())  # exactly one file — no temp-file leftovers
    assert written.suffix == ".json"
    assert json.loads(written.read_text())["pack_name"] == art.pack_name
    assert not (tmp_path / "runs").exists()  # nothing leaked into CWD runs/


def test_artifact_total_unsure_trials_sums_probe_unsure(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(str(REPO_EXAMPLE))
    unsure = _cr("classifier:0", 2, True, None, 0.0, unsure=True)
    samples = [
        _FakeSample("injection-trust-pivot", 1, {"tier2": _FakeScore({"checks": [unsure]})}),
        _FakeSample("injection-trust-pivot", 2, {"tier2": _FakeScore({"checks": [unsure]})}),
        _FakeSample("injection-control-benign", 1, {"tier2": _FakeScore({"checks": [unsure]})}),
    ]
    fake = _FakeLog(samples)
    fake.status = "success"
    fake.location = None
    monkeypatch.setattr("evalyn.engine.run.inspect_eval", lambda *a, **k: [fake])
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda: 0.0)
    art = run_gate(pack, judge_model="mockllm/model",
                   log_dir=str(tmp_path / "logs"), out_dir=str(tmp_path / "out"))
    assert art.total_unsure_trials == 3  # 2 + 1 across probes
    assert art.total_unsure_trials == sum(p.unsure_trials for p in art.probes)
    # NOANSWER accounting is surfaced in the serialized artifact too
    [written] = (tmp_path / "out").glob("*.json")
    assert json.loads(written.read_text())["total_unsure_trials"] == 3


# --- final review F1: gate threads the grading-steps cache into the task ---


def _fake_success_log():
    fake = _FakeLog([])
    fake.status = "success"
    fake.location = None
    return fake


def test_run_gate_defaults_cache_dir_to_pack_dot_cache(monkeypatch, tmp_path):
    """Gate runs must reuse the pack's .cache grading steps (same dir the
    calibrate CLI writes) instead of regenerating G-Eval steps per judge call."""
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(str(REPO_EXAMPLE))
    captured = {}

    def fake_build_task(pack_arg, **kwargs):
        captured.update(kwargs)
        return "task"

    monkeypatch.setattr("evalyn.engine.run.build_task", fake_build_task)
    monkeypatch.setattr("evalyn.engine.run.inspect_eval",
                        lambda *a, **k: [_fake_success_log()])
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda: 0.0)
    run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"),
             out_dir=str(tmp_path / "out"))
    assert captured["cache_dir"] == Path(pack.root) / ".cache"


# --- PR #4 fix #1: all-unsure non-required epochs are no-signal, not perfect --


def test_reducer_excludes_no_signal_trials_from_mean(minimal_pack_with_probe):
    # an epoch whose non-required checks ALL came back unsure carries no score
    # signal — it counts as an unsure trial and is EXCLUDED from mean_score
    pack = minimal_pack_with_probe("p", samples=2)
    samples = [
        _FakeSample("p", 1, {"tier3": _FakeScore(
            {"checks": [_cr("rubric:x", 3, False, True, 0.5)]})}),
        _FakeSample("p", 2, {"tier3": _FakeScore(
            {"checks": [_cr("rubric:x", 3, False, None, 0.0, unsure=True)]})}),
    ]
    [pr] = _reduce_log_to_probes(_FakeLog(samples), pack)
    assert pr.trials == 2
    assert pr.unsure_trials == 1
    assert pr.mean_score == 0.5  # NOT (0.5 + 1.0)/2 — unsure is never a 1.0


def test_reducer_all_no_signal_trials_is_fail_closed_zero_mean(minimal_pack_with_probe):
    pack = minimal_pack_with_probe("p", samples=1)
    sample = _FakeSample("p", 1, {"tier3": _FakeScore(
        {"checks": [_cr("rubric:x", 3, False, None, 0.0, unsure=True)]})})
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.trials == 1 and pr.unsure_trials == 1
    assert pr.mean_score == 0.0  # no usable signal must never read as perfect


# --- PR #4 fix #2: a sample error must not abort the whole eval ---------------

_ERRPACK_TARGET_YAML = """\
name: errpack
sessions:
  open:    { method: POST, path: /session }
  message: { method: POST, path: /chat, stream: sse, event_format: vercel-ai }
auth: { kind: none }
budget: { max_turns_per_session: 1 }
env:
  base_url: ${EVALYN_TARGET_URL:-http://127.0.0.1:8899}
allowlist:
  - http://127.0.0.1:8899
  - http://localhost:8899
"""

# `doomed` has 2 turns > max_turns_per_session=1 — the solver raises before any
# HTTP, so its sample ERRORS while `healthy` still runs and scores.
_ERRPACK_PROBES = """\
- id: healthy
  category: misc
  turns: ["Where did you work?"]
  checks:
    - { type: contains, value: "Acme", required: true }
- id: doomed
  category: misc
  turns: ["hi", "hi again"]
  checks:
    - { type: contains, value: "x", required: true }
"""


def test_errored_probe_is_missing_gate_fail_not_run_abort(toy_target, monkeypatch,
                                                          tmp_path):
    """One probe's sample error must NOT abort the eval: the artifact is still
    written, the errored probe hard-fails as MISSING (trials == 0), and the
    healthy probe is still scored."""
    from evalyn.engine.gate import evaluate_gate

    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack_dir = tmp_path / "errpack"
    (pack_dir / "probes").mkdir(parents=True)
    (pack_dir / "target.yaml").write_text(_ERRPACK_TARGET_YAML)
    (pack_dir / "probes" / "p.yaml").write_text(_ERRPACK_PROBES)
    out = tmp_path / "runs"
    art = run_gate(load_pack(pack_dir), judge_model="mockllm/model",
                   log_dir=str(tmp_path / "logs"), out_dir=str(out))
    assert list(out.glob("*.json")), "artifact must be written despite the error"
    by_id = {p.id: p for p in art.probes}
    assert by_id["doomed"].trials == 0        # errored -> no scored trials
    assert by_id["healthy"].trials == 1       # the healthy probe still scored
    assert by_id["healthy"].pass_k == 1.0
    res = evaluate_gate(art, baseline=None)
    assert res.exit_code == 1                 # MISSING is a hard gate failure
    assert any("doomed" in f and "MISSING" in f for f in res.failures)
    assert not any("healthy" in f for f in res.failures)


# --- PR #4 fix #11: artifact filename collisions + unsanitized pack name ------


def test_artifact_filenames_do_not_collide_back_to_back(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(str(REPO_EXAMPLE))
    monkeypatch.setattr("evalyn.engine.run.inspect_eval",
                        lambda *a, **k: [_fake_success_log()])
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda: 0.0)
    out = tmp_path / "runs"
    for _ in range(2):  # same second: a coarse timestamp would os.replace-clobber
        run_gate(pack, judge_model="mockllm/model",
                 log_dir=str(tmp_path / "logs"), out_dir=str(out))
    assert len(list(out.glob("*.json"))) == 2


def test_artifact_filename_sanitizes_hostile_pack_name(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(str(REPO_EXAMPLE))
    pack.spec.name = "../evil/pack name"   # must not escape out_dir or crash
    monkeypatch.setattr("evalyn.engine.run.inspect_eval",
                        lambda *a, **k: [_fake_success_log()])
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda: 0.0)
    out = tmp_path / "runs"
    run_gate(pack, judge_model="mockllm/model",
             log_dir=str(tmp_path / "logs"), out_dir=str(out))
    [written] = list(out.iterdir())
    assert written.parent == out
    assert written.suffix == ".json"
    assert "/" not in written.name and ".." not in written.name
    assert not (tmp_path / "evil").exists()


def test_run_gate_explicit_cache_dir_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(str(REPO_EXAMPLE))
    captured = {}

    def fake_build_task(pack_arg, **kwargs):
        captured.update(kwargs)
        return "task"

    monkeypatch.setattr("evalyn.engine.run.build_task", fake_build_task)
    monkeypatch.setattr("evalyn.engine.run.inspect_eval",
                        lambda *a, **k: [_fake_success_log()])
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda: 0.0)
    custom = tmp_path / "custom-cache"
    run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"),
             out_dir=str(tmp_path / "out"), cache_dir=custom)
    assert captured["cache_dir"] == custom
