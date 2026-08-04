"""Judge JSON key -> rubric criterion resolution, shared by tier3._parse and
pairwise._parse_pair (promoted from tier3 in the PR #6 review round so both
parsers bind keys identically — no cross-module private import).

History: 2026-07-30 calibrate failure (LLM-generated grading steps renamed the
rubric headings and every draw keyed by the steps' names went unparseable)
introduced tolerant fail-closed matching; the 2026-08-04 ruling added
exact-beats-prefix binding (see bind_judge_keys).
"""

from __future__ import annotations


def _norm_key(s: str) -> str:
    """Deterministic key normalization: collapse whitespace, casefold."""
    return " ".join(s.split()).casefold()


def match_criterion(key: str, criteria: list[str]) -> tuple[str, bool] | None:
    """Fail-closed resolution of a judge JSON key to a rubric criterion.

    A key counts only when it (i) normalizes equal (case/whitespace) to
    exactly one criterion, or (ii) is a unique normalized prefix/superset of
    exactly one criterion ("Specificity" -> "Specificity without overreach").
    Returns ``(criterion, is_exact)`` — is_exact True only for case (i) — or
    None for zero/ambiguous matches (not counted). Deterministic rules only,
    never fuzzy string distance.
    """
    nk = _norm_key(key)
    if not nk:
        return None  # "" is trivially a prefix of everything — never counts
    exact = [c for c in criteria if _norm_key(c) == nk]
    if exact:
        return (exact[0], True) if len(exact) == 1 else None
    partial = [c for c in criteria
               if _norm_key(c).startswith(nk) or nk.startswith(_norm_key(c))]
    return (partial[0], False) if len(partial) == 1 else None


def bind_judge_keys(entries: dict, criteria: list[str]) -> tuple[dict, set[str]]:
    """Bind a judge reply's JSON entries to canonical criterion names.

    Exact-normalizing keys OUTRANK prefix/superset keys (2026-08-04 ruling,
    reversing the earlier any-two-keys collision): a criterion with exactly
    one exact key binds to it and any stray prefix-only keys for it are
    ignored. A collision — the criterion lands in the returned ``collided``
    set, fail-closed — remains only between keys of equal quality: two keys
    both normalizing equal to one criterion, or two+ prefix-only keys with no
    exact key.

    Returns ``(matched, collided)``: matched maps canonical criterion name ->
    the winning entry; collided names stay out of matched.
    """
    exact: dict[str, list] = {}
    prefix: dict[str, list] = {}
    for key, entry in entries.items():
        m = match_criterion(str(key), criteria)
        if m is None:
            continue  # zero/ambiguous match: not counted
        crit, is_exact = m
        (exact if is_exact else prefix).setdefault(crit, []).append(entry)
    matched: dict = {}
    collided: set[str] = set()
    for crit in set(exact) | set(prefix):
        candidates = exact.get(crit) or prefix.get(crit)
        if len(candidates) == 1:
            matched[crit] = candidates[0]
        else:
            collided.add(crit)
    return matched, collided
