"""Dedup — is this finding one we already have? Advisory, never a filter.

`discover` re-runs, and the same weakness surfaces down several paths. Without
a flag a pack silts up with five spellings of one bug; with a *suppressor* it
would silently discard genuine findings. So: `scan_duplicates` returns a
`DuplicateFlag` and the caller stages the probe **anyway**, recording the flag
in the **run artifact** (`Finding.duplicate_of` / `duplicate_reason`). Not in
the staged YAML header: the header is rendered before dedup is consulted, and
the artifact is where a human reads the verdict anyway. A human decides.

The comparison is a **conjunction of all three** criteria (spec §7) — same
category, a shared required-check signature, AND turn-set Jaccard >= 0.6 —
precisely because a false positive is the expensive error here. Two findings
that share a path but assert different violation classes are different
findings, and vice versa.

Deterministic and stdlib-only: lowercase, collapse whitespace, compare sets. No
embeddings, no model call, no network — this runs on every confirmed finding,
and it must be free, offline, and reproducible from the artifact alone.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from evalyn.targets.schema import Check, Probe

#: Fraction of the union of normalized turns two findings must share. 0.6 keeps
#: "the same conversation plus one extra turn" together while separating two
#: hunts that merely opened the same way.
JACCARD_THRESHOLD = 0.6


@dataclass(frozen=True)
class DuplicateFlag:
    """`candidate` looks like `probe_id` — advice, recorded, never enforced."""

    probe_id: str
    reason: str
    score: float


def _normalized_turns(probe: Probe) -> frozenset[str]:
    return frozenset(" ".join(t.lower().split()) for t in probe.turns)


def _signature(check: Check) -> tuple[str, str]:
    """`(type, ref|value|rubric)` — what the check asserts, not how it reads."""
    return check.type, (check.ref or check.value or check.rubric or "")


def _required_signatures(probe: Probe) -> frozenset[tuple[str, str]]:
    """Only *required* checks identify a finding: a non-required check weighs
    the trial score, it does not say what the violation was."""
    return frozenset(_signature(c) for c in probe.checks if c.required)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0          # no turns, no evidence of overlap — and no ZeroDivision
    return len(left & right) / len(union)


def scan_duplicates(candidate: Probe,
                    existing: Sequence[Probe]) -> DuplicateFlag | None:
    """The best duplicate match for `candidate`, or None.

    Highest Jaccard wins; ties break on the lowest probe id, so the flag does
    not depend on the order `existing` happened to be read in. A rediscovery of
    the exact same finding (same content-addressed id) scores 1.0 and is
    flagged like any other — that is the strongest duplicate there is.
    """
    candidate_turns = _normalized_turns(candidate)
    candidate_sigs = _required_signatures(candidate)

    matches: list[tuple[float, str, str]] = []
    for other in existing:
        if other.category != candidate.category:
            continue
        shared = candidate_sigs & _required_signatures(other)
        if not shared:
            continue
        score = _jaccard(candidate_turns, _normalized_turns(other))
        if score < JACCARD_THRESHOLD:
            continue
        checks = ", ".join(f"{t}:{v}" for t, v in sorted(shared))
        matches.append((score, other.id, (
            f"same category {candidate.category!r}, shared required check(s) "
            f"[{checks}], and {score:.2f} turn overlap "
            f"(>= {JACCARD_THRESHOLD}) with {other.id!r}")))
    if not matches:
        return None
    score, probe_id, reason = min(matches, key=lambda m: (-m[0], m[1]))
    return DuplicateFlag(probe_id=probe_id, reason=reason, score=score)
