"""Compare mode: blind pairwise A/B judging over two gate artifacts (Plan #2b).

Compare consumes two `RunArtifact`s produced by `evalyn gate` — it makes NO
target HTTP calls. Per rubric-checked probe, trials are paired positionally
after per-side epoch sort (zipped; leftovers excluded and counted — the two
sides' epoch numbers need not match) and each pair is judged
blind with `judge_pair` (order-controlled draws, flip detection). Verdicts
tally per (pair x criterion) into the probe's category; hard metrics
(latency, invariant failures) come ONLY from `trial_records` and are never
blended with verdicts. Compare is advisory: no combined winner is computed.
"""

from __future__ import annotations

import asyncio
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from evalyn.engine.budget import BudgetExceeded, estimate_cost
from evalyn.engine.run import RunArtifact, atomic_write_artifact, pack_fingerprint
from evalyn.scoring.pairwise import judge_pair
from evalyn.scoring.rubrics import (
    load_rubric,
    load_rubric_context,
    load_rubric_steps,
)
from evalyn.targets.loader import Pack

_TALLY_KEY = {"A": "wins_a", "B": "wins_b", "tie": "ties", "unsure": "unsure"}


@dataclass
class CompareArtifact:
    pack_name: str
    pack_hash: str
    judge_model: str
    created_at: str
    label_a: str
    label_b: str
    source_a: str            # artifact file paths as given on the CLI
    source_b: str
    created_at_a: str
    created_at_b: str
    # category -> {"wins_a","wins_b","ties","unsure","flips",
    #              "criteria_judged","flip_rate"} — only categories with at
    # least one judged (pair x criterion) appear here.
    categories: dict
    # per probe: {"id","category","pairs_judged","excluded_trials",
    #   "rubrics": {rid: [per-pair {"epoch","epoch_b","verdicts","flipped",
    #                               "justifications"}]}} — pairs are
    # positional after per-side epoch sort; "epoch" is side A's, "epoch_b"
    # side B's (additive, PR #6).
    probes: list[dict]
    # category -> {"latency_mean_a","latency_mean_b","latency_p95_a",
    #   "latency_p95_b","invariant_failures_a","invariant_failures_b",
    #   "trials_a","trials_b"} — from trial_records ONLY, all trials both
    #   sides (None latencies excluded from mean/p95, trials still counted).
    hard_metrics: dict
    excluded_pairs: int
    judge_usd: float = 0.0
    rubric_scores_untrusted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CompareArtifact":
        try:
            return cls(**d)
        except TypeError as e:
            # unknown/missing fields (e.g. a future schema) must surface as a
            # clean ValueError, never a bare TypeError traceback — same
            # pattern as RunArtifact.from_dict.
            raise ValueError(
                "artifact fields do not match the CompareArtifact schema "
                f"({e}); this artifact does not match the current schema") from e


def _p95(vals: list[float]) -> float:
    """Locked p95: sorted(vals)[max(0, ceil(0.95*len(vals)) - 1)]."""
    return sorted(vals)[max(0, math.ceil(0.95 * len(vals)) - 1)]


def _sorted_records(art: RunArtifact, probe_id: str) -> list[dict]:
    for r in art.probes:
        if r.id == probe_id:
            return sorted(r.trial_records, key=lambda rec: rec["epoch"])
    return []


def _probe_rubric_ids(probe) -> list[str]:
    """Ordered, de-duplicated rubric ids of a probe's rubric checks."""
    seen: list[str] = []
    for c in probe.checks:
        if c.type == "rubric" and c.rubric and c.rubric not in seen:
            seen.append(c.rubric)
    return seen


def _check_preconditions(pack: Pack, art_a: RunArtifact, art_b: RunArtifact) -> None:
    """Locked preconditions — raise ValueError BEFORE any judge call."""
    fp = pack_fingerprint(pack)
    for side, art in (("A", art_a), ("B", art_b)):
        if art.pack_hash != fp:
            raise ValueError(
                f"artifact {side} pack hash {art.pack_hash[:12]} does not "
                f"match this pack's fingerprint {fp[:12]} — compare requires "
                f"both artifacts to come from the exact pack being compared")
    for side, art in (("A", art_a), ("B", art_b)):
        for probe in pack.probes:
            if not _probe_rubric_ids(probe):
                continue
            recs = _sorted_records(art, probe.id)
            if not recs:
                # a #2b artifact whose probe scored ZERO trials is a run
                # problem, not a schema-era problem (PR #6 message split)
                raise ValueError(
                    f"artifact {side} probe {probe.id!r} has no scored "
                    f"trials — the run produced no judgeable sessions for "
                    f"it; check the target and the run report")
            if any(not rec.get("transcript") for rec in recs):
                raise ValueError(
                    f"artifact {side} probe {probe.id!r} has no judgeable "
                    f"transcripts — artifact predates transcript capture — "
                    f"re-run `evalyn gate`")


def _hard_metrics(pack: Pack, art_a: RunArtifact, art_b: RunArtifact) -> dict:
    """Per-category latency/invariant metrics from trial_records ONLY."""
    per_cat: dict[str, dict] = {}
    for suffix, art in (("a", art_a), ("b", art_b)):
        for probe in pack.probes:
            m = per_cat.setdefault(probe.category, {
                "lat_a": [], "lat_b": [], "inv_a": 0, "inv_b": 0,
                "trials_a": 0, "trials_b": 0})
            for rec in _sorted_records(art, probe.id):
                m[f"trials_{suffix}"] += 1
                m[f"inv_{suffix}"] += rec.get("invariant_failures") or 0
                secs = rec.get("session_seconds")
                if secs is not None:  # None latency excluded, trial counted
                    m[f"lat_{suffix}"].append(secs)
    out: dict[str, dict] = {}
    for cat, m in per_cat.items():
        entry: dict = {}
        for suffix in ("a", "b"):
            vals = m[f"lat_{suffix}"]
            entry[f"latency_mean_{suffix}"] = (
                sum(vals) / len(vals) if vals else None)
            entry[f"latency_p95_{suffix}"] = _p95(vals) if vals else None
            entry[f"invariant_failures_{suffix}"] = m[f"inv_{suffix}"]
            entry[f"trials_{suffix}"] = m[f"trials_{suffix}"]
        out[cat] = entry
    return out


async def run_compare(pack: Pack, art_a: RunArtifact, art_b: RunArtifact,
                      judge_model: str, *, cache_dir: Path | None = None,
                      rubric_scores_untrusted: bool = False,
                      seed: int | None = None,
                      max_concurrency: int = 4,
                      out_dir: str = "runs",
                      label_a: str = "A", label_b: str = "B",
                      source_a: str = "", source_b: str = "",
                      run_id: str | None = None) -> CompareArtifact:
    if max_concurrency < 1:
        raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency}")
    _check_preconditions(pack, art_a, art_b)

    # Rubric materials loaded ONCE per rubric id; frozen steps and fact sheets
    # thread through to judge_pair as-is (USER RULING 2026-08-03: a committed
    # rubrics/<rid>.steps.json IS the grading steps; None lets judge_pair
    # generate via its own cache seam).
    rids = sorted({rid for p in pack.probes for rid in _probe_rubric_ids(p)})
    rubrics = {rid: load_rubric(pack, rid) for rid in rids}
    contexts = {rid: load_rubric_context(pack, rid) for rid in rids}
    frozen = {rid: load_rubric_steps(pack, rid) for rid in rids}

    # Bound judge concurrency (house Semaphore pattern, calibrate.py). Each
    # judge call gets its own child rng derived deterministically from the
    # master at SCHEDULING time, so concurrent interleaving cannot perturb
    # the seeded draw-2 order sequence.
    sem = asyncio.Semaphore(max_concurrency)
    master = random.Random(seed)

    async def _judge(rid: str, ta: str, tb: str, rng: random.Random):
        async with sem:
            text, rhash = rubrics[rid]
            return await judge_pair(text, rhash, ta, tb, judge_model,
                                    cache_dir=cache_dir, context=contexts[rid],
                                    steps=frozen[rid], rng=rng)

    # Build the per-probe pairing plan, then judge every (pair x rubric).
    probe_entries: list[dict] = []
    # (probe_entry, rid, epoch_a, epoch_b)
    jobs: list[tuple[dict, str, int, int]] = []
    coros = []
    excluded_pairs = 0
    for probe in pack.probes:
        probe_rids = _probe_rubric_ids(probe)
        recs_a = _sorted_records(art_a, probe.id)
        recs_b = _sorted_records(art_b, probe.id)
        entry: dict = {"id": probe.id, "category": probe.category,
                       "pairs_judged": 0, "excluded_trials": 0, "rubrics": {}}
        if probe_rids:
            pairs = list(zip(recs_a, recs_b))
            excluded = len(recs_a) + len(recs_b) - 2 * len(pairs)
            entry["pairs_judged"] = len(pairs)
            entry["excluded_trials"] = excluded
            excluded_pairs += excluded
            for rid in probe_rids:
                entry["rubrics"][rid] = []
                for rec_a, rec_b in pairs:
                    jobs.append((entry, rid, rec_a["epoch"], rec_b["epoch"]))
                    coros.append(_judge(rid, rec_a["transcript"],
                                        rec_b["transcript"],
                                        random.Random(master.random())))
        probe_entries.append(entry)

    verdicts = await asyncio.gather(*coros)

    categories: dict[str, dict] = {}
    usage_acc: dict[str, dict[str, int]] = {}
    for (entry, rid, epoch, epoch_b), pv in zip(jobs, verdicts):
        entry["rubrics"][rid].append({
            "epoch": epoch,        # side A's epoch (kept for shape compat)
            "epoch_b": epoch_b,    # side B's epoch (additive, PR #6)
            "verdicts": dict(pv.verdicts),
            "flipped": dict(pv.flipped),
            "justifications": dict(pv.justifications),
        })
        cat = categories.setdefault(entry["category"], {
            "wins_a": 0, "wins_b": 0, "ties": 0, "unsure": 0, "flips": 0,
            "criteria_judged": 0, "flip_rate": 0.0})
        # one tally per (pair x criterion) — unsure counts in the denominator
        for crit, v in pv.verdicts.items():
            cat["criteria_judged"] += 1
            cat[_TALLY_KEY.get(v, "unsure")] += 1
            if pv.flipped.get(crit):
                cat["flips"] += 1
        for model_id, u in pv.usage.items():
            acc = usage_acc.setdefault(model_id,
                                       {"input_tokens": 0, "output_tokens": 0})
            acc["input_tokens"] += u.get("input_tokens", 0) or 0
            acc["output_tokens"] += u.get("output_tokens", 0) or 0
    for cat in categories.values():
        cat["flip_rate"] = (cat["flips"] / cat["criteria_judged"]
                            if cat["criteria_judged"] else 0.0)

    # Metering-shape gotcha: estimate_cost reads .input_tokens/.output_tokens
    # ATTRIBUTES while PairVerdict.usage carries plain dicts — a raw dict
    # would silently meter $0.00.
    judge_usd = estimate_cost(
        {m: SimpleNamespace(**u) for m, u in usage_acc.items()})

    art = CompareArtifact(
        pack_name=pack.spec.name,
        pack_hash=pack_fingerprint(pack),
        judge_model=judge_model,
        created_at=datetime.now(timezone.utc).isoformat(),
        label_a=label_a, label_b=label_b,
        source_a=source_a, source_b=source_b,
        created_at_a=art_a.created_at,
        created_at_b=art_b.created_at,
        categories=categories,
        probes=probe_entries,
        hard_metrics=_hard_metrics(pack, art_a, art_b),
        excluded_pairs=excluded_pairs,
        judge_usd=judge_usd,
        rubric_scores_untrusted=rubric_scores_untrusted,
    )

    # Post-hoc budget gate, house write-before-raise: the artifact is written
    # FIRST (to the caller's out_dir, with the real labels/sources) so the
    # metered evidence survives a breach for inspection.
    cap = pack.spec.budget.max_usd_per_run
    if cap and judge_usd > cap:
        # The breach artifact carries the SAME run_id the caller asked for: a
        # cockpit-launched compare that busts its cap must still land at the
        # path the server is watching, or the run reads as vanished.
        write_compare_artifact(art, out_dir=out_dir, run_id=run_id)
        raise BudgetExceeded(
            f"judge spend ${judge_usd:.4f} exceeded max_usd_per_run "
            f"${cap:.2f} (compare artifact written)")
    return art


def write_compare_artifact(art: CompareArtifact, out_dir: str = "runs",
                           *, run_id: str | None = None) -> Path:
    """Atomic temp-then-rename write with a collision-proof name — the shared
    house writer (R8-13), suffixed `-compare`.

    `run_id=None` mints exactly as before; a caller that passes one (the CLI,
    from `EVALYN_RUN_ID`) gets `runs/<run_id>-compare.json`."""
    return atomic_write_artifact(art.to_dict(), art.pack_name, out_dir,
                                 suffix="-compare", run_id=run_id)


def _fmt(val: float | None, suffix: str = "") -> str:
    return "-" if val is None else f"{val:.2f}{suffix}"


def render_compare_report(art: CompareArtifact) -> str:
    a, b = art.label_a, art.label_b
    lines = [f"# Evalyn compare — {art.pack_name}: {a} vs {b}", ""]
    if art.rubric_scores_untrusted:
        lines.append("**WARNING: rubric scores UNTRUSTED** — this compare "
                     "bypassed a missing/stale judge calibration "
                     "(`--allow-uncalibrated`); pairwise verdicts below are "
                     "untrusted until `evalyn calibrate` passes.")
        lines.append("")
    lines.append("## Pairwise verdicts")
    lines.append("")
    lines.append(f"| category | {a} wins | {b} wins | ties | unsure | flip rate |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for cat in sorted(art.categories):
        c = art.categories[cat]
        lines.append(f"| {cat} | {c['wins_a']} | {c['wins_b']} | {c['ties']} "
                     f"| {c['unsure']} | {c['flip_rate']:.2f} |")
    if not art.categories:
        lines.append("| (no rubric-checked probes judged) | - | - | - | - | - |")
    lines.append("")
    lines.append("## Hard metrics")
    lines.append("")
    lines.append(f"| category | latency mean {a}/{b} | latency p95 {a}/{b} "
                 f"| invariant failures {a}/{b} |")
    lines.append("| --- | --- | --- | --- |")
    for cat in sorted(art.hard_metrics):
        m = art.hard_metrics[cat]
        lines.append(
            f"| {cat} "
            f"| {_fmt(m['latency_mean_a'], 's')}/{_fmt(m['latency_mean_b'], 's')} "
            f"| {_fmt(m['latency_p95_a'], 's')}/{_fmt(m['latency_p95_b'], 's')} "
            f"| {m['invariant_failures_a']}/{m['invariant_failures_b']} |")
    lines.append("")
    total_pairs = sum(p["pairs_judged"] for p in art.probes)
    lines.append(f"Totals: {total_pairs} pair(s) judged, {art.excluded_pairs} "
                 f"trial(s) excluded, judge spend ${art.judge_usd:.4f}.")
    lines.append("")
    lines.append("compare is advisory: verdicts and hard metrics are reported "
                 "side by side — no combined winner is computed.")
    return "\n".join(lines)
