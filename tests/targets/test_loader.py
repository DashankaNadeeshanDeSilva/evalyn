import pytest
from pathlib import Path
from evalyn.targets.loader import load_pack, resolve_base_url, AllowlistError, PackError

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

def test_load_pack_missing_target_yaml(tmp_path):
    """load_pack raises PackError when target.yaml is missing."""
    empty_pack = tmp_path / "empty"
    empty_pack.mkdir()
    with pytest.raises(PackError, match="no target.yaml"):
        load_pack(empty_pack)

def test_load_pack_invalid_target_spec(tmp_path):
    """load_pack raises PackError when target.yaml is schema-invalid."""
    invalid_pack = tmp_path / "invalid"
    invalid_pack.mkdir()
    # Create target.yaml missing required 'sessions' field
    target_file = invalid_pack / "target.yaml"
    target_file.write_text("name: test\nallowlist: []\n")
    with pytest.raises(PackError, match="invalid target.yaml"):
        load_pack(invalid_pack)

def test_load_pack_empty_target_yaml(tmp_path):
    """An empty target.yaml is a PackError, not an AttributeError."""
    empty_pack = tmp_path / "empty_yaml"
    empty_pack.mkdir()
    (empty_pack / "target.yaml").write_text("")
    with pytest.raises(PackError, match="invalid target.yaml"):
        load_pack(empty_pack)

def test_probe_with_zero_samples_is_pack_error(tmp_path):
    """samples must be >= 1; samples: 0 is rejected at load time."""
    bad_pack = tmp_path / "zero_samples"
    bad_pack.mkdir()
    (bad_pack / "target.yaml").write_text(
        "name: test\n"
        "sessions:\n"
        "  session1: { method: POST, path: /session }\n"
        "allowlist: []\n"
    )
    probes_dir = bad_pack / "probes"
    probes_dir.mkdir()
    (probes_dir / "p.yaml").write_text(
        "- id: zero\n  category: test\n  turns: [hi]\n  checks: []\n  samples: 0\n")
    with pytest.raises(PackError, match="invalid probe"):
        load_pack(bad_pack)

def test_probe_glob_matches_yml_and_yaml_deterministically(tmp_path):
    """Probes in *.yml files load too, in sorted filename order across both suffixes."""
    pack_dir = tmp_path / "yml_pack"
    pack_dir.mkdir()
    (pack_dir / "target.yaml").write_text(
        "name: test\n"
        "sessions:\n"
        "  session1: { method: POST, path: /session }\n"
        "allowlist: []\n"
    )
    probes_dir = pack_dir / "probes"
    probes_dir.mkdir()
    (probes_dir / "b.yaml").write_text(
        "- {id: from-yaml, category: c, turns: [hi], checks: []}\n")
    (probes_dir / "a.yml").write_text(
        "- {id: from-yml, category: c, turns: [hi], checks: []}\n")
    pack = load_pack(pack_dir)
    assert [p.id for p in pack.probes] == ["from-yml", "from-yaml"]  # a.yml < b.yaml

def test_load_pack_invalid_probe(tmp_path):
    """load_pack raises PackError when a probe entry is schema-invalid."""
    invalid_pack = tmp_path / "invalid_probe"
    invalid_pack.mkdir()
    # Create valid target.yaml
    target_file = invalid_pack / "target.yaml"
    target_file.write_text(
        "name: test\n"
        "sessions:\n"
        "  session1: { method: POST, path: /session }\n"
        "allowlist: []\n"
    )
    # Create probes directory with invalid probe (missing required 'turns' field)
    probes_dir = invalid_pack / "probes"
    probes_dir.mkdir()
    probe_file = probes_dir / "test.yaml"
    probe_file.write_text("- id: test-probe\n  category: test\n  checks: []\n")
    with pytest.raises(PackError, match="invalid probe"):
        load_pack(invalid_pack)

def test_load_pack_duplicate_probe_id(tmp_path):
    """load_pack raises PackError when two probes share the same id."""
    dup_pack = tmp_path / "dup_probe"
    dup_pack.mkdir()
    target_file = dup_pack / "target.yaml"
    target_file.write_text(
        "name: test\n"
        "sessions:\n"
        "  session1: { method: POST, path: /session }\n"
        "allowlist: []\n"
    )
    probes_dir = dup_pack / "probes"
    probes_dir.mkdir()
    probe_file = probes_dir / "test.yaml"
    probe_file.write_text(
        "- id: dup-probe\n"
        "  category: test\n"
        "  turns: [\"hi\"]\n"
        "  checks: []\n"
        "- id: dup-probe\n"
        "  category: test\n"
        "  turns: [\"hi\"]\n"
        "  checks: []\n"
    )
    with pytest.raises(PackError, match="dup-probe"):
        load_pack(dup_pack)
