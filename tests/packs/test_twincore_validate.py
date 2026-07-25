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


def test_twincore_allowlist_is_localhost_8000_only(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "https://twincore.example.com")
    pack = load_pack(PACK)
    assert pack.spec.allowlist == ["http://localhost:8000", "http://127.0.0.1:8000"]
    with pytest.raises(AllowlistError):
        resolve_base_url(pack)
