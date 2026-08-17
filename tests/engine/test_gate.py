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
    """The false parenthetical: on a run nobody stopped, `never` having no
    scores is guessed to be errors and the report says so with a `?`. On a
    stopped run that guess is not merely hedged, it is one of two stories the
    artifact cannot choose between — see the hedging test below."""
    stopped, finished = _cancelled_pair()
    assert "all trials errored?" in finished.report_md    # the control
    assert "all trials errored?" not in stopped.report_md
    assert "the run was stopped before this probe ran" in stopped.report_md


def test_a_stopped_run_hedges_both_causes_of_a_probe_with_no_scores():
    """`trials == 0` has TWO causes and the artifact records neither.

    A stop reduces an un-run probe to `trials=0` (R4-13) and a fully-ERRORED
    probe stays at `trials=0` too (`run.py`: an epoch that produced no checks in
    any scorer is not counted). So on a cancelled run, a target that died before
    the operator pressed Cancel is indistinguishable from a probe the stop
    prevented — and naming only the stop sends the reader past a real fault.
    """
    stopped, _ = _cancelled_pair()
    (missing,) = [f for f in stopped.failures if "`never`" in f]
    assert "stopped" in missing and "errored" in missing
    assert "does not record which" in missing


def test_a_stopped_run_does_not_blame_an_un_run_capability_probe_on_errors():
    """The same hedge on the branch that runs FIRST for capability probes, and
    so never saw the cancelled fork at all: an un-run capability probe on a
    stopped run was still being reported as `all trials errored or unscored`."""
    cap = _probe("cap", category="grounding", kind="capability", trials=0,
                 pass_at_k=0.0, pass_k=0.0, mean_score=0.0)
    stopped = _art([cap])
    stopped.cancelled = True
    ran, halted = evaluate_gate(_art([cap]), None), evaluate_gate(stopped, None)

    assert "all trials errored or unscored" in ran.report_md          # control
    assert "all trials errored or unscored" not in halted.report_md
    assert "the run was stopped before this probe ran" in halted.report_md
    assert "does not record which" in halted.report_md
    assert halted.failures == []      # capability probes still never red a build


def test_a_stopped_run_still_exits_non_zero():
    """Scoped deliberately. The *report* stops claiming a decided verdict; the
    exit code does not become 0, because a run that was stopped part-way has
    not passed and saying so would be the worse lie.

    3, not 1: this run's probes really did fail, but a stopped run's failures
    are not the product's to answer for, and the CLI already spells that
    `run-invalid` (`cli.py`, exit 3). The control run — same probes, no stop —
    is a genuine FAIL and keeps 1, so the two stay distinguishable.
    """
    stopped, finished = _cancelled_pair()
    assert stopped.exit_code == 3 and finished.exit_code == 1
    assert len(stopped.failures) == len(finished.failures) == 2


def _clean_cancelled_pair():
    """A cancel that landed AFTER every probe had scored.

    Not hypothetical: `test_control.py::test_a_cancel_that_lands_after_scoring
    _still_marks_the_artifact` builds exactly this from a real run — complete,
    passing, and `cancelled` the only thing wrong with it. It is the shape that
    makes `1 if failures else 0` dangerous, because there are no failures.
    """
    probes = [_probe("ran", category="grounding", mean_score=1.0)]
    stopped = _art(probes)
    stopped.cancelled = True
    return evaluate_gate(stopped, None), evaluate_gate(_art(probes), None)


def test_a_cancelled_run_whose_probes_all_passed_still_never_exits_zero():
    """0 does not mean "no failures" to anyone downstream — it means PASS.

    `GET /api/runs/{id}/gate` serves this integer verbatim, and a 0 beside a
    report whose own banner reads **NO VERDICT** is the report calling the
    endpoint a liar. The control proves the artifact is otherwise spotless, so
    the only thing the assertion can be reading is the stop.
    """
    stopped, finished = _clean_cancelled_pair()
    assert finished.exit_code == 0 and finished.failures == []   # control
    assert stopped.failures == []          # nothing to blame — that is the trap
    assert stopped.exit_code == 3
    assert "**NO VERDICT**" in stopped.report_md


def test_the_no_verdict_banner_only_points_below_when_there_is_something_there():
    """The banner used to promise "the probes the stop prevented from running
    appear below as MISSING" on every cancelled run. On a cancel that landed
    after scoring there is no such probe and no such line, so the promise sent
    the reader looking for a section that is not there. The partial run is the
    control: the pointer must survive where it is true."""
    stopped_clean, _ = _clean_cancelled_pair()
    stopped_partial, _ = _cancelled_pair()

    assert "1 probe(s) recorded no trials at all" in stopped_partial.report_md
    assert "MISSING" in stopped_partial.report_md                      # control
    assert "MISSING" not in stopped_clean.report_md
    assert "recorded no trials" not in stopped_clean.report_md
    assert "the stop landed after they had run" in stopped_clean.report_md


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


def test_a_probe_nobody_could_score_is_reported_even_when_the_baseline_is_zero_too():
    """The hole: every arm of the regression branch is a COMPARISON, and a probe
    nobody could score compares fine.

    Its fallback mean is 0.00, so against a baseline mean of 0.00 the drop is
    neither `> band` nor `> 0`, and the `(no baseline)` arm cannot run because a
    baseline exists — the probe produced no line anywhere and a total judge
    outage read as a clean PASS. A 0.00 baseline mean is reachable:
    `--update-baseline` blesses FAIL verdicts.

    `ctl` is the control and must stay silent: a measured 0.00 that matches its
    measured baseline is a genuine non-event, so this is not "print every
    probe", it is "never swallow a probe that was not measured".
    """
    base = _art([_probe("g", mean_score=0.0), _probe("ctl", mean_score=0.0)])
    cur = _art([_probe("g", trials=3, unsure_trials=3, mean_score=0.0),
                _probe("ctl", trials=3, mean_score=0.0)])
    res = evaluate_gate(cur, baseline=base)

    lines = res.failures + res.quarantined
    assert [ln for ln in lines if "`ctl`" in ln] == []            # control
    (line,) = [ln for ln in lines if "`g`" in ln]
    assert "NO USABLE SCORE" in line


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


def test_every_unmeasured_line_spends_the_same_words_from_one_source():
    """ONE source for `NO USABLE SCORE`, proven structurally.

    The marker is what a reader greps and what a consumer keys on, and the
    safety lines used to hand-write their own wording — so a future edit to
    `_NO_SIGNAL` would have left them stale and silently unfindable. Asserting
    each line *ends with* the shared constant fails for any re-typed copy, which
    a substring check for the marker text would not.
    """
    from evalyn.engine.gate import _NO_SIGNAL
    note = _NO_SIGNAL.format(n=3)

    unmeasured = dict(trials=3, unsure_trials=3, mean_score=0.0)
    cur = _art([_probe("passes", category="injection", safety=True, samples=3,
                       pass_k=1.0, **unmeasured),
                _probe("fails", category="injection", safety=True, samples=3,
                       pass_k=0.0, **unmeasured),
                _probe("regressed", **unmeasured),
                _probe("no-base", **unmeasured),
                _probe("cap", kind="capability", **unmeasured)])
    res = evaluate_gate(cur, baseline=_art([_probe("regressed", mean_score=1.0)]))

    lines = res.failures + res.quarantined + res.report_md.splitlines()
    for pid in ("passes", "fails", "regressed", "no-base", "cap"):
        (line, *_) = [ln for ln in lines if f"`{pid}`" in ln]
        assert line.endswith(note), f"{pid}: {line!r}"


def test_a_safety_failure_says_whether_it_was_measured_at_all():
    """Both probes FAIL, and both must: an unsure REQUIRED check already forces
    `pass^k` to 0, and a safety probe nobody could score does not get the
    benefit of the doubt. That verdict is pinned policy and this does not touch
    it.

    What it does touch is that the two were told apart only by comparing an
    unsure count against a trial total the line never printed. `real` is the
    control — a measured, on-its-merits safety failure — and it must NOT pick up
    the marker, or the marker would just mean "a safety probe failed".
    """
    from evalyn.engine.gate import _NO_SIGNAL
    real = _probe("real", category="injection", safety=True, samples=3, trials=3,
                  pass_k=0.0, unsure_trials=0, mean_score=0.0)
    outage = _probe("outage", category="injection", safety=True, samples=3,
                    trials=3, pass_k=0.0, unsure_trials=3, mean_score=0.0)
    res = evaluate_gate(_art([real, outage]), None)

    assert res.exit_code == 1 and len(res.failures) == 2
    (measured,) = [f for f in res.failures if "`real`" in f]
    (absent,) = [f for f in res.failures if "`outage`" in f]
    assert "NO USABLE SCORE" not in measured
    assert absent.endswith(_NO_SIGNAL.format(n=3))


def test_a_partly_unsure_safety_failure_still_reports_its_unsure_count():
    """The control for the branch above: two unsure trials out of three is a
    real measurement with a caveat, so the pre-existing `(2 unsure)` suffix must
    survive — the new marker replaces it only when there is nothing to measure.
    """
    p = _probe("inj", category="injection", safety=True, samples=3, trials=3,
               pass_k=0.0, unsure_trials=2, mean_score=0.5)
    (f,) = evaluate_gate(_art([p]), None).failures
    assert "(2 unsure)" in f and "NO USABLE SCORE" not in f


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


# --- the unmeasured mean is recorded as None, and the gate does not notice ----
#
# `run.py` records `mean_score=None` when no trial produced a usable score, so
# an unmeasured probe stops being indistinguishable from one that genuinely
# scored zero everywhere. The gate is the ONE consumer that must be unmoved by
# that: verdicts are pinned policy and this change is a reporting fix. These
# tests are the proof, and they are written as equivalence rather than as
# expected literals — a re-derived literal could drift with the report wording,
# but "these two artifacts gate identically" cannot.

#: The shape `run.py` now records `mean_score=None` for: trials ran, and every
#: one of them came back unsure. `_probe` leaves `expected_trials` at 0
#: ("unknown"), which skips the INCOMPLETE check so these reach the arms under
#: test rather than short-circuiting there.
_UNMEASURED = dict(trials=3, unsure_trials=3)


@pytest.mark.parametrize("base_mean, band", [
    (1.0, 0.1),    # a big drop: REGRESSION fires, and must keep firing
    (0.05, 0.1),   # a drop inside the band: quarantine arm
    (0.0, 0.1),    # no drop at all: the `_no_usable_score` catch-all arm
])
def test_none_mean_gates_exactly_as_the_old_fallback_zero_did(base_mean, band):
    """A `None` mean and the fabricated `0.0` it replaced gate identically.

    Same probe twice — same trials, same unsure count, same everything — except
    that one carries the new `None` and the other the `0.0` an artifact written
    before this change carries. Exit code, failures and the rendered report must
    match character for character, across every arm a non-safety probe can take.
    That is `gate._mean` doing its job: it re-applies the old fallback at the
    point of use, so no verdict and no line of prose moved.
    """
    baseline = _art([_probe("g", mean_score=base_mean)])
    nulled = evaluate_gate(_art([_probe("g", mean_score=None, **_UNMEASURED)]),
                           baseline, band=band)
    legacy = evaluate_gate(_art([_probe("g", mean_score=0.0, **_UNMEASURED)]),
                           baseline, band=band)
    assert (nulled.exit_code, nulled.failures, nulled.quarantined, nulled.report_md) \
        == (legacy.exit_code, legacy.failures, legacy.quarantined, legacy.report_md)
    # Not vacuous: the pair really did travel an arm that reads the mean, and
    # the reader was told the 0.00 printed there was never measured.
    assert "NO USABLE SCORE" in nulled.report_md


def test_a_none_mean_still_fails_the_regression_gate_it_used_to():
    """The fail-closed half, asserted on its own so the parametrize can't hide it.

    An unmeasured probe against a 1.0 baseline is a REGRESSION today and stays
    one. If `_mean` were ever "simplified" into skipping the comparison when the
    mean is absent, a total judge outage would read as a clean pass — the exact
    fail-open round-2 N3 closed.
    """
    res = evaluate_gate(_art([_probe("g", mean_score=None, **_UNMEASURED)]),
                        _art([_probe("g", mean_score=1.0)]))
    assert res.exit_code == 1
    assert any("REGRESSION" in f for f in res.failures)


def test_a_none_mean_in_the_BASELINE_is_not_read_as_a_missing_baseline():
    """A blessed baseline may itself carry an unmeasured probe.

    `--update-baseline` blesses FAIL verdicts, so a baseline probe nobody could
    score is reachable, and once such a run is blessed its `mean_score` is
    `None`. `_baseline_mean` must fold that to 0.0, not return the `None` that
    means "this probe is absent from the baseline" — otherwise a blessed probe
    is reported as having no baseline at all, on a run where it plainly does.
    """
    unmeasured_baseline = _art([_probe("g", mean_score=None, **_UNMEASURED)])
    res = evaluate_gate(_art([_probe("g", mean_score=0.5)]), unmeasured_baseline)
    assert not any("no baseline" in q for q in res.quarantined), res.quarantined
    # control: the same current probe against a baseline that truly lacks it
    absent = evaluate_gate(_art([_probe("g", mean_score=0.5)]),
                           _art([_probe("other", mean_score=1.0)]))
    assert any("no baseline" in q for q in absent.quarantined)


def test_a_float_mean_artifact_written_before_this_change_still_loads(tmp_path):
    """Every artifact and baseline on disk carries a float. They must keep working.

    `from_dict` does no type coercion, so the guarantee is really about the
    consumers: a float mean survives the round trip unchanged and still gates.
    The `None` round trip is asserted beside it because JSON has a null and
    `asdict` writes it — a loader that choked on it would strand every artifact
    written from here on.
    """
    legacy = _art([_probe("g", mean_score=0.0, **_UNMEASURED)])
    path = tmp_path / "baseline.json"
    save_baseline(legacy, str(path))
    assert load_baseline(str(path)).probes[0].mean_score == 0.0

    current = _art([_probe("g", mean_score=None, **_UNMEASURED)])
    save_baseline(current, str(path))
    assert load_baseline(str(path)).probes[0].mean_score is None
    # and the null really is what reached the file, not a coerced zero
    assert json.loads(path.read_text())["probes"][0]["mean_score"] is None
