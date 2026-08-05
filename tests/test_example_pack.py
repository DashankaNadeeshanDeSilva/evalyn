from evalyn.discovery.personas import (
    DEFAULT_PERSONA,
    DEFAULT_PLAYBOOK,
    load_personas,
    load_playbooks,
)
from evalyn.targets.loader import load_pack


def test_example_pack_loads_and_is_balanced(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack("packs/example")
    cats = {p.category for p in pack.probes}
    assert {"invariants", "injection", "grounding"} <= cats
    inj = [p for p in pack.probes if p.category == "injection"]
    # balanced: at least one attack (safety_critical) and one benign control
    assert any(p.safety_critical for p in inj) and any(not p.safety_critical for p in inj)


def test_example_pack_ships_curious_auditor_persona_and_playbook():
    """R11-5: the pack's persona/playbook markdown load through the real
    loaders (not the built-in fallback) so `discover` uses the shipped voice."""
    personas = load_personas("packs/example")
    assert "curious-auditor" in personas
    persona = personas["curious-auditor"]
    assert persona.name == "Curious auditor"
    assert "audit" in persona.text.lower()
    # a real pack asset, not the code fallback, is being returned
    assert persona.text != DEFAULT_PERSONA.text

    playbooks = load_playbooks("packs/example")
    assert "trust-then-pivot" in playbooks
    playbook = playbooks["trust-then-pivot"]
    assert playbook.name == "Trust then pivot"
    assert "pivot" in playbook.text.lower()
    assert playbook.text != DEFAULT_PLAYBOOK.text
