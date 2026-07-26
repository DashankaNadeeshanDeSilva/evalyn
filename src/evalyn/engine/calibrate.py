"""Judge calibration harness (Task 5).

Scores committed anchor transcripts (human-labeled 1-5 per rubric criterion)
with the tier-3 rubric judge and measures +/-1 agreement. The committed
``calibration.json`` record is what lets the gate trust rubric scores: the
gate fails closed (setup error) when the record is missing or stale.

Human labels only: nothing here generates or overwrites anchor label values.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from evalyn.scoring.rubrics import grading_steps, load_rubric, parse_criteria
from evalyn.scoring.tier3 import score_transcript
from evalyn.targets.loader import Pack, PackError

RECORD_NAME = "calibration.json"
AGREEMENT_THRESHOLD = 0.85


@dataclass
class Anchor:
    id: str
    rubric: str
    transcript: str
    scores: dict[str, int]      # human 1-5 labels per criterion (never generated)


@dataclass
class CalibrationResult:
    overall: float                       # fraction of (anchor x criterion) pairs within +/-1
    per_criterion: dict[str, float]      # keyed "<rubric>:<criterion>"
    anchors: int                         # anchors actually scored
    skipped: list[str] = field(default_factory=list)   # anchor ids without usable labels
    unsure: list[str] = field(default_factory=list)    # judge-unsure anchors (counted as misses)
    # human labels whose criterion name matches no rubric criterion, per anchor
    # id — reported (never silently dropped from the agreement denominator)
    unmatched: dict[str, list[str]] = field(default_factory=dict)


def load_anchors(pack: Pack) -> list[Anchor]:
    d = Path(pack.root) / "anchors"
    out: list[Anchor] = []
    if not d.exists():
        return out
    for f in sorted(d.glob("*.yaml")):
        obj = yaml.safe_load(f.read_text()) or {}
        scores = obj.get("scores") or {}
        if not isinstance(scores, dict):
            raise PackError(
                f"anchor {f.name}: `scores` must be a mapping of criterion -> "
                f"integer 1-5, got {type(scores).__name__} ({scores!r})")
        try:
            out.append(Anchor(id=obj.get("id", f.stem), rubric=obj["rubric"],
                              transcript=obj["transcript"], scores=dict(scores)))
        except KeyError as e:
            # missing/empty human labels are NOT an error here — such anchors
            # load with {} labels and are reported as skipped downstream
            raise PackError(
                f"anchor {f.name}: missing required key {e.args[0]!r} "
                f"(anchors need `rubric` and `transcript`)") from e
    return out


def _within_one(judge: int, human: int) -> bool:
    return abs(int(judge) - int(human)) <= 1


def _valid_labels(scores: dict) -> bool:
    return bool(scores) and all(
        isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5
        for v in scores.values())


async def run_calibration(pack: Pack, judge_model: str,
                          cache_dir: str | Path | None, k: int = 3, *,
                          max_concurrency: int = 4) -> CalibrationResult:
    if max_concurrency < 1:
        raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency}")
    anchors = load_anchors(pack)
    skipped = [a.id for a in anchors if not _valid_labels(a.scores)]
    usable = [a for a in anchors if _valid_labels(a.scores)]
    cache = Path(cache_dir) if cache_dir is not None else None
    rubrics = {rid: load_rubric(pack, rid) for rid in sorted({a.rubric for a in usable})}
    # Pre-warm the grading-steps cache once per rubric BEFORE concurrent scoring
    # so first-time samples cannot race to divergent steps within one run.
    for text, rhash in rubrics.values():
        await grading_steps(text, rhash, judge_model, cache)
    # Bound judge concurrency: at most max_concurrency anchors in flight at
    # once (an unbounded burst risks rate-limit failures against a live API).
    sem = asyncio.Semaphore(max_concurrency)

    async def _score(a: Anchor):
        async with sem:
            return await score_transcript(rubrics[a.rubric][0], rubrics[a.rubric][1],
                                          a.transcript, judge_model, k=k,
                                          cache_dir=cache)

    results = await asyncio.gather(*[_score(a) for a in usable])

    hits: dict[str, int] = {}
    totals: dict[str, int] = {}
    unsure_ids: list[str] = []
    unmatched: dict[str, list[str]] = {}
    for anchor, res in zip(usable, results):
        criteria = parse_criteria(rubrics[anchor.rubric][0])
        missing = [c for c in anchor.scores if c not in criteria]
        if missing:
            unmatched[anchor.id] = missing  # reported, never silently dropped
        judged = res.medians if res.medians is not None else {}
        if res.unsure:
            unsure_ids.append(anchor.id)
        for crit, human in anchor.scores.items():
            if crit not in criteria:
                continue
            # fail closed: an undecidable judge is a miss on every matched pair
            within = False if res.unsure else _within_one(judged[crit], human)
            key = f"{anchor.rubric}:{crit}"
            totals[key] = totals.get(key, 0) + 1
            hits[key] = hits.get(key, 0) + (1 if within else 0)

    per_criterion = {key: hits[key] / totals[key] for key in sorted(totals)}
    overall = sum(hits.values()) / sum(totals.values()) if totals else 0.0
    return CalibrationResult(overall=overall, per_criterion=per_criterion,
                             anchors=len(usable), skipped=skipped, unsure=unsure_ids,
                             unmatched=unmatched)


def _record_path(pack: Pack) -> Path:
    return Path(pack.root) / RECORD_NAME


def _pack_rubric_ids(pack: Pack) -> set[str]:
    return {c.rubric for p in pack.probes for c in p.checks
            if c.type == "rubric" and c.rubric}


def load_record(pack: Pack) -> dict | None:
    p = _record_path(pack)
    return json.loads(p.read_text()) if p.exists() else None


def _rubrics_with_scored_pairs(per_criterion: dict) -> set[str]:
    # per_criterion is keyed "<rubric>:<criterion>" (run_calibration contract)
    return {key.split(":", 1)[0] for key in per_criterion}


def per_rubric_agreement(per_criterion: dict) -> dict[str, float]:
    """Each rubric's agreement: the mean of its per-criterion values — exact
    pooled agreement as long as every criterion scored the same number of
    anchor pairs, which run_calibration guarantees when every usable anchor
    labels all of its rubric's criteria (one pair per anchor per matched
    criterion). Shared by is_stale and the calibrate CLI verdict so the two
    can never disagree (PR #4 fix #4)."""
    by_rubric: dict[str, list[float]] = {}
    for key, val in per_criterion.items():
        by_rubric.setdefault(key.split(":", 1)[0], []).append(val)
    return {rid: sum(vs) / len(vs) for rid, vs in sorted(by_rubric.items())}


def write_record(pack: Pack, overall: float, per_criterion: dict,
                 judge_model: str) -> Path:
    # Bless ONLY rubrics that actually had scored (anchor x criterion) pairs
    # (PR #4 fix #3): recording a hash for a rubric that was never calibrated
    # would make is_stale call it covered — zero-anchor rubrics must stay
    # uncovered so the gate refuses them.
    rubric_ids = sorted(_rubrics_with_scored_pairs(per_criterion))
    hashes = {rid: load_rubric(pack, rid)[1] for rid in rubric_ids}
    rec = {"judge_model": judge_model, "rubric_hashes": hashes, "agreement": overall,
           "per_criterion": per_criterion,
           "created_at": datetime.now(timezone.utc).isoformat()}
    p = _record_path(pack)
    p.write_text(json.dumps(rec, indent=2))
    return p


def is_stale(pack: Pack, judge_model: str) -> tuple[bool, str]:
    """Locked staleness rule: stale if the record is missing, the judge model
    differs, ANY rubric referenced by the pack's rubric checks has no anchor
    coverage / changed / is missing, the recorded OVERALL agreement is below
    threshold, or ANY pack rubric's OWN agreement is below threshold (per-rubric
    fail-closed, PR #4 fix #4 — a strong overall mean must never hide a weak
    rubric; a failing calibrate run must never leave a record the gate accepts)."""
    rec = load_record(pack)
    if rec is None:
        return True, "no calibration record"
    if rec.get("judge_model") != judge_model:
        return True, f"judge model changed ({rec.get('judge_model')} -> {judge_model})"
    recorded = rec.get("rubric_hashes", {})
    pack_rubrics = sorted(_pack_rubric_ids(pack))
    for rid in pack_rubrics:
        if rid not in recorded:
            return True, (f"no anchor coverage for rubric {rid!r} "
                          f"(never calibrated against human labels)")
        try:
            current = load_rubric(pack, rid)[1]
        except FileNotFoundError:
            return True, f"rubric {rid!r} missing"
        if current != recorded[rid]:
            return True, f"rubric {rid!r} changed since calibration"
    if rec.get("agreement", 0.0) < AGREEMENT_THRESHOLD:
        return True, (f"recorded agreement {rec.get('agreement', 0.0):.0%} is below "
                      f"the {AGREEMENT_THRESHOLD:.0%} threshold")
    # Per-rubric agreement, derived from the existing per_criterion record
    # field (no schema change — see per_rubric_agreement for the pooling
    # guarantee).
    by_rubric = per_rubric_agreement(rec.get("per_criterion") or {})
    weak: list[str] = []
    for rid in pack_rubrics:
        if rid not in by_rubric:
            return True, (f"no anchor coverage for rubric {rid!r} "
                          f"(record has no per-criterion agreement for it)")
        if by_rubric[rid] < AGREEMENT_THRESHOLD:
            weak.append(f"{rid!r} at {by_rubric[rid]:.0%}")
    if weak:
        return True, (f"per-rubric agreement below the {AGREEMENT_THRESHOLD:.0%} "
                      f"threshold for {', '.join(weak)}")
    return False, "calibrated"
