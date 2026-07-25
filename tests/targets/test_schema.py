import pytest
from evalyn.targets.schema import TargetSpec, Probe, Check, SessionEndpoint, AuthSpec


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


def test_rubric_check_type_with_rubric_id():
    c = Check(type="rubric", rubric="persona")
    assert c.type == "rubric" and c.rubric == "persona"
    assert c.required is False  # rubric checks default non-required
    assert "rubric" in c.model_dump()  # rides into probe metadata


def test_judge_spec_defaults_and_override():
    spec = TargetSpec.model_validate({
        "name": "toy",
        "sessions": {},
        "allowlist": [],
    })
    assert spec.judge.rubric_model == "anthropic/claude-3-5-sonnet-latest"
    assert spec.judge.generator_family is None

    spec2 = TargetSpec.model_validate({
        "name": "toy",
        "sessions": {},
        "allowlist": [],
        "judge": {"rubric_model": "anthropic/claude-3-7-sonnet-latest",
                  "generator_family": "openai"},
    })
    assert spec2.judge.rubric_model == "anthropic/claude-3-7-sonnet-latest"
    assert spec2.judge.generator_family == "openai"


def test_unknown_event_format_rejected():
    with pytest.raises(ValueError, match="event_format"):
        SessionEndpoint(method="POST", path="/x", event_format="mystery")


def test_named_sse_event_format_accepted():
    ep = SessionEndpoint(method="POST", path="/x", event_format="named-sse",
                         event_name="token", content_field="content")
    assert ep.event_name == "token" and ep.content_field == "content"


def test_session_endpoint_flow_field_defaults():
    ep = SessionEndpoint(method="POST", path="/x")
    assert ep.open_body == {}
    assert ep.session_id_field == "session_id"
    assert ep.message_field == "message"
    assert ep.session_field == "session_id"
    assert ep.event_name is None and ep.content_field is None


def test_targetspec_auth_parses_to_authspec():
    spec = TargetSpec.model_validate({
        "name": "t", "sessions": {}, "allowlist": [],
        "auth": {"kind": "bearer", "token": "tok"},
    })
    assert isinstance(spec.auth, AuthSpec)
    assert spec.auth.kind == "bearer" and spec.auth.token == "tok"


def test_targetspec_auth_defaults_to_none_kind():
    spec = TargetSpec.model_validate({"name": "t", "sessions": {}, "allowlist": []})
    assert spec.auth.kind == "none"
