import json

import pytest

from evalyn.engine.baseline import load_baseline, save_baseline
from evalyn.engine.gate import evaluate_gate
from evalyn.engine.run import ProbeResult, RunArtifact


def _art(probes, name="example"):
    return RunArtifact(name, "hash", "mockllm/model", "now", probes, "log")


def _probe(pid="p", *, category="cat", kind="regression", safety=False, samples=1,
           trials=1, pass_at_k=1.0, pass_k=1.0, mean_score=1.0, unsure_trials=0,
           checks=None):
    return ProbeResult(pid, category, kind, safety, samples, trials=trials,
                       pass_at_k=pass_at_k, pass_k=pass_k, mean_score=mean_score,
                       unsure_trials=unsure_trials, checks=checks or [])


def test_safety_probe_fails_when_pass_k_below_one():
    # flaky injection: pass^k < 1 -> must FAIL, regardless of a high mean
    p = _probe("inj", category="injection", safety=True, samples=3, trials=3,
               pass_at_k=1.0, pass_k=0.0, mean_score=0.67)
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("inj" in f and "SAFETY" in f for f in res.failures)


def test_safety_probe_passes_when_pass_k_is_one():
    p = _probe("inj", category="injection", safety=True, samples=3, trials=3,
               pass_k=1.0, mean_score=1.0)
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0


def test_safety_failure_surfaces_unsure_trial_count():
    p = _probe("inj", category="injection", safety=True, samples=3, trials=3,
               pass_k=0.0, mean_score=1.0, unsure_trials=2)
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("2 unsure" in f for f in res.failures)


def test_capability_probe_never_fails_build():
    p = _probe("cap", category="grounding", kind="capability", trials=1,
               pass_at_k=0.0, pass_k=0.0, mean_score=0.0)
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0


def test_capability_probe_with_no_trials_never_fails_build():
    # locked semantic: capability probes NEVER red the build — even when the
    # probe has no scored trials at all (a hard failure for any other kind)
    p = _probe("cap", category="grounding", kind="capability", trials=0,
               pass_k=0.0, mean_score=0.0)
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0
    assert not any("cap" in f for f in res.failures)
    assert "## Capability probes (not gating)" in res.report_md
    assert "`cap`" in res.report_md


def test_capability_probe_all_errored_is_surfaced_but_not_red():
    # observability only: an all-errored capability probe must say so in the
    # report instead of rendering pass^k=None — verdict stays green (pinned)
    p = _probe("cap", category="grounding", kind="capability", trials=0)
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0
    assert "no scored trials — all trials errored or unscored" in res.report_md
    assert "pass^k=None" not in res.report_md


def test_regression_mean_drop_beyond_band_fails():
    base = _art([_probe("g", category="grounding", mean_score=1.0)])
    cur = _art([_probe("g", category="grounding", mean_score=0.5)])
    res = evaluate_gate(cur, baseline=base, band=0.1)
    assert res.exit_code == 1
    assert any("`g`" in f for f in res.failures)


def test_regression_small_drop_is_quarantined_not_failed():
    base = _art([_probe("g", category="grounding", mean_score=1.0)])
    cur = _art([_probe("g", category="grounding", mean_score=0.95)])
    res = evaluate_gate(cur, baseline=base, band=0.1)
    assert res.exit_code == 0
    assert any("`g`" in q for q in res.quarantined)


def test_regression_no_baseline_imperfect_mean_is_quarantined():
    cur = _art([_probe("g", category="grounding", mean_score=0.5)])
    res = evaluate_gate(cur, baseline=None)
    assert res.exit_code == 0
    assert any("`g`" in q for q in res.quarantined)


# --- design-gap #2 proof: a NON-REQUIRED miss alone moves the band verdict ---

def test_nonrequired_partial_score_moves_band():
    # same probe, required checks all pass in both runs (pass_k stays 1.0); the
    # current run's mean dropped to 0.75 purely via a non-required weighted
    # miss — that partial score alone must cross the band and fail the gate
    base = _art([ProbeResult("p", "c", "regression", False, 1, trials=1,
                             pass_at_k=1.0, pass_k=1.0, mean_score=1.0)])
    cur = _art([ProbeResult("p", "c", "regression", False, 1, trials=1,
                            pass_at_k=1.0, pass_k=1.0, mean_score=0.75)])
    res = evaluate_gate(cur, base, band=0.1)
    assert res.exit_code == 1  # 1.0 - 0.75 = 0.25 > 0.1 => REGRESSION
    assert any("REGRESSION" in f for f in res.failures)


# --- carry-note 1: no trials collected (probe absent from log) is a HARD FAILURE ---

def test_no_trials_on_regression_probe_is_hard_failure():
    p = _probe("gone", category="grounding", samples=3, trials=0)
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("gone" in f and "MISSING" in f for f in res.failures)


def test_no_trials_on_safety_probe_is_hard_failure():
    p = _probe("inj", category="injection", safety=True, samples=3, trials=0)
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("inj" in f for f in res.failures)


def test_report_md_marks_pass_and_fail():
    good = _probe("ok", category="grounding", mean_score=1.0)
    res = evaluate_gate(_art([good]), baseline=None)
    assert "PASS" in res.report_md

    bad = _probe("inj", category="injection", safety=True, samples=3, trials=3,
                 pass_k=0.0)
    res = evaluate_gate(_art([bad]), baseline=None)
    assert "FAIL" in res.report_md
    assert "inj" in res.report_md


def test_report_md_prints_total_unsure_trials():
    # Task 12: NOANSWER accounting is part of the human-readable report
    art = _art([_probe("ok")])
    art.total_unsure_trials = 3
    res = evaluate_gate(art, baseline=None)
    assert "3 unsure trial(s)" in res.report_md


def test_report_md_omits_unsure_line_when_zero():
    res = evaluate_gate(_art([_probe("ok")]), baseline=None)
    assert "unsure trial" not in res.report_md


def test_report_md_banners_untrusted_rubric_scores():
    # PR #4 fix #6: --allow-uncalibrated is an informed override — rubric
    # checks still gate, but the report must carry a prominent banner
    art = _art([_probe("ok")])
    art.rubric_scores_untrusted = True
    res = evaluate_gate(art, baseline=None)
    assert "UNTRUSTED" in res.report_md
    assert "uncalibrated" in res.report_md.lower()


def test_report_md_has_no_untrusted_banner_by_default():
    res = evaluate_gate(_art([_probe("ok")]), baseline=None)
    assert "UNTRUSTED" not in res.report_md


def test_exit_code_is_exactly_the_failure_verdict():
    ok = evaluate_gate(_art([_probe("ok")]), baseline=None)
    assert ok.exit_code == 0 and not ok.failures
    bad = evaluate_gate(_art([_probe("gone", trials=0)]), baseline=None)
    assert bad.exit_code == 1 and bad.failures


# --- round-2 N1: incomplete probes (errored epochs) must not pass the gate ---

def test_incomplete_safety_probe_fails_even_when_scored_trials_pass():
    # repro: samples=3, 2 epochs errored, 1 passed -> trials=1, pass_k=1.0 over
    # a shrunken denominator. The gate must FAIL it as INCOMPLETE.
    p = _probe("inj", category="injection", safety=True, samples=3, trials=1,
               pass_at_k=1.0, pass_k=1.0, mean_score=1.0)
    p.expected_trials = 3
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("inj" in f and "INCOMPLETE" in f and "1/3" in f for f in res.failures)


def test_incomplete_default_kind_probe_fails_too():
    p = _probe("g", category="grounding", samples=3, trials=1, mean_score=1.0)
    p.expected_trials = 3
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("`g`" in f and "INCOMPLETE" in f for f in res.failures)


def test_incomplete_capability_probe_is_never_a_failure():
    # pinned kind semantics: capability probes NEVER red the build
    p = _probe("cap", category="grounding", kind="capability", samples=3, trials=1,
               pass_k=1.0, mean_score=1.0)
    p.expected_trials = 3
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0
    assert not res.failures


def test_complete_probe_with_expected_trials_is_not_incomplete():
    p = _probe("ok", category="grounding", samples=3, trials=3, mean_score=1.0)
    p.expected_trials = 3
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0


def test_unknown_expected_trials_skips_incompleteness_check():
    # documented fallback: pre-round-2 artifacts load with expected_trials=0
    # ("unknown") — only the trials == 0 MISSING rule applies to them
    p = _probe("old", category="grounding", samples=3, trials=1, mean_score=1.0)
    assert p.expected_trials == 0
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 0


def test_zero_trials_is_still_missing_not_incomplete():
    p = _probe("gone", category="grounding", samples=3, trials=0)
    p.expected_trials = 3
    res = evaluate_gate(_art([p]), baseline=None)
    assert res.exit_code == 1
    assert any("MISSING" in f for f in res.failures)
    assert not any("INCOMPLETE" in f for f in res.failures)


# --- round-2 N4c: the BASELINE side of the untrusted-rubric banner ------------

def test_report_md_banners_untrusted_baseline_distinctly():
    base = _art([_probe("g", category="grounding", mean_score=1.0)])
    base.rubric_scores_untrusted = True
    cur = _art([_probe("g", category="grounding", mean_score=1.0)])
    res = evaluate_gate(cur, baseline=base)
    assert "BASELINE" in res.report_md and "UNTRUSTED" in res.report_md
    # distinct wording: the current-side banner must NOT appear
    assert "this run bypassed" not in res.report_md


def test_report_md_no_baseline_banner_when_baseline_is_trusted():
    base = _art([_probe("g", category="grounding", mean_score=1.0)])
    cur = _art([_probe("g", category="grounding", mean_score=1.0)])
    res = evaluate_gate(cur, baseline=base)
    assert "BASELINE" not in res.report_md


def test_current_and_baseline_untrusted_banners_are_both_shown():
    base = _art([_probe("g", category="grounding", mean_score=1.0)])
    base.rubric_scores_untrusted = True
    cur = _art([_probe("g", category="grounding", mean_score=1.0)])
    cur.rubric_scores_untrusted = True
    res = evaluate_gate(cur, baseline=base)
    assert "this run bypassed" in res.report_md          # current-side banner
    assert "BASELINE" in res.report_md                   # baseline-side banner


# --- a stopped run earned no verdict (R4-115) ---

def _cancelled_pair():
    """The same probes twice, cancelled and not — so every assertion below is
    a *difference* the flag made, never a property of the fixture.

    `ran` finished and failed its safety `pass^k`; `never` was reduced to
    `trials=0` by the stop (R4-13). Both are real gate failures, so the report
    has something to be wrong about: a run this shape genuinely reads FAIL when
    nobody stopped it.
    """
    probes = [_probe("ran", category="injection", safety=True, samples=3,
                     trials=3, pass_k=0.0, mean_score=0.0),
              _probe("never", trials=0, pass_at_k=0.0, pass_k=0.0, mean_score=0.0)]
    stopped = _art(probes)
    stopped.cancelled = True
    return evaluate_gate(stopped, baseline=None), evaluate_gate(_art(probes),
                                                                baseline=None)


def test_a_stopped_run_reports_no_verdict_rather_than_fail():
    stopped, finished = _cancelled_pair()
    assert "**FAIL**" in finished.report_md               # the control
    assert "**NO VERDICT**" in stopped.report_md
    assert "**FAIL**" not in stopped.report_md
    assert "stopped before it finished" in stopped.report_md


def test_a_stopped_run_does_not_blame_its_un_run_probes_on_errors():
    """The false parenthetical: `never` has no scores because the operator
    stopped the run, which the artifact records — not because its trials
    errored, which nothing recorded and the report was guessing."""
    stopped, finished = _cancelled_pair()
    assert "all trials errored?" in finished.report_md    # the control
    assert "all trials errored?" not in stopped.report_md
    assert "the run was stopped before this probe ran" in stopped.report_md


def test_a_stopped_run_still_exits_non_zero():
    """Scoped deliberately. The *report* stops claiming a decided verdict; the
    exit code does not become 0, because a run that was stopped part-way has
    not passed and saying so would be the worse lie."""
    stopped, finished = _cancelled_pair()
    assert stopped.exit_code == 1 and finished.exit_code == 1
    assert len(stopped.failures) == len(finished.failures) == 2


# --- an unmeasured 0.00 is not a measured one ---

def test_a_probe_nobody_could_score_says_so_instead_of_reporting_a_zero():
    """The pair is the whole test. Both probes report `mean 0.00` and both are
    quarantined with no baseline; only one of them was actually measured.

    `scored` failed every trial on its merits — a product regression to chase.
    `unscored` has `trials == unsure_trials`, so every trial was excluded from
    the mean and the 0.00 is `run.py:305`'s fallback — a judge that did not
    answer, which is a completely different thing to do next about.
    """
    scored = _probe("scored", trials=3, mean_score=0.0)
    unscored = _probe("unscored", trials=3, unsure_trials=3, mean_score=0.0)
    res = evaluate_gate(_art([scored, unscored]), baseline=None)

    (measured,) = [q for q in res.quarantined if "scored`" in q and "unscored" not in q]
    (absent,) = [q for q in res.quarantined if "unscored`" in q]
    assert "NO USABLE SCORE" not in measured
    assert "NO USABLE SCORE" in absent
    assert "all 3 trials unsure" in absent


def test_the_note_reaches_a_regression_line_too():
    """The most misleading place it can appear: against a baseline, a probe
    nobody could score is reported as a REGRESSION — a judge outage wearing a
    product regression's name."""
    base = _art([_probe("g", mean_score=1.0)])
    cur = _art([_probe("g", trials=3, unsure_trials=3, mean_score=0.0)])
    (failure,) = evaluate_gate(cur, baseline=base).failures
    assert failure.startswith("REGRESSION")
    assert "NO USABLE SCORE" in failure


def test_a_safety_probe_that_passes_on_an_unmeasured_mean_is_quarantined():
    """The shape actually on disk — 7 artifacts in `runs/` carry it.

    A safety probe gates on `pass^k` over its REQUIRED checks, and an unsure
    required check already forces `pass^k` to 0, so 1.0 here is a genuine pass.
    But every trial was unsure on the non-required checks, so the `mean 0.00`
    printed beside it measured nothing — and before this, the report said
    neither thing: the safety branch returned early and the probe passed in
    silence.

    Quarantined, not failed. Whether an unmeasurable probe should red the build
    is a product decision this does not take; making it visible is not.
    """
    p = _probe("inj", category="injection", safety=True, samples=3, trials=3,
               pass_k=1.0, unsure_trials=3, mean_score=0.0)
    res = evaluate_gate(_art([p]), baseline=None)

    assert res.exit_code == 0, "a real pass must stay a pass"
    assert res.failures == []
    (q,) = res.quarantined
    assert "pass^k=1.0 stands" in q and "not a measurement" in q


def test_a_safety_probe_with_a_real_mean_is_not_quarantined():
    """The control. Same probe, same pass, trials that actually scored — this
    must stay off the quarantine list entirely, or the check above is just
    'quarantine every passing safety probe'."""
    p = _probe("inj", category="injection", safety=True, samples=3, trials=3,
               pass_k=1.0, unsure_trials=0, mean_score=1.0)
    assert evaluate_gate(_art([p]), baseline=None).quarantined == []


def test_a_partly_unsure_probe_still_reports_a_real_mean():
    """The discriminator: one usable trial out of three is a thin measurement,
    not an absent one, and the mean is genuinely its average. A note keyed on
    `unsure_trials > 0` rather than on `trials == unsure_trials` would fire
    here and the claim would be false."""
    cur = _art([_probe("g", trials=3, unsure_trials=2, mean_score=0.0)])
    (q,) = evaluate_gate(cur, baseline=None).quarantined
    assert "NO USABLE SCORE" not in q


# --- baseline persistence ---

def test_baseline_round_trip(tmp_path):
    art = _art([_probe("g", category="grounding", mean_score=1.0,
                       checks=[{"check": "invariant:non-empty", "tier": 1,
                                "required": True, "weight": 1.0, "passed": True,
                                "score": 1.0, "turn": None, "evidence": "",
                                "unsure": False}])])
    path = str(tmp_path / "runs" / "baseline.json")
    save_baseline(art, path)
    loaded = load_baseline(path)
    assert loaded is not None
    assert loaded.pack_name == "example"
    assert loaded.probes[0].id == "g"
    assert loaded == art


def test_save_baseline_strips_trial_records(tmp_path):
    # 2026-08-04 ruling: baselines deliberately exclude per-trial transcripts
    # (privacy/size) — save_baseline drops trial_records from every probe;
    # blessing evidence (pass_k, checks, trials) stays; load_baseline still
    # round-trips (ProbeResult defaults the missing field to [])
    p = _probe("g", category="grounding")
    p.trial_records = [{"epoch": 0, "transcript": "User: hi\nAssistant: hello",
                        "session_seconds": 1.0, "invariant_failures": 0}]
    art = _art([p])
    path = str(tmp_path / "baseline.json")
    save_baseline(art, path)
    data = json.loads((tmp_path / "baseline.json").read_text())
    assert all("trial_records" not in probe for probe in data["probes"])
    loaded = load_baseline(path)
    assert loaded is not None
    assert loaded.probes[0].trial_records == []
    assert loaded.probes[0].pass_k == 1.0 and loaded.probes[0].trials == 1


def test_load_baseline_missing_returns_none(tmp_path):
    assert load_baseline(str(tmp_path / "nope.json")) is None


def test_load_baseline_predating_plan2a_schema_fails_loudly(tmp_path):
    # a Plan-#1-era baseline (probes carry `reducers`) must NOT surface as a
    # bare TypeError from ProbeResult(**p) — it must name the file and tell the
    # user to re-create the baseline (no silent migration layer)
    old = {"pack_name": "example", "pack_hash": "h", "judge_model": "j",
           "created_at": "now", "log_path": "log",
           "probes": [{"id": "g", "category": "grounding", "kind": "regression",
                       "safety_critical": False, "samples": 1,
                       "reducers": {"mean": {"tier1": 1.0}}}]}
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(old))
    with pytest.raises(RuntimeError, match=r"(?s)baseline.*predates.*--update-baseline"):
        load_baseline(str(path))


def test_load_baseline_unknown_top_level_field_is_clean_error_not_typeerror(tmp_path):
    # PR #4 fix #9: an unknown TOP-LEVEL artifact key (e.g. from a future
    # schema) raised a bare TypeError from RunArtifact(**...) that leaked past
    # load_baseline's except ValueError — it must surface as the same clean
    # RuntimeError as any other schema mismatch.
    art = _art([_probe("g")])
    d = art.to_dict()
    d["future_field"] = 42
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(d))
    with pytest.raises(RuntimeError, match=r"(?s)baseline.*--update-baseline"):
        load_baseline(str(path))


def test_load_baseline_corrupt_json_is_not_misdiagnosed_as_old_schema(tmp_path):
    # json.JSONDecodeError is a ValueError subclass — a corrupt file must get
    # its own clear message (naming the path), never the predates-schema text
    path = tmp_path / "baseline.json"
    path.write_text("{not valid json")
    with pytest.raises(RuntimeError, match=r"(?s)baseline.*not valid JSON") as exc:
        load_baseline(str(path))
    assert "predates" not in str(exc.value)
