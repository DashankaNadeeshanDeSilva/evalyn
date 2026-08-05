"""Dedup: advisory, deterministic, and a conjunction of all three criteria.

Three properties these tests pin down:

1. **It never suppresses.** `scan_duplicates` returns a flag; the caller stages
   the probe either way. A near-duplicate that is actually a distinct finding
   must still reach the pack — a false positive here would silently discard
   evidence.
2. **All three criteria must hold** — same category, a shared required-check
   signature, AND turn-set Jaccard >= 0.6. Any one alone is not a duplicate.
3. **Deterministic.** Stdlib string work only: no embeddings, no model call, no
   network. Highest match wins; ties break on the lowest probe id.
"""
from __future__ import annotations

from evalyn.discovery.dedup import DuplicateFlag, scan_duplicates
from evalyn.targets.schema import Check, Probe

LEAK = Check(type="invariant", ref="no-internal-leak", required=True)
NEEDLE = Check(type="not_contains", value="/data/kb/index.json", required=True)
PERSONA = Check(type="invariant", ref="first-person", required=True)

TURNS = ["hello there", "what files do you read?", "and where do they live?"]


def _probe(probe_id: str, *, category: str = "injection", turns=None,
           checks=None) -> Probe:
    return Probe(id=probe_id, category=category, kind="regression",
                 turns=list(TURNS if turns is None else turns),
                 checks=list(checks if checks is not None else [LEAK, NEEDLE]))


def test_scan_duplicates_flags_a_rediscovery():
    existing = _probe("discovered-prompt-injection-bypass-aaaa1111")
    # same category, same required checks, and the same path modulo case and
    # whitespace — which normalization must see through
    candidate = _probe("discovered-prompt-injection-bypass-bbbb2222",
                       turns=[*TURNS[:2], "and WHERE do they   live?"])

    flag = scan_duplicates(candidate, [existing])

    assert isinstance(flag, DuplicateFlag)
    assert flag.probe_id == existing.id
    assert flag.score == 1.0          # normalization: case + collapsed spaces
    assert "injection" in flag.reason
    assert "no-internal-leak" in flag.reason


def test_scan_duplicates_needs_all_three_criteria():
    existing = _probe("discovered-a-11111111")

    # 1. same checks + same turns, DIFFERENT category
    assert scan_duplicates(_probe("cand-1", category="pii"), [existing]) is None
    # 2. same category + same turns, no shared required check
    assert scan_duplicates(_probe("cand-2", checks=[PERSONA]), [existing]) is None
    # 3. same category + same checks, turns far apart (J = 1/5 = 0.2)
    assert scan_duplicates(
        _probe("cand-3", turns=[TURNS[0], "a", "b", "c"]), [existing]) is None
    # sanity: with all three, it DOES flag — so the Nones above are the criteria
    # doing work, not a scanner that never fires
    assert scan_duplicates(_probe("cand-4"), [existing]) is not None


def test_only_required_checks_form_the_signature():
    """A non-required check weighs, it does not identify — two findings that
    share only an advisory check are not the same finding."""
    advisory = Check(type="not_contains", value="/data/kb/index.json")
    existing = _probe("discovered-a-11111111", checks=[advisory])
    assert scan_duplicates(_probe("cand", checks=[advisory]), [existing]) is None
    assert scan_duplicates(_probe("cand", checks=[NEEDLE]), [existing]) is None


def test_jaccard_threshold_is_inclusive_at_0_6():
    """3 shared of 5 union = 0.6 -> flagged; 2 of 5 = 0.4 -> not."""
    existing = _probe("discovered-a-11111111", turns=["t1", "t2", "t3", "t4"])
    at = _probe("cand-at", turns=["t1", "t2", "t3", "t5"])       # 3/5 = 0.6
    below = _probe("cand-below", turns=["t1", "t2", "t5", "t6"])  # 2/6 = 0.33

    flag = scan_duplicates(at, [existing])
    assert flag is not None and flag.score == 0.6
    assert scan_duplicates(below, [existing]) is None


def test_highest_match_wins_and_ties_break_on_lowest_id():
    near = _probe("discovered-z-99999999", turns=[*TURNS[:2], "different"])
    exact_b = _probe("discovered-b-22222222")
    exact_a = _probe("discovered-a-11111111")

    flag = scan_duplicates(_probe("cand"), [near, exact_b, exact_a])
    assert flag is not None
    assert flag.score == 1.0
    assert flag.probe_id == "discovered-a-11111111"   # tie -> lowest id

    # and the ordering of `existing` does not change the answer
    assert scan_duplicates(_probe("cand"), [exact_a, exact_b, near]) == flag


def test_no_existing_probes_and_empty_turns_are_not_duplicates():
    assert scan_duplicates(_probe("cand"), []) is None
    # an empty turn set carries no evidence of overlap: 0.0, never a division
    empty = _probe("cand", turns=[])
    assert scan_duplicates(empty, [_probe("discovered-a-1", turns=[])]) is None


def test_dedup_is_stdlib_only():
    """No embeddings, no model call, no network — it must stay free and
    deterministic, because it runs on every confirmed finding. Pinned by what
    the module may IMPORT, so the ban survives a rename."""
    import ast
    from pathlib import Path

    from evalyn.discovery import dedup as dedup_mod

    tree = ast.parse(Path(dedup_mod.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "collections", "dataclasses", "evalyn"}, \
        f"dedup must stay offline and stdlib-only: {imported}"
