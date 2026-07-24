from evalyn.scoring.checks import check_result


def test_check_result_shape():
    r = check_result("invariant:x", tier=1, required=True, weight=1.0,
                     passed=False, score=0.0, turn=2, evidence="leak")
    assert r == {"check": "invariant:x", "tier": 1, "required": True, "weight": 1.0,
                 "passed": False, "score": 0.0, "turn": 2, "evidence": "leak",
                 "unsure": False}


def test_check_result_defaults():
    r = check_result("c", tier=2, required=False, weight=2.0, passed=None, score=0.0)
    assert r["turn"] is None and r["evidence"] == "" and r["unsure"] is False
