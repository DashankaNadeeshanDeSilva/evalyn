"""Shape pins for `packs/twincore-injection` — the demo carve-out.

`packs/twincore-injection` is a **derivative** pack: `probes/injection.yaml` is a
byte-for-byte copy of the same file in `packs/twincore`, and `target.yaml`
differs from twincore's in exactly two human-readable fields (`name`,
`description`). Nothing was moved out of `packs/twincore` — it stays intact, so
every assertion in `test_twincore_validate.py` and every "50 probes" claim in the
READMEs stays true.

The price of copying is drift, and `test_injection_yaml_is_byte_identical_to_twincore`
is what pays it: the two files are pinned equal at the byte level, so a future
edit to TwinCore's redirect constants can never update one copy and silently
leave the other stale.

Paths here are absolute (`Path(__file__).parents[2]`) rather than the
repo-root-relative literals used by `test_twincore_validate.py`, which only pass
when pytest is invoked from the repo root (docs/JOURNAL.md:548).
"""

from pathlib import Path

import pytest

from evalyn.engine.run import pack_fingerprint
from evalyn.engine.validate import validate_pack
from evalyn.targets.loader import load_pack

REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "packs" / "twincore-injection"
TWINCORE = REPO / "packs" / "twincore"

_CONTROL_IDS = {
    "injection-control-background",
    "injection-control-python",
    "injection-control-projects",
}


@pytest.fixture(scope="module")
def pack():
    return load_pack(str(PACK))


def test_twincore_injection_pack_validates(pack):
    report = validate_pack(pack)
    assert report.ok, report.errors


def test_pack_is_the_full_31_injection_cases(pack):
    """28 safety-critical attacks + 3 benign controls, all `category: injection`."""
    assert len(pack.probes) == 31
    attacks = [p for p in pack.probes if p.safety_critical is True]
    controls = [p for p in pack.probes if p.safety_critical is False]
    assert len(attacks) == 28
    assert {p.id for p in controls} == _CONTROL_IDS
    assert all(p.category == "injection" for p in pack.probes)


def test_injection_yaml_is_byte_identical_to_twincore():
    """The anti-drift guard that makes copying (rather than moving) safe.

    `injection.yaml:11-12` says these probes are deliberately coupled to
    TwinCore's verbatim redirect constants and "must be updated" when those
    change. Two copies mean two places to update; this test turns a silent
    divergence into a red suite.
    """
    assert (PACK / "probes" / "injection.yaml").read_bytes() == (
        TWINCORE / "probes" / "injection.yaml"
    ).read_bytes()


def test_pack_has_no_rubric_checks_so_the_calibration_gate_stays_dormant(pack):
    """Zero rubric checks is load-bearing, not incidental.

    `cli.py` guards the whole fail-closed calibration block behind
    `has_rubric`; with none, `is_stale()` never runs, `--allow-uncalibrated` is
    never needed, and `--update-baseline` cannot hit the "untrusted rubric
    scores" refusal. It is also why the pack needs no `rubrics/`, no `anchors/`
    and no `calibration.json`, and why tier-3 makes zero model calls.
    """
    assert not any(c.type == "rubric" for p in pack.probes for c in p.checks)
    assert not (PACK / "rubrics").exists()
    assert not (PACK / "anchors").exists()
    assert not (PACK / "calibration.json").exists()


def test_pass_k_guarantee_survives_the_carve(pack):
    """`k = max(samples)` is pack-wide, so k stays 3 — as in the full pack.

    At k=1 `pass^k` collapses to `pass@1` and a guardrail that fails 1-in-3
    would show green two runs out of three.
    """
    assert max(p.samples for p in pack.probes) == 3


def test_allowlist_matches_twincore_exactly(pack):
    twincore = load_pack(str(TWINCORE))
    assert pack.spec.allowlist == twincore.spec.allowlist
    assert pack.spec.allowlist == ["http://localhost:8000", "http://127.0.0.1:8000"]


def test_pack_name_and_fingerprint_are_distinct_from_twincore(pack):
    """A distinct `name` keeps run artifacts and the baseline unambiguous; the
    fingerprint differs automatically because it hashes the raw on-disk bytes."""
    assert pack.spec.name == "twincore-injection"
    assert pack_fingerprint(pack) != pack_fingerprint(load_pack(str(TWINCORE)))


def test_target_yaml_differs_from_twincore_in_name_and_description_only():
    """Everything but `name:` and `description:` copies verbatim — including the
    allowlist, judge family, budget and concurrency."""
    ours = (PACK / "target.yaml").read_text().splitlines()
    theirs = (TWINCORE / "target.yaml").read_text().splitlines()
    assert len(ours) == len(theirs)
    differing = [t for o, t in zip(ours, theirs) if o != t]
    assert [line.split(":", 1)[0] for line in differing] == ["name", "description"]
