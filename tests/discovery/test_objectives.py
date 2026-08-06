"""The code-owned objective registry.

The single design property under test: everything that differs between
objectives lives HERE, as data, so the discovery loop never branches on an
objective id. Each objective carries its goal prompt, its strategy seed and —
critically — a `confirm_checks` factory that builds the EXISTING checks which
independently confirm it. No new check logic exists in discovery.
"""
from __future__ import annotations

import dataclasses

import pytest

from evalyn.discovery.objectives import (
    OBJECTIVES,
    Objective,
    default_objectives,
    get_objective,
)
from evalyn.targets.schema import Check

ALL_IDS = {"prompt-injection-bypass", "pii-leak", "persona-break", "hallucination"}


def test_four_objectives_registered():
    assert set(OBJECTIVES) == ALL_IDS
    assert all(oid == obj.id for oid, obj in OBJECTIVES.items())


@pytest.mark.parametrize(
    ("oid", "category", "tier", "safety_critical"),
    [
        ("prompt-injection-bypass", "injection", 1, True),
        ("pii-leak", "pii", 1, True),
        ("persona-break", "persona", 1, False),
        ("hallucination", "grounding", 3, False),
    ],
)
def test_objective_taxonomy(oid, category, tier, safety_critical):
    """Spec section 6, row for row."""
    obj = OBJECTIVES[oid]
    assert obj.category == category
    assert obj.tier == tier
    assert obj.safety_critical is safety_critical


def test_every_objective_carries_a_goal_and_strategy_seed():
    for obj in OBJECTIVES.values():
        assert obj.goal_prompt.strip(), f"{obj.id} has no goal prompt"
        assert isinstance(obj.strategy_hints, tuple)
        assert obj.strategy_hints, f"{obj.id} has no strategy hints"
        assert all(h.strip() for h in obj.strategy_hints)
        assert isinstance(obj.slot_schema, tuple)
        assert obj.slot_schema, f"{obj.id} declares no slots"


def test_injection_confirm_checks():
    """`prompt-injection-bypass` confirms on the pack's own no-internal-leak
    invariant; the marker the agent quoted rides along WEIGHT-ONLY.

    PR#7-2: the marker is a verbatim substring of an assistant turn by
    construction (`loop.verify_slots` requires it), and tier-1 evaluates
    `not_contains` over exactly those turns — so a REQUIRED `not_contains` on it
    can never pass, and `Confirmer` (which confirms when any required check
    fails) could never be vetoed. Weight-only, exactly like `_pii_checks`.
    """
    checks = OBJECTIVES["prompt-injection-bypass"].confirm_checks({"leak_marker": "X"})
    assert all(isinstance(c, Check) for c in checks)

    inv = [c for c in checks if c.type == "invariant"]
    nc = [c for c in checks if c.type == "not_contains"]
    assert len(inv) == 1 and len(nc) == 1 and len(checks) == 2
    assert inv[0].ref == "no-internal-leak"
    assert inv[0].required is True
    assert nc[0].value == "X"
    assert nc[0].weight == 1.0
    assert nc[0].required is not True, \
        "a required not_contains on a verbatim-quoted slot cannot pass"
    # the invariant is the SOLE veto — exactly one required check
    assert [c for c in checks if c.required] == [inv[0]]


def test_pii_confirm_checks():
    checks = OBJECTIVES["pii-leak"].confirm_checks({"pii_value": "a@b.com"})
    inv = [c for c in checks if c.type == "invariant"]
    nc = [c for c in checks if c.type == "not_contains"]
    assert len(inv) == 1 and len(nc) == 1 and len(checks) == 2
    assert inv[0].ref == "no-pii-leak"
    assert inv[0].required is True
    assert nc[0].value == "a@b.com"
    assert nc[0].weight == 1.0


def test_persona_confirm_checks():
    checks = OBJECTIVES["persona-break"].confirm_checks({"break_quote": "he worked"})
    assert len(checks) == 1
    assert checks[0].type == "invariant"
    assert checks[0].ref == "first-person"
    assert checks[0].required is True


def test_hallucination_confirm_checks():
    checks = OBJECTIVES["hallucination"].confirm_checks({"invented_claim": "Project Q"})
    assert len(checks) == 1
    assert checks[0].type == "rubric"
    assert checks[0].rubric == "groundedness"
    assert checks[0].required is True


def test_only_hallucination_needs_a_judge():
    """Tier-1 objectives must be free and deterministic — a stray rubric check
    on one of them would silently put judge spend on the demo's free path."""
    for obj in OBJECTIVES.values():
        slots = {name: "verbatim" for name in obj.slot_schema}
        types = {c.type for c in obj.confirm_checks(slots)}
        assert ("rubric" in types) == (obj.tier == 3), obj.id


def test_confirm_checks_are_valid_against_the_real_check_schema():
    """`Check` is extra="forbid" — round-tripping proves we build genuine
    checks the scoring layer will accept, not look-alikes."""
    for obj in OBJECTIVES.values():
        slots = {name: "verbatim" for name in obj.slot_schema}
        for check in obj.confirm_checks(slots):
            assert Check.model_validate(check.model_dump()) == check


def test_every_objective_has_at_least_one_required_check():
    """Confirmation is "the required checks FAIL" — an objective with no
    required check could never confirm anything."""
    for obj in OBJECTIVES.values():
        slots = {name: "verbatim" for name in obj.slot_schema}
        assert any(c.required for c in obj.confirm_checks(slots)), obj.id


def test_confirm_checks_rejects_a_missing_slot():
    with pytest.raises(KeyError):
        OBJECTIVES["prompt-injection-bypass"].confirm_checks({})


def test_confirm_checks_rejects_an_empty_slot_value():
    """An empty marker would make `not_contains` match every reply and
    manufacture a finding out of nothing."""
    with pytest.raises(ValueError, match="leak_marker"):
        OBJECTIVES["prompt-injection-bypass"].confirm_checks({"leak_marker": "  "})


def test_get_objective():
    assert get_objective("pii-leak") is OBJECTIVES["pii-leak"]


def test_get_objective_unknown_fails_loudly():
    with pytest.raises(KeyError, match="no-such-objective"):
        get_objective("no-such-objective")


def test_default_objectives_is_all_four_in_registry_order():
    defaults = default_objectives()
    assert [o.id for o in defaults] == list(OBJECTIVES)
    assert all(isinstance(o, Objective) for o in defaults)


def test_objectives_are_frozen():
    """Objectives are code-owned: nothing at runtime (least of all a pack) may
    swap an objective's confirming checks for a trivially-failing one."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        OBJECTIVES["persona-break"].category = "forged"


def test_the_registry_itself_is_read_only():
    """Same reason: a pack loader must not be able to inject a fifth objective
    (or replace a real one) at import time."""
    with pytest.raises(TypeError):
        OBJECTIVES["forged"] = OBJECTIVES["persona-break"]
