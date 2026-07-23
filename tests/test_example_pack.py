from evalyn.targets.loader import load_pack


def test_example_pack_loads_and_is_balanced(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack("packs/example")
    cats = {p.category for p in pack.probes}
    assert {"invariants", "injection", "grounding"} <= cats
    inj = [p for p in pack.probes if p.category == "injection"]
    # balanced: at least one attack (safety_critical) and one benign control
    assert any(p.safety_critical for p in inj) and any(not p.safety_critical for p in inj)
