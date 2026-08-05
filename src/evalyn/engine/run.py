from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
import warnings
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from evalyn.engine.budget import BudgetExceeded, estimate_cost
from evalyn.engine.task_builder import build_task
from evalyn.scoring.checks import aggregate_trial
from evalyn.targets.loader import Pack


@dataclass
class ProbeResult:
    id: str
    category: str
    kind: str
    safety_critical: bool
    samples: int              # declared in the pack (actual trials may differ — A1)
    trials: int = 0           # trials actually collected (epochs with checks)
    expected_trials: int = 0  # pack-wide epoch count k the task RAN for every
    #                           probe (round-2 N1): the gate fails any probe
    #                           whose trials < expected_trials as INCOMPLETE so
    #                           errored epochs can't shrink the pass^k
    #                           denominator. 0 = unknown (pre-round-2 artifact:
    #                           the field is absent and the dataclass default
    #                           applies) — the gate then skips the
    #                           incompleteness check (only trials == 0 MISSING
    #                           applies), keeping old baselines loadable.
    pass_at_k: float = 0.0    # any trial's required checks all passed
    pass_k: float = 0.0       # EVERY trial's required checks passed (safety gate)
    mean_score: float = 0.0   # mean weighted trial_score over trials WITH score
    #                           signal (no-signal trials are excluded, 0.0 if none)
    unsure_trials: int = 0    # NOANSWER accounting: required-unsure or no-signal
    #                           (all non-required unsure) trials, not failures
    checks: list[dict] = field(default_factory=list)  # representative CheckResults
    # Per-trial evidence, one dict per SCORED epoch (same rule as `trials`),
    # sorted by epoch: {"epoch": int, "transcript": str,
    # "session_seconds": float | None, "invariant_failures": int}. The
    # transcript is the judged one (labeled_transcript format: "User: …\n
    # Assistant: …" — identical to what Tier-2/3 saw); session_seconds is the
    # target session wall-clock the solver stored — concurrency-gate queue wait
    # excluded (None on pre-#2b logs);
    # invariant_failures counts FAILED `invariant:<id>` checks. Additive
    # (#2b Task 6): old artifacts/baselines load with [] — this is the compare
    # mode's pairing input (Task 8).
    trial_records: list[dict] = field(default_factory=list)


@dataclass
class RunArtifact:
    pack_name: str
    pack_hash: str
    judge_model: str
    created_at: str
    probes: list[ProbeResult]
    log_path: str
    # True when the run was allowed past a missing/stale judge calibration via
    # --allow-uncalibrated: rubric-check scores in this artifact are untrusted.
    rubric_scores_untrusted: bool = False
    # Estimated USD spent on Evalyn's OWN judge models (Tier-2/3 LLM calls;
    # target-side HTTP spend is never counted). Metered POST-HOC after the eval
    # returns — a run can overshoot `budget.max_usd_per_run`; the cap bounds
    # what a run may have spent before its results are trusted, and a breach
    # raises BudgetExceeded AFTER this artifact is written.
    judge_usd: float = 0.0
    # NOANSWER accounting: total trials (across all probes) whose required
    # checks came back unsure — judge-infra failures, distinct from product
    # failures. Sum of per-probe `unsure_trials`.
    total_unsure_trials: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunArtifact":
        try:
            probe_dicts = d["probes"]
        except (TypeError, KeyError) as e:
            # a missing `probes` key must be the same clean ValueError as any
            # other schema mismatch, never a bare KeyError traceback (round-2 N7)
            raise ValueError(
                "artifact has no 'probes' list; this artifact does not match "
                "the Plan #2a RunArtifact schema") from e
        try:
            probes = [ProbeResult(**p) for p in probe_dicts]
        except TypeError as e:
            raise ValueError(
                "artifact probe entries do not match the Plan #2a ProbeResult "
                f"schema ({e}); this artifact predates the current schema") from e
        try:
            return cls(**{**d, "probes": probes})
        except TypeError as e:
            # unknown TOP-LEVEL keys (e.g. a future schema) must surface as the
            # same clean ValueError the probe loop raises — never a bare
            # TypeError that leaks past load_baseline as a traceback (fix #9)
            raise ValueError(
                "artifact fields do not match the Plan #2a RunArtifact schema "
                f"({e}); this artifact does not match the current schema") from e


def pack_fingerprint(pack: Pack) -> str:
    """SHA-256 over the RAW pack file bytes (target.yaml + probes + rubrics).

    Hashing raw bytes — not a re-serialization of the resolved spec — keeps the
    fingerprint independent of ${ENV} resolution (e.g. base_url localhost vs
    127.0.0.1), so the same pack files always fingerprint identically.
    """
    h = hashlib.sha256()
    for name in sorted(getattr(pack, "raw_files", {})):
        h.update(name.encode())
        h.update(b"\0")
        h.update(pack.raw_files[name])
    return h.hexdigest()


def _sample_transcript(sample) -> str:
    """The judged transcript, rebuilt from the log sample's messages.

    Same format as scoring/transcript.py's labeled_transcript (the text
    Tier-2/3 judged) — by role name here because log messages are re-parsed
    ChatMessage variants, not the solver's original instances.
    """
    blocks = []
    for m in sample.messages or []:
        role = getattr(m, "role", "")
        if role == "user":
            blocks.append(f"User: {m.text}")
        elif role == "assistant":
            blocks.append(f"Assistant: {m.text}")
    return "\n".join(blocks)


def reduce_log_to_probes(log, pack: Pack) -> list[ProbeResult]:
    by_id = {p.id: p for p in pack.probes}
    # Group CheckResults per (probe_id, epoch) across ALL scorers present in the
    # log (tier3 lands later — never hardcode a scorer list). The authority is
    # each Score's metadata["checks"], never Score.value. An epoch that produced
    # no checks in ANY scorer (errored trial) is NOT counted as a trial, so a
    # fully-errored probe keeps trials == 0 and the gate hard-fails it as
    # MISSING — never a silent pass (fail-closed, Plan #1 rule).
    trials: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    # Per-sample evidence for trial_records: the judged transcript plus the
    # session wall-clock the solver put in the sample store. Captured for every
    # sample; only SCORED epochs (present in `trials`) ever emit a record.
    sample_info: dict[tuple[str, int], tuple[str, float | None]] = {}
    for sample in log.samples or []:
        pid = sample.metadata["id"] if sample.metadata else sample.id
        for sc in (sample.scores or {}).values():
            checks = (sc.metadata or {}).get("checks") or []
            if checks:
                trials[pid][sample.epoch].extend(checks)
        sample_info[(pid, sample.epoch)] = (
            _sample_transcript(sample),
            (sample.store or {}).get("evalyn:session_seconds"))

    # The task runs EVERY probe at the pack-wide max(samples) (task_builder's
    # Epochs(k)) — record that expectation so the gate can fail probes whose
    # scored trials fell short (errored epochs, round-2 N1).
    expected = max((p.samples for p in by_id.values()), default=1)

    results: list[ProbeResult] = []
    for pid, probe in by_id.items():
        # Amendment A1: stats reflect the ACTUAL number of trials collected (the
        # task runs every probe at the pack-wide max), not declared `samples`.
        per_epoch = trials.get(pid, {})
        n = len(per_epoch)
        req_passes: list[bool] = []
        unsure_ct = 0
        scores: list[float] = []
        trial_records: list[dict] = []
        for epoch in sorted(per_epoch):
            crs = per_epoch[epoch]
            req_pass, trial_unsure, trial_score = aggregate_trial(crs)
            req_passes.append(req_pass)
            unsure_ct += 1 if trial_unsure else 0
            # trial_score None = no score signal (ALL non-required checks came
            # back unsure): the trial counts toward trials/unsure_trials but is
            # EXCLUDED from mean_score — averaging in a fabricated value would
            # fail open (PR #4 fix #1).
            if trial_score is not None:
                scores.append(trial_score)
            transcript, session_seconds = sample_info.get((pid, epoch), ("", None))
            trial_records.append({
                "epoch": epoch,
                "transcript": transcript,
                "session_seconds": session_seconds,
                "invariant_failures": sum(
                    1 for c in crs
                    if str(c.get("check", "")).startswith("invariant:")
                    and c.get("passed") is False),
            })
        pass_at_k = 1.0 if any(req_passes) else 0.0
        pass_k = 1.0 if (n > 0 and all(req_passes)) else 0.0
        # no trial produced a usable score -> 0.0 (fail-closed), surfaced via
        # unsure_trials, never a silent perfect mean
        mean_score = sum(scores) / len(scores) if scores else 0.0
        # carry one epoch's checks as representative evidence for the report
        rep_checks = next(iter(per_epoch.values())) if per_epoch else []
        results.append(ProbeResult(
            id=pid, category=probe.category, kind=probe.kind,
            safety_critical=probe.safety_critical, samples=probe.samples,
            trials=n, expected_trials=expected, pass_at_k=pass_at_k,
            pass_k=pass_k, mean_score=mean_score,
            unsure_trials=unsure_ct, checks=rep_checks,
            trial_records=trial_records))
    return results


#: Pre-Plan-#3 private name. The reducer went public when `discover`'s
#: replay-once began reusing it (spec §7: replay runs the gate's OWN machinery,
#: it does not re-derive a verdict), and the alias keeps every earlier caller
#: and test importing the private name working unchanged.
_reduce_log_to_probes = reduce_log_to_probes


def _judge_usd(log) -> float:
    """Judge spend for THIS eval, read from the returned eval log.

    Never the process-global model_usage() ContextVar: that value is set inside
    Inspect's eval event-loop context and does not propagate here (it returned
    {} on every real run — live-confirmed 2026-07-28), and it accumulates
    across evals in one process (would double-count compare's second eval).
    """
    try:
        return estimate_cost(log.stats.model_usage)
    except Exception as e:
        # Fail-open by design (brief): metering failure must not kill the run.
        # But be LOUD about it — a silent 0.0 would quietly disable the cap.
        warnings.warn(
            f"judge-spend metering unavailable — budget cap not enforced "
            f"this run ({type(e).__name__}: {e})", RuntimeWarning, stacklevel=2)
        return 0.0


def run_gate(pack: Pack, judge_model: str = "mockllm/model",
             log_dir: str = "runs/logs", rubric_judge_model: str | None = None,
             rubric_scores_untrusted: bool = False,
             out_dir: str = "runs",
             cache_dir: str | Path | None = None) -> RunArtifact:
    # Grading-steps cache for the tier-3 judge. Defaults to the pack's .cache
    # dir — the SAME location `evalyn calibrate` caches under — so gate trials
    # are judged with the steps calibration validated, instead of regenerating
    # G-Eval steps per judge call (extra spend, uncalibrated steps).
    steps_cache = Path(cache_dir) if cache_dir is not None else Path(pack.root) / ".cache"
    task = build_task(pack, judge_model=judge_model,
                      rubric_judge_model=rubric_judge_model,
                      cache_dir=steps_cache)
    logs = inspect_eval(task, model="mockllm/model", log_dir=log_dir, display="none")
    log = logs[0]
    if log.status != "success":
        raise RuntimeError(f"inspect eval did not succeed: status {log.status!r}")
    if log.samples is None and log.location:
        log = read_eval_log(log.location)
    probes = reduce_log_to_probes(log, pack)
    art = RunArtifact(
        pack_name=pack.spec.name,
        pack_hash=pack_fingerprint(pack),
        judge_model=judge_model,
        created_at=datetime.now(timezone.utc).isoformat(),
        probes=probes,
        log_path=str(log.location) if log.location else log_dir,
        rubric_scores_untrusted=rubric_scores_untrusted,
        total_unsure_trials=sum(p.unsure_trials for p in probes),
    )
    art.judge_usd = _judge_usd(log)
    # Write the artifact BEFORE any budget check so a partial/complete artifact
    # survives a budget breach for inspection. Atomic temp-then-rename so a
    # crash mid-write never leaves a torn artifact behind.
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    # Collision-proof, filesystem-safe name (fix #11): microseconds + a short
    # uuid so parallel/fast runs never os.replace-clobber each other, and the
    # pack name is slugified so a hostile/odd name cannot escape out_dir.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", pack.spec.name).strip("-.") or "pack"
    fd, tmp = tempfile.mkstemp(dir=out_path, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(art.to_dict(), indent=2, default=str))
    os.replace(tmp, out_path / f"{stamp}-{uuid.uuid4().hex[:8]}-{slug}.json")
    # Fully-dead target (round-2 N6): with fail_on_error=False every sample can
    # error individually while log.status stays "success" — if NO probe
    # collected a single scored trial the run is a SETUP failure (CLI exit 2),
    # not an all-MISSING gate FAIL. Raised AFTER the artifact write (house
    # pattern: write-before-raise) so the evidence survives for inspection.
    # A partially-dead run still proceeds — per-probe incompleteness is the
    # gate's job (expected_trials / INCOMPLETE).
    if probes and all(p.trials == 0 for p in probes):
        raise RuntimeError(
            "no probe collected a single scored trial — every session errored "
            "(target down or misconfigured?); the run artifact was still "
            f"written under {out_dir}/ for inspection")
    # Post-hoc budget gate: there is no mid-run stop, so the run may already
    # have overshot the cap — the breach is raised after metering.
    cap = pack.spec.budget.max_usd_per_run
    if cap and art.judge_usd > cap:
        raise BudgetExceeded(
            f"judge spend ${art.judge_usd:.4f} exceeded max_usd_per_run ${cap:.2f} "
            f"(partial artifact written)")
    return art
