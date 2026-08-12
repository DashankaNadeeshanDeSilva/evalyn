import inspect
import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from evalyn.engine.budget import PRICES as budget_prices
from evalyn.engine.run import (ProbeResult, RunArtifact, _judge_usd,
                               _reduce_log_to_probes, atomic_write_artifact,
                               new_run_id, pack_fingerprint, run_gate)
from evalyn.targets.loader import load_pack

EXAMPLE = "packs/example"
REPO_EXAMPLE = Path(__file__).resolve().parent.parent.parent / "packs" / "example"


# --- fake-log helpers for the reducer (no Inspect run needed) ---

class _FakeScore:
    def __init__(self, metadata):
        self.value = None  # the reducer's authority is metadata checks, never value
        self.metadata = metadata


class _FakeSample:
    def __init__(self, pid, epoch, scores, messages=None, store=None):
        self.id = pid
        self.epoch = epoch
        self.metadata = {"id": pid}
        self.scores = scores
        self.messages = messages or []
        self.store = store or {}


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


# --- Task 22: per-trial checks, and a representative that agrees with the verdict ---

#: The five fields the gate reads. Task 22 is presentation-only, so every one of
#: these literals is the value the PRE-Task-22 reducer produced on the same
#: input — recorded here so a later "improvement" to the check plumbing that
#: moves a verdict fails loudly instead of silently re-scoring the corpus.
_VERDICT_FIELDS = ("trials", "pass_at_k", "pass_k", "mean_score", "unsure_trials")


def _epoch_samples(pattern):
    """One single-scorer `_FakeSample` per epoch. `pattern` maps epoch -> the
    required check's `passed`; `None` means it came back unsure."""
    return [_FakeSample("p", epoch, {"tier1": _FakeScore({"checks": [
        _cr("contains:x", 1, True, passed, 1.0 if passed else 0.0,
            unsure=passed is None)]})})
        for epoch, passed in sorted(pattern.items())]


def test_each_trial_record_carries_that_epochs_own_checks(minimal_pack_with_probe):
    """Task 22: the drill-down must show THIS trial's checks.

    Discriminating by construction — epoch 2 is the only one that deviated, so
    a record handed the probe-level representative list (or epoch 1's, or an
    empty one) fails on `passed`, not merely on length.
    """
    pack = minimal_pack_with_probe("p", samples=3)
    samples = _epoch_samples({1: True, 2: False, 3: True})
    # a second scorer on epoch 2 only: the plumbing is per-epoch, not per-scorer
    samples[1].scores["tier3"] = _FakeScore(
        {"checks": [_cr("rubric:tone", 3, False, True, 0.5)]})
    [pr] = _reduce_log_to_probes(_FakeLog(samples), pack)

    by_epoch = {rec["epoch"]: rec["checks"] for rec in pr.trial_records}
    assert sorted(by_epoch) == [1, 2, 3]
    assert [c["passed"] for c in by_epoch[1]] == [True]
    assert [c["passed"] for c in by_epoch[3]] == [True]
    assert [(c["check"], c["passed"]) for c in by_epoch[2]] == [
        ("contains:x", False), ("rubric:tone", True)]
    # the artifact's own check-dict shape, unchanged
    assert all(set(c) == {"check", "tier", "required", "weight", "passed",
                          "score", "turn", "evidence", "unsure"}
               for checks in by_epoch.values() for c in checks)


def test_a_trial_records_checks_are_isolated_from_the_representative_list(
        minimal_pack_with_probe):
    """A redactor that rewrites the drill-down must not silently rewrite the
    report as well. They serialise the same; they must not BE the same.

    The in-place mutation is the whole test: a shallow `list(crs)` separates
    the two *lists* and passes an `is not` assertion while leaving every check
    **dict** shared, so the write below still lands in both.
    """
    pack = minimal_pack_with_probe("p", samples=1)
    [pr] = _reduce_log_to_probes(_FakeLog(_epoch_samples({1: False})), pack)
    record_checks = pr.trial_records[0]["checks"]

    assert pr.checks == record_checks
    assert pr.checks is not record_checks
    pr.checks[0]["evidence"] = "[redacted]"
    assert record_checks[0]["evidence"] == "", (
        "the trial record was rewritten through the representative list")


@pytest.mark.parametrize("pattern, expected", [
    ({1: True, 2: True, 3: True}, (3, 1.0, 1.0, 1.0, 0)),
    ({1: True, 2: False, 3: True}, (3, 1.0, 0.0, 2 / 3, 0)),
    ({1: False, 2: False, 3: False}, (3, 0.0, 0.0, 0.0, 0)),
    # the unsure trial counts toward `trials`/`unsure_trials` but is EXCLUDED
    # from the mean (PR #4 fix #1), so that is (1.0 + 0.0) / 2, not / 3
    ({1: True, 2: None, 3: False}, (3, 1.0, 0.0, 0.5, 1)),
    ({1: False, 2: True}, (2, 1.0, 0.0, 0.5, 0)),
])
def test_task_22_moves_no_verdict_field(minimal_pack_with_probe, pattern, expected):
    """**PRESENTATION ONLY.** `pass_k`/`pass_at_k`/`mean_score`/`unsure_trials`
    come from the `req_passes` aggregation, never from `checks` or
    `trial_records`. These are the pre-Task-22 values on the same inputs."""
    pack = minimal_pack_with_probe("p", samples=max(pattern))
    [pr] = _reduce_log_to_probes(_FakeLog(_epoch_samples(pattern)), pack)

    assert tuple(getattr(pr, f) for f in _VERDICT_FIELDS) == pytest.approx(expected)


def test_a_failing_trial_represents_a_failing_probe(minimal_pack_with_probe):
    """Task 22 commit 2: the representative list may not contradict pass^k.

    Epoch 1 passes and epoch 3 deviates, which is exactly the shape that made
    `injection-exfil-boundaries` render `pass^k=0.0  7 checks  0 failed` on
    stage: the representative was always the first epoch's all-green list.
    """
    pack = minimal_pack_with_probe("p", samples=3)
    [pr] = _reduce_log_to_probes(
        _FakeLog(_epoch_samples({1: True, 2: True, 3: False})), pack)

    assert pr.pass_k == 0.0, "the probe failed"
    assert any(c["passed"] is False for c in pr.checks), (
        "so its representative checks must show a failure")
    assert pr.checks == pr.trial_records[-1]["checks"]  # epoch 3's, the failing one


def test_an_all_passing_probe_keeps_the_lowest_epoch_as_representative(
        minimal_pack_with_probe):
    """The fallback: no failing epoch to pick, so the lowest-numbered one."""
    pack = minimal_pack_with_probe("p", samples=2)
    [pr] = _reduce_log_to_probes(_FakeLog(_epoch_samples({1: True, 2: True})), pack)

    assert pr.pass_k == 1.0
    assert pr.checks == pr.trial_records[0]["checks"]


def test_an_abstaining_epoch_never_represents_a_probe_that_really_failed(
        minimal_pack_with_probe):
    """**Fix round I1.** `not req_pass` is true for an ABSTAINED required
    check as well as a failed one, so selecting on it picked epoch 1 here —
    an epoch with no `passed: false` in it — and printed `pass^k=0.0 … 0
    failed` on stage all over again, with the real deviation on epoch 3 left
    unshown.

    Not hypothetical for the demo: `packs/twincore-injection/probes/
    injection.yaml:257` is a `type: classifier, required: true` check, i.e. a
    tier-2 judge call, and abstaining is exactly what a judge call does when
    it cannot decide.
    """
    pack = minimal_pack_with_probe("p", samples=3)
    [pr] = _reduce_log_to_probes(
        _FakeLog(_epoch_samples({1: None, 2: True, 3: False})), pack)

    assert pr.pass_k == 0.0 and pr.unsure_trials == 1
    assert not any(c["passed"] is False for c in pr.trial_records[0]["checks"]), (
        "epoch 1 must be the abstainer this test is about")
    assert any(c["passed"] is False for c in pr.checks), (
        "the abstaining epoch was chosen over the one that really failed")
    assert pr.checks == pr.trial_records[-1]["checks"]  # epoch 3's


def test_an_all_abstaining_probe_is_represented_by_its_abstention(
        minimal_pack_with_probe):
    """No epoch shows a `passed: false`, so there is no failure to show and
    inventing one would be worse. The lowest failing epoch's `unsure` entries
    are the honest evidence — and they are what the badge renders."""
    pack = minimal_pack_with_probe("p", samples=2)
    [pr] = _reduce_log_to_probes(
        _FakeLog(_epoch_samples({1: True, 2: None})), pack)

    assert pr.pass_k == 0.0 and pr.unsure_trials == 1
    assert pr.checks == pr.trial_records[1]["checks"]   # epoch 2, the abstainer
    assert [c["unsure"] for c in pr.checks] == [True]


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
                                                               tmp_path, live_pack_dir):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(live_pack_dir(REPO_EXAMPLE))
    # mockllm/model is priced at zero (free local stub), which would make the
    # judge_usd guard below vacuous — a real 0.0 and the ContextVar-seam bug's
    # 0.0 are indistinguishable. Price the stub nonzero FOR THIS TEST ONLY so
    # judge_usd > 0.0 still proves the eval's own usage reaches _judge_usd.
    monkeypatch.setitem(budget_prices, "mockllm", (0.015, 0.075))
    art = run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"),
                   out_dir=str(tmp_path / "runs"))  # keep runs/ out of the repo CWD
    # Plan #2b Task 1 regression guard: a REAL run must meter nonzero judge
    # spend from the returned log (live bug 2026-07-28: judge_usd == 0.0)
    assert art.judge_usd > 0.0
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
                                                        tmp_path, live_pack_dir):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(live_pack_dir(REPO_EXAMPLE))
    monkeypatch.chdir(tmp_path)  # a CWD runs/ write would be visible here
    # metering is not this test's concern (and unpriced mockllm would warn)
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.0)
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
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.0)
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
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.0)
    with pytest.raises(RuntimeError, match="no probe collected"):  # empty log (N6)
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

def _errpack_target_yaml(base_url: str) -> str:
    """The pack text, built around the live target's URL (its port is dynamic).

    `base_url` is the 127.0.0.1 spelling the `toy_target` fixture yields; the
    allowlist keeps a `localhost` entry too, as the shipped packs do.
    """
    return f"""\
name: errpack
sessions:
  open:    {{ method: POST, path: /session }}
  message: {{ method: POST, path: /chat, stream: sse, event_format: vercel-ai }}
auth: {{ kind: none }}
budget: {{ max_turns_per_session: 1 }}
env:
  base_url: ${{EVALYN_TARGET_URL:-{base_url}}}
allowlist:
  - {base_url}
  - {base_url.replace("127.0.0.1", "localhost")}
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
    (pack_dir / "target.yaml").write_text(_errpack_target_yaml(toy_target))
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
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.0)
    out = tmp_path / "runs"
    for _ in range(2):  # same second: a coarse timestamp would os.replace-clobber
        with pytest.raises(RuntimeError, match="no probe collected"):  # empty log (N6)
            run_gate(pack, judge_model="mockllm/model",
                     log_dir=str(tmp_path / "logs"), out_dir=str(out))
    assert len(list(out.glob("*.json"))) == 2


def test_artifact_filename_sanitizes_hostile_pack_name(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(str(REPO_EXAMPLE))
    pack.spec.name = "../evil/pack name"   # must not escape out_dir or crash
    monkeypatch.setattr("evalyn.engine.run.inspect_eval",
                        lambda *a, **k: [_fake_success_log()])
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.0)
    out = tmp_path / "runs"
    with pytest.raises(RuntimeError, match="no probe collected"):  # empty log (N6)
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
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.0)
    custom = tmp_path / "custom-cache"
    with pytest.raises(RuntimeError, match="no probe collected"):  # empty log (N6)
        run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"),
                 out_dir=str(tmp_path / "out"), cache_dir=custom)
    assert captured["cache_dir"] == custom


# --- round-2 N1: errored epochs must not shrink the pass^k denominator -------


def test_reducer_records_expected_trials_from_pack_wide_epochs(minimal_pack_with_probe):
    # the task runs every probe at the pack-wide max(samples) = k; the reducer
    # must record that expectation so the gate can spot incomplete probes
    pack = minimal_pack_with_probe("p", samples=3)
    # only ONE of the 3 epochs produced checks (2 errored)
    sample = _FakeSample("p", 1, {"tier1": _FakeScore(
        {"checks": [_cr("inv", 1, True, True, 1.0)]})})
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.trials == 1
    assert pr.expected_trials == 3
    assert pr.pass_k == 1.0  # over the SCORED trials only — the gate must
    #                          refuse to trust this via expected_trials


def test_artifact_roundtrip_preserves_expected_trials(minimal_pack_with_probe):
    art = RunArtifact(
        pack_name="p", pack_hash="h", judge_model="j", created_at="now",
        probes=[ProbeResult("p", "c", "regression", False, 3, trials=1,
                            expected_trials=3)],
        log_path="log")
    loaded = RunArtifact.from_dict(art.to_dict())
    assert loaded == art
    assert loaded.probes[0].expected_trials == 3


def test_artifact_without_expected_trials_still_loads_as_unknown():
    # backward read: pre-round-2 artifacts have no expected_trials — they must
    # load with the documented fallback 0 ("unknown": the gate skips the
    # incompleteness check and only trials == 0 fails as MISSING)
    art = RunArtifact(
        pack_name="p", pack_hash="h", judge_model="j", created_at="now",
        probes=[ProbeResult("p", "c", "regression", False, 3, trials=3)],
        log_path="log")
    d = art.to_dict()
    for p in d["probes"]:
        del p["expected_trials"]
    loaded = RunArtifact.from_dict(d)
    assert loaded.probes[0].expected_trials == 0


# --- Task 6 (#2b): per-trial transcript + hard metrics ------------------------


def test_artifact_without_trial_records_still_loads_empty():
    # backward read: pre-#2b artifacts/baselines have no trial_records — the
    # additive default [] must apply so old baselines keep loading unchanged
    art = RunArtifact(
        pack_name="p", pack_hash="h", judge_model="j", created_at="now",
        probes=[ProbeResult("p", "c", "regression", False, 3, trials=3)],
        log_path="log")
    d = art.to_dict()
    for p in d["probes"]:
        del p["trial_records"]
    loaded = RunArtifact.from_dict(d)
    assert loaded.probes[0].trial_records == []


def test_reducer_trial_records_scored_epochs_only(minimal_pack_with_probe):
    # one record per SCORED epoch (same rule as `trials`): the errored epoch
    # gets no record; invariant_failures counts only FAILED `invariant:` checks
    pack = minimal_pack_with_probe("p", samples=2)
    msgs = [SimpleNamespace(role="user", text="hi"),
            SimpleNamespace(role="assistant", text="hello"),
            SimpleNamespace(role="system", text="never in the transcript")]
    scored = _FakeSample("p", 1, {
        "tier1": _FakeScore({"checks": [
            _cr("invariant:non-empty", 1, True, False, 0.0),
            _cr("invariant:no-pii", 1, True, True, 1.0),
            _cr("contains:x", 1, True, False, 0.0),  # non-invariant fail: not counted
        ]}),
    }, messages=msgs, store={"evalyn:session_seconds": 1.25})
    errored = _FakeSample("p", 2, {"tier1": _FakeScore(None)})
    [pr] = _reduce_log_to_probes(_FakeLog([scored, errored]), pack)
    assert pr.trials == 1
    assert pr.trial_records == [{
        "epoch": 1, "transcript": "User: hi\nAssistant: hello",
        # Task 22: the epoch's own checks, all three of them — including the
        # two that `invariant_failures` does not count.
        "checks": scored.scores["tier1"].metadata["checks"],
        "session_seconds": 1.25, "invariant_failures": 1}]


def test_reducer_trial_records_sorted_by_epoch_missing_seconds_is_none(
        minimal_pack_with_probe):
    # records come sorted by epoch regardless of log order; a sample whose
    # store carries no session timing yields session_seconds None, not a fake 0
    pack = minimal_pack_with_probe("p", samples=2)
    ck = {"tier1": _FakeScore({"checks": [_cr("invariant:i", 1, True, True, 1.0)]})}
    later = _FakeSample("p", 2, ck,
                        messages=[SimpleNamespace(role="user", text="u2"),
                                  SimpleNamespace(role="assistant", text="a2")])
    first = _FakeSample("p", 1, ck,
                        messages=[SimpleNamespace(role="user", text="u1"),
                                  SimpleNamespace(role="assistant", text="a1")],
                        store={"evalyn:session_seconds": 0.5})
    [pr] = _reduce_log_to_probes(_FakeLog([later, first]), pack)
    assert [r["epoch"] for r in pr.trial_records] == [1, 2]
    assert pr.trial_records[0]["session_seconds"] == 0.5
    assert pr.trial_records[1]["session_seconds"] is None


# --- round-2 N3: required-unsure trials carry no score signal ----------------


def test_reducer_excludes_required_unsure_trials_from_mean(minimal_pack_with_probe):
    # repro: trial 1 scores 0.5; trial 2's REQUIRED check is unsure — it must
    # be excluded from the mean (not averaged in via the non-required mean)
    pack = minimal_pack_with_probe("p", samples=2)
    samples = [
        _FakeSample("p", 1, {
            "tier2": _FakeScore({"checks": [_cr("classifier:0", 2, True, True, 1.0)]}),
            "tier3": _FakeScore({"checks": [_cr("rubric:x", 3, False, True, 0.5)]})}),
        _FakeSample("p", 2, {
            "tier2": _FakeScore({"checks": [_cr("classifier:0", 2, True, None, 0.0,
                                                unsure=True)]}),
            "tier3": _FakeScore({"checks": [_cr("rubric:x", 3, False, True, 1.0)]})}),
    ]
    [pr] = _reduce_log_to_probes(_FakeLog(samples), pack)
    assert pr.trials == 2 and pr.unsure_trials == 1
    assert pr.mean_score == 0.5  # NOT (0.5 + 1.0)/2 — the unsure trial is no-signal


def test_reducer_all_required_unsure_trials_is_zero_mean_fail_closed(minimal_pack_with_probe):
    # all trials required-unsure -> mean 0.0 so a baseline regression FIRES
    # (previously the non-required mean turned a judge outage green)
    from evalyn.engine.gate import evaluate_gate

    pack = minimal_pack_with_probe("p", samples=1)
    sample = _FakeSample("p", 1, {
        "tier2": _FakeScore({"checks": [_cr("classifier:0", 2, True, None, 0.0,
                                            unsure=True)]}),
        "tier3": _FakeScore({"checks": [_cr("rubric:x", 3, False, True, 1.0)]})})
    [pr] = _reduce_log_to_probes(_FakeLog([sample]), pack)
    assert pr.mean_score == 0.0 and pr.unsure_trials == 1
    art = RunArtifact("p", "h", "j", "now", [pr], "log")
    base = RunArtifact("p", "h", "j", "now", [ProbeResult(
        "p", "misc", "regression", False, 1, trials=1, expected_trials=1,
        pass_at_k=1.0, pass_k=1.0, mean_score=1.0)], "log")
    res = evaluate_gate(art, base, band=0.1)
    assert res.exit_code == 1
    assert any("REGRESSION" in f for f in res.failures)


# --- round-2 N6: a fully-dead target is a setup error, not a gate FAIL -------


def test_run_gate_raises_when_no_probe_scored_a_single_trial(monkeypatch, tmp_path):
    # log.status is "success" (fail_on_error=False swallows per-sample errors)
    # but NO probe collected a scored trial: the target is dead — run_gate must
    # raise (CLI maps it to exit 2), never hand the gate an all-MISSING artifact
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(str(REPO_EXAMPLE))
    monkeypatch.setattr("evalyn.engine.run.inspect_eval",
                        lambda *a, **k: [_fake_success_log()])
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.0)
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="no probe collected"):
        run_gate(pack, judge_model="mockllm/model",
                 log_dir=str(tmp_path / "logs"), out_dir=str(out))
    # house pattern: the artifact is written BEFORE the raise, for inspection
    assert list(out.glob("*.json")), "artifact must survive the setup-error raise"


# --- Plan #2b Task 1: judge_usd is metered from the RETURNED eval log --------


def _fake_log(usage: dict):
    return SimpleNamespace(stats=SimpleNamespace(model_usage=usage))


def test_judge_usd_reads_log_stats():
    usage = {"anthropic/claude-sonnet-5": SimpleNamespace(input_tokens=88_035,
                                                          output_tokens=27_037)}
    got = _judge_usd(_fake_log(usage))
    # sonnet-5 PRICES: (0.003, 0.015) per 1k
    assert got == pytest.approx(88.035 * 0.003 + 27.037 * 0.015)


def test_judge_usd_is_per_log_isolated():
    # two different logs meter independently — no shared/global accumulator
    with pytest.warns(RuntimeWarning, match="no price entry"):  # "m" is unpriced
        a = _judge_usd(_fake_log({"m": SimpleNamespace(input_tokens=1000, output_tokens=0)}))
    b = _judge_usd(_fake_log({}))
    assert a > 0.0 and b == 0.0


def test_judge_usd_fail_open_is_loud():
    with pytest.warns(RuntimeWarning, match="budget cap not enforced"):
        assert _judge_usd(SimpleNamespace()) == 0.0  # no .stats -> warn + 0.0


# --- Plan #4 Task 2: run_id correlation -------------------------------------

#: The artifact filename format as it stands TODAY, spelled out here on purpose.
#: This is the regression guard for the whole task: every existing caller writes
#: through `run_id=None`, and if that path drifts by so much as a digit the
#: terminal `gate`/`compare`/`discover` flows — and 80 artifacts already on disk
#: — stop correlating. It is deliberately NOT imported from the code under test.
_MINTED_RE = re.compile(r"^\d{8}T\d{6}\d{6}-[0-9a-f]{8}-.+\.json$")


def test_default_minted_artifact_name_format_is_unchanged(tmp_path):
    """`run_id=None` mints EXACTLY as before — stamp+micros, uuid8, slug."""
    out = tmp_path / "runs"
    path = atomic_write_artifact({"a": 1}, "example", str(out), suffix="")
    assert _MINTED_RE.match(path.name), path.name
    stamp, uuid8, slug = path.stem.split("-", 2)
    assert len(stamp) == 21 and stamp[8] == "T"      # 8 date + T + 6 time + 6 micros
    assert len(uuid8) == 8 and int(uuid8, 16) >= 0   # lowercase hex, 8 chars
    assert slug == "example"
    assert json.loads(path.read_text()) == {"a": 1}
    assert not list(out.glob("*.tmp")), "temp file must be renamed away"


def test_default_minted_name_is_a_valid_run_id_plus_suffix(tmp_path):
    """The default path and the frozen `RunId` grammar must already agree."""
    from evalyn.ui.models import is_run_id
    for suffix in ("", "-compare", "-discover"):
        path = atomic_write_artifact({}, "example", str(tmp_path), suffix=suffix)
        assert is_run_id(path.stem)


def test_new_run_id_mints_the_same_format_as_the_default_path(tmp_path):
    """The extracted minter is the SAME minter — not a second one that drifts."""
    from evalyn.ui.models import is_run_id
    minted = new_run_id("example")
    assert is_run_id(minted)
    assert _MINTED_RE.match(minted + ".json"), minted
    default = atomic_write_artifact({}, "example", str(tmp_path), suffix="").stem
    # same shape, field for field (values differ: stamp + uuid are fresh)
    a, b = minted.split("-"), default.split("-")
    assert [len(x) for x in a] == [len(x) for x in b]


def test_new_run_id_is_collision_proof_and_slugifies_a_hostile_pack_name():
    ids = {new_run_id("example") for _ in range(5)}
    assert len(ids) == 5                       # uuid8 + microseconds
    hostile = new_run_id("../evil/pack name")
    assert "/" not in hostile and ".." not in hostile.split("-", 2)[2]
    assert new_run_id("...").endswith("-pack")  # empty slug falls back


def test_atomic_write_artifact_uses_an_explicit_run_id_verbatim(tmp_path):
    out = tmp_path / "runs"
    path = atomic_write_artifact({"a": 1}, "ignored-pack-name", str(out), suffix="",
                                 run_id="20260807T101112000000-deadbeef-example")
    assert path.name == "20260807T101112000000-deadbeef-example.json"
    assert path == out / "20260807T101112000000-deadbeef-example.json"
    assert json.loads(path.read_text()) == {"a": 1}


def test_explicit_run_id_still_carries_the_mode_suffix(tmp_path):
    """`runs/<run_id><suffix>.json` — the server derives the path it will read."""
    for suffix in ("-compare", "-discover"):
        path = atomic_write_artifact({}, "p", str(tmp_path), suffix=suffix,
                                     run_id="20260807T101112000000-deadbeef-example")
        assert path.name == f"20260807T101112000000-deadbeef-example{suffix}.json"


def test_run_id_is_keyword_only_and_defaults_to_none():
    sig = inspect.signature(atomic_write_artifact)
    p = sig.parameters["run_id"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is None
    # the pre-existing parameters keep their order and meaning
    assert [n for n, q in sig.parameters.items()
            if q.kind is not inspect.Parameter.KEYWORD_ONLY] == [
        "payload", "pack_name", "out_dir", "suffix"]


@pytest.mark.parametrize("hostile", [
    "../../etc/passwd", "..", "/abs/path", "baseline",
    "20260807T101112000000-deadbeef-example.json",   # a filename, not an id
    "20260807T101112000000-deadbeef-example\n",
])
def test_atomic_write_artifact_refuses_a_run_id_that_is_not_one(tmp_path, hostile):
    with pytest.raises(ValueError, match="run_id"):
        atomic_write_artifact({}, "p", str(tmp_path), suffix="", run_id=hostile)
    assert not list(tmp_path.rglob("*")), "a refused write must leave nothing behind"


def test_atomic_write_artifact_never_reads_the_environment():
    """Env is how the SUBPROCESS is told; the parameter is how it flows.

    A read here would make the writer's behaviour depend on ambient state that
    no caller passed and no test controls.
    """
    src = inspect.getsource(atomic_write_artifact)
    assert "environ" not in src
    assert "getenv" not in src


def test_run_gate_threads_run_id_to_the_artifact_name(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(str(REPO_EXAMPLE))
    monkeypatch.setattr("evalyn.engine.run.inspect_eval",
                        lambda *a, **k: [_fake_success_log()])
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.0)
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="no probe collected"):  # empty log (N6)
        run_gate(pack, judge_model="mockllm/model", log_dir=str(tmp_path / "logs"),
                 out_dir=str(out), run_id="20260807T101112000000-deadbeef-example")
    assert [p.name for p in out.glob("*.json")] == [
        "20260807T101112000000-deadbeef-example.json"]


def test_run_gate_run_id_is_keyword_only_and_optional():
    p = inspect.signature(run_gate).parameters["run_id"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is None
