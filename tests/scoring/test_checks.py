from evalyn.scoring.checks import aggregate_trial, check_result


def test_check_result_shape():
    r = check_result("invariant:x", tier=1, required=True, weight=1.0,
                     passed=False, score=0.0, turn=2, evidence="leak")
    assert r == {"check": "invariant:x", "tier": 1, "required": True, "weight": 1.0,
                 "passed": False, "score": 0.0, "turn": 2, "evidence": "leak",
                 "unsure": False}


def test_check_result_defaults():
    r = check_result("c", tier=2, required=False, weight=2.0, passed=None, score=0.0)
    assert r["turn"] is None and r["evidence"] == "" and r["unsure"] is False


# --- aggregate_trial: the Shared-Contract trial aggregation rule ---

def test_required_failure_zeroes_trial():
    crs = [check_result("a", 1, True, 1.0, False, 0.0),
           check_result("b", 2, False, 1.0, True, 1.0)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is False and unsure is False and score == 0.0


def test_weighted_nonrequired_mean_when_required_pass():
    crs = [check_result("req", 1, True, 1.0, True, 1.0),
           check_result("q1", 3, False, 3.0, True, 1.0),
           check_result("q2", 3, False, 1.0, False, 0.0)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is True and unsure is False
    assert score == (3.0 * 1.0 + 1.0 * 0.0) / (3.0 + 1.0)  # 0.75


def test_unsure_required_is_not_pass_and_carries_no_score_signal():
    # round-2 N3: a required check the judge could not decide leaves the trial
    # with NO trustworthy score — same no-signal semantics as the
    # all-non-required-unsure case (score None, excluded from mean downstream),
    # never a fabricated 1.0 that a judge outage would turn into a green mean
    crs = [check_result("req", 2, True, 1.0, None, 0.0, unsure=True)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is False and unsure is True and score is None


def test_unsure_required_suppresses_nonrequired_mean():
    # round-2 N3 repro: required-unsure alongside a perfect non-required check
    # must NOT fall through to the non-required mean (1.0) — on non-safety
    # probes (gated by mean only) that would turn a judge outage green
    crs = [check_result("req", 2, True, 1.0, None, 0.0, unsure=True),
           check_result("q1", 3, False, 1.0, True, 1.0)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is False and unsure is True and score is None


def test_unsure_nonrequired_excluded_from_weighted_mean():
    crs = [check_result("q1", 3, False, 1.0, True, 1.0),
           check_result("q2", 3, False, 1.0, None, 0.0, unsure=True)]
    _, _, score = aggregate_trial(crs)
    assert score == 1.0  # q2 excluded from numerator and denominator


def test_no_required_checks_is_trivially_satisfied():
    crs = [check_result("q1", 3, False, 2.0, True, 1.0),
           check_result("q2", 3, False, 2.0, True, 0.5)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is True and unsure is False and score == 0.75


def test_malformed_required_passed_none_without_unsure_is_not_a_pass():
    # fail-open guard (reviewer fix 1): the contract says required_pass is True
    # iff EVERY required check has passed is True — a malformed required check
    # with passed=None but unsure=False must NOT count as passing. It is also
    # neither a product failure (no required False) nor a NOANSWER (the check
    # is not marked unsure), so trial_unsure stays False and the score falls
    # through to the non-required weighted mean.
    crs = [check_result("req", 1, True, 1.0, None, 0.0)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is False
    assert unsure is False
    assert score == 1.0  # no required False, no usable non-required checks


def test_all_zero_weight_nonrequired_falls_back_to_one():
    # pin the den == 0 fallback: all non-required checks usable but weightless
    crs = [check_result("q1", 3, False, 0.0, True, 1.0),
           check_result("q2", 3, False, 0.0, False, 0.0)]
    _, _, score = aggregate_trial(crs)
    assert score == 1.0


def test_all_nonrequired_unsure_is_no_signal_not_perfect_score():
    # PR #4 fix #1 (fail-open): non-required checks EXIST but ALL are unsure —
    # there is no score signal at all, so the trial must come back unsure with
    # score None (excluded from mean_score downstream), never a perfect 1.0.
    crs = [check_result("classifier:0", 2, False, 1.0, None, 0.0, unsure=True),
           check_result("classifier:1", 2, False, 1.0, None, 0.0, unsure=True)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is True      # no required checks -> trivially satisfied
    assert unsure is True        # no-signal trial is NOANSWER, not a pass
    assert score is None         # excluded from mean_score, never 1.0


def test_required_pass_with_all_nonrequired_unsure_is_still_no_signal():
    crs = [check_result("req", 1, True, 1.0, True, 1.0),
           check_result("classifier:0", 2, False, 1.0, None, 0.0, unsure=True)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is True and unsure is True and score is None


def test_required_failure_dominates_all_nonrequired_unsure():
    # a definite required failure zeroes the trial even when every non-required
    # check is unsure — product failure beats NOANSWER
    crs = [check_result("req", 1, True, 1.0, False, 0.0),
           check_result("classifier:0", 2, False, 1.0, None, 0.0, unsure=True)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is False and unsure is False and score == 0.0


def test_required_false_beats_required_unsure_for_trial_unsure():
    # a definite required failure is a product failure, not a NOANSWER
    crs = [check_result("r1", 1, True, 1.0, False, 0.0),
           check_result("r2", 2, True, 1.0, None, 0.0, unsure=True)]
    req_pass, unsure, score = aggregate_trial(crs)
    assert req_pass is False and unsure is False and score == 0.0
