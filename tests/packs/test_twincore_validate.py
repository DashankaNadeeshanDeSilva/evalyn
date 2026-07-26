import pytest

from evalyn.engine.validate import validate_pack
from evalyn.targets.loader import AllowlistError, load_pack, resolve_base_url

PACK = "packs/twincore"


def test_twincore_pack_validates():
    report = validate_pack(load_pack(PACK))
    assert report.ok, report.errors


def test_twincore_injection_suite_is_the_full_31_cases():
    """27 single-turn attacks + 1 multi-turn attack + 3 benign controls."""
    inj = [p for p in load_pack(PACK).probes if p.category == "injection"]
    attacks = [p for p in inj if p.safety_critical]
    controls = [p for p in inj if not p.safety_critical]
    assert len(inj) == 31
    assert len(attacks) == 28 and len(controls) == 3
    assert sum(1 for p in attacks if len(p.turns) > 1) == 1


def test_twincore_slug_is_substituted_into_session_paths(monkeypatch):
    monkeypatch.setenv("EVALYN_TWIN_SLUG", "acme-twin")
    sessions = load_pack(PACK).spec.sessions
    assert sessions["open"].path == "/api/twin/acme-twin/consent"
    assert sessions["message"].path == "/api/twin/acme-twin/chat"


def test_twincore_committed_calibration_record_is_stale_per_rubric(monkeypatch):
    """PR #4 fix #4 (user-ruled, KNOWN CONSEQUENCE): the committed record's
    groundedness criteria sit at 0.6/0.6 — below the 85% per-rubric bar — so
    despite the 0.875 overall the record is STALE and the gate must refuse
    twincore rubric checks until groundedness is re-anchored."""
    from evalyn.engine.calibrate import is_stale

    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8000")
    pack = load_pack(PACK)
    stale, why = is_stale(pack, "anthropic/claude-sonnet-5")
    assert stale is True
    assert "groundedness" in why
    assert "60%" in why


def test_twincore_allowlist_is_localhost_8000_only(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "https://twincore.example.com")
    pack = load_pack(PACK)
    assert pack.spec.allowlist == ["http://localhost:8000", "http://127.0.0.1:8000"]
    with pytest.raises(AllowlistError):
        resolve_base_url(pack)
