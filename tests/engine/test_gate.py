from evalyn.engine.baseline import load_baseline, save_baseline
from evalyn.engine.gate import evaluate_gate
from evalyn.engine.run import ProbeResult, RunArtifact


def _art(probes):
    return RunArtifact("example", "hash", "mockllm/model", "now", probes, "log")


def test_safety_probe_fails_when_pass_k_below_one():
    # flaky injection: pass^k = 0.5 on tier1 -> must FAIL
    p = ProbeResult("inj", "injection", "regression", True, 3,
                    {"pass_k_3": {"tier1": 0.5, "tier2": 1.0}, "pass_at_3": {"tier1": 1.0},
                     "mean": {"tier1": 0.67}})
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("inj" in f for f in res.failures)


def test_safety_probe_passes_when_pass_k_is_one():
    p = ProbeResult("inj", "injection", "regression", True, 3,
                    {"pass_k_3": {"tier1": 1.0, "tier2": 1.0}, "mean": {"tier1": 1.0}})
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0


def test_capability_probe_never_fails_build():
    p = ProbeResult("cap", "grounding", "capability", False, 1,
                    {"pass_k_1": {"tier1": 0.0}, "mean": {"tier1": 0.0}})
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0


def test_capability_probe_with_empty_reducers_never_fails_build():
    # locked semantic: capability probes NEVER red the build — even when the
    # probe has no scores at all (which is a hard failure for any other kind)
    p = ProbeResult("cap", "grounding", "capability", False, 1, {})
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0
    assert not any("cap" in f for f in res.failures)
    assert "## Capability probes (not gating)" in res.report_md
    assert "`cap`" in res.report_md


def test_capability_probe_all_errored_is_surfaced_but_not_red():
    # observability only: an all-errored capability probe must say so in the
    # report instead of rendering pass^k=None — verdict stays green (pinned)
    p = ProbeResult("cap", "grounding", "capability", False, 1, {})
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0
    assert "no scored trials — all trials errored or unscored" in res.report_md
    assert "pass^k=None" not in res.report_md


def test_regression_mean_drop_beyond_band_fails():
    base = _art([ProbeResult("g", "grounding", "regression", False, 1,
                             {"mean": {"tier1": 1.0}})])
    cur = _art([ProbeResult("g", "grounding", "regression", False, 1,
                            {"mean": {"tier1": 0.5}})])
    res = evaluate_gate(cur, baseline=base, band=0.1)
    assert res.exit_code == 1
    assert any("`g`" in f for f in res.failures)


def test_regression_small_drop_is_quarantined_not_failed():
    base = _art([ProbeResult("g", "grounding", "regression", False, 1,
                             {"mean": {"tier1": 1.0}})])
    cur = _art([ProbeResult("g", "grounding", "regression", False, 1,
                            {"mean": {"tier1": 0.95}})])
    res = evaluate_gate(cur, baseline=base, band=0.1)
    assert res.exit_code == 0
    assert any("`g`" in q for q in res.quarantined)


def test_regression_no_baseline_imperfect_mean_is_quarantined():
    cur = _art([ProbeResult("g", "grounding", "regression", False, 1,
                            {"mean": {"tier1": 0.5}})])
    res = evaluate_gate(cur, baseline=None)
    assert res.exit_code == 0
    assert any("`g`" in q for q in res.quarantined)


# --- carry-note 1: empty reducers (probe absent from log) is a HARD FAILURE ---

def test_empty_reducers_on_regression_probe_is_hard_failure():
    p = ProbeResult("gone", "grounding", "regression", False, 3, {})
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("gone" in f for f in res.failures)


def test_empty_reducers_on_safety_probe_is_hard_failure():
    p = ProbeResult("inj", "injection", "regression", True, 3, {})
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("inj" in f for f in res.failures)


# --- carry-note 2 (A1): reducer keys are labeled by ACTUAL trials, not declared samples ---

def test_safety_gate_uses_actual_trial_pass_k_key_not_declared_samples():
    # declared samples=1 but the run actually collected 3 trials -> key is pass_k_3
    p = ProbeResult("inj", "injection", "regression", True, 1,
                    {"pass_k_3": {"tier1": 0.0}, "mean": {"tier1": 0.33}})
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("inj" in f for f in res.failures)

    ok = ProbeResult("inj", "injection", "regression", True, 1,
                     {"pass_k_3": {"tier1": 1.0}, "mean": {"tier1": 1.0}})
    assert evaluate_gate(_art([ok]), baseline=None).exit_code == 0


def test_report_md_marks_pass_and_fail():
    good = ProbeResult("ok", "grounding", "regression", False, 1,
                       {"mean": {"tier1": 1.0}})
    res = evaluate_gate(_art([good]), baseline=None)
    assert "PASS" in res.report_md

    bad = ProbeResult("inj", "injection", "regression", True, 3,
                      {"pass_k_3": {"tier1": 0.0}})
    res = evaluate_gate(_art([bad]), baseline=None)
    assert "FAIL" in res.report_md
    assert "inj" in res.report_md


# --- baseline persistence ---

def test_baseline_round_trip(tmp_path):
    art = _art([ProbeResult("g", "grounding", "regression", False, 1,
                            {"mean": {"tier1": 1.0}})])
    path = str(tmp_path / "runs" / "baseline.json")
    save_baseline(art, path)
    loaded = load_baseline(path)
    assert loaded is not None
    assert loaded.pack_name == "example"
    assert loaded.probes[0].id == "g"
    assert loaded.probes[0].reducers == {"mean": {"tier1": 1.0}}


def test_load_baseline_missing_returns_none(tmp_path):
    assert load_baseline(str(tmp_path / "nope.json")) is None
