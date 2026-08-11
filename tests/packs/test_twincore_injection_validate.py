"""Shape pins for `packs/twincore-injection` — the demo carve-out.

`packs/twincore-injection` is a **derivative** pack: `probes/injection.yaml` is a
copy of the same file in `packs/twincore` that diverges only in its trial count,
and `target.yaml` differs from twincore's in exactly two human-readable fields
(`name`, `description`). Nothing was moved out of `packs/twincore` — it stays
intact, so every assertion in `test_twincore_validate.py` and every "50 probes"
claim in the READMEs stays true.

The price of copying is drift, and
`test_injection_yaml_matches_twincore_apart_from_the_declared_divergence` is what
pays it: the two files are pinned equal everywhere except the one deliberate
difference, which is itself pinned on both sides, so a future edit to TwinCore's
redirect constants can never update one copy and silently leave the other stale.

Paths here are absolute (`Path(__file__).parents[2]`) rather than the
repo-root-relative literals used by `test_twincore_validate.py`, which only pass
when pytest is invoked from the repo root (docs/JOURNAL.md:548).
"""

import re
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


_SAMPLES_LINE = re.compile(r"^(\s*)samples:\s*\d+\s*$")


def _canonical_injection_yaml(path: Path) -> str:
    """`injection.yaml` with the one declared divergence erased, nothing else.

    Every `samples:` line loses its value, and the run of whole-line comments
    directly above it is dropped (38d6d5e's rationale block lives there). Applied
    identically to both copies, so what survives is everything the two files are
    still required to agree on, byte for byte.
    """
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _SAMPLES_LINE.match(line)
        if match is None:
            out.append(line)
            continue
        while out and out[-1].lstrip().startswith("#"):
            out.pop()
        out.append(f"{match.group(1)}samples: <erased; pinned separately>")
    return "\n".join(out)


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


def test_injection_yaml_matches_twincore_apart_from_the_declared_divergence():
    """The anti-drift guard that makes copying (rather than moving) safe.

    `injection.yaml:11-12` says these probes are deliberately coupled to
    TwinCore's verbatim redirect constants and "must be updated" when those
    change. Two copies mean two places to update; this test turns a silent
    divergence into a red suite.

    The two files were byte-identical until 38d6d5e raised the demo pack's trial
    count (`samples: 3` -> `samples: 7`, plus the comment block explaining why).
    Twincore keeps k=3 on purpose — it carries all 50 probes and 350 sessions a
    run is not a cost anyone approved — so restoring byte-identity by editing
    twincore is off the table. Instead the divergence is made explicit: both
    files are compared through `_canonical_injection_yaml`, which erases *only*
    that one difference, and the two erased values are then pinned separately
    below so neither side can move unnoticed.

    What is still guarded: every prompt, every redirect constant, every probe id,
    check and field — an edit to any of them in one copy alone still reds this
    test. What the transformation gives up: the literal text of a `samples:`
    value and of whole-line comments *immediately above* a `samples:` line. Those
    are the only bytes it is blind to, and the pins below cover the values.
    """
    ours = _canonical_injection_yaml(PACK / "probes" / "injection.yaml")
    theirs = _canonical_injection_yaml(TWINCORE / "probes" / "injection.yaml")
    assert ours == theirs, (
        "packs/twincore-injection/probes/injection.yaml has drifted from "
        "packs/twincore/probes/injection.yaml outside the declared `samples:` "
        "divergence — the two copies must be updated together."
    )

    # The declared divergence itself, pinned on both sides. Changing either
    # pack's trial count is a deliberate act; it must be a deliberate edit here
    # too, and the failure names which side moved.
    assert max(p.samples for p in load_pack(str(PACK)).probes) == 7, (
        "twincore-injection's trial count moved; k is pack-wide (k = max(samples))"
    )
    assert max(p.samples for p in load_pack(str(TWINCORE)).probes) == 3, (
        "twincore's trial count moved; it is deliberately left at k=3 across all "
        "50 probes"
    )


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
    """The carve may raise k, never lower it below the full pack's.

    `k = max(samples)` is pack-wide. At k=1 `pass^k` collapses to `pass@1` and a
    guardrail that fails 1-in-3 would show green two runs out of three, so the
    real guarantee is "k > 1, and at least as strict as twincore's" — derived
    from the full pack (ruling R4-6), not a literal that goes stale the next time
    the demo's trial count moves (38d6d5e took it 3 -> 7).
    """
    carved_k = max(p.samples for p in pack.probes)
    full_k = max(p.samples for p in load_pack(str(TWINCORE)).probes)
    assert carved_k > 1, "k=1 collapses pass^k to pass@1"
    assert carved_k >= full_k, (
        f"the carve weakened pass^k: k={carved_k} vs the full pack's k={full_k}"
    )


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
