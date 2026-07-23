from evalyn.targets.schema import TargetSpec, Probe, Check


def test_probe_defaults_to_regression_kind():
    p = Probe(id="p1", category="grounding", turns=["hi"],
              checks=[Check(type="invariant", ref="non-empty")])
    assert p.kind == "regression"
    assert p.safety_critical is False
    assert p.samples == 1
    assert p.checks[0].required is False and p.checks[0].weight == 1.0


def test_targetspec_parses_minimal_mapping():
    spec = TargetSpec.model_validate({
        "name": "toy",
        "sessions": {"open": {"method": "POST", "path": "/session"},
                     "message": {"method": "POST", "path": "/chat",
                                 "stream": "sse", "event_format": "vercel-ai"}},
        "auth": {"kind": "none"},
        "env": {"base_url": "http://localhost:8899"},
        "allowlist": ["http://localhost:8899"],
        "invariants": [{"id": "non-empty"}],
    })
    assert spec.sessions["message"].event_format == "vercel-ai"
    assert spec.budget.max_usd_per_run == 5.0
    assert spec.concurrency == 4


def test_capability_and_safety_flags_roundtrip():
    p = Probe(id="p2", category="injection", kind="capability",
              safety_critical=True, turns=["x"],
              checks=[Check(type="classifier", question="refused?", expect=True)],
              samples=3)
    assert p.kind == "capability" and p.safety_critical is True and p.samples == 3
