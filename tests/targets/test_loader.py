import pytest
from pathlib import Path
from evalyn.targets.loader import load_pack, resolve_base_url, AllowlistError

MINIPACK = Path(__file__).parent.parent / "fixtures" / "minipack"

def test_load_pack_reads_spec_and_probes():
    pack = load_pack(MINIPACK)
    assert pack.spec.name == "mini"
    assert any(p.id == "inv-nonempty" for p in pack.probes)

def test_env_default_resolution(monkeypatch):
    monkeypatch.delenv("EVALYN_TARGET_URL", raising=False)
    pack = load_pack(MINIPACK)
    assert pack.spec.env["base_url"] == "http://localhost:8899"  # from ${...:-default}

def test_env_override(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(MINIPACK)
    assert resolve_base_url(pack) == "http://localhost:8899"

def test_allowlist_rejects_unlisted_url(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://evil.example.com")
    pack = load_pack(MINIPACK)
    with pytest.raises(AllowlistError):
        resolve_base_url(pack)
