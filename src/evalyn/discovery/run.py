"""The `discover` orchestrator — where every earlier piece runs together.

`run_discovery` builds the discovery task (one Sample = one hunt), runs it as a
single Inspect eval, reads each hunt's `SessionResult` back out of the sample
store, and for every CONFIRMED session turns the finding into a staged `gate`
probe, dedup-flags it, and replays it once to check it still reds the gate. The
run record — a `DiscoveryArtifact` — is written to disk BEFORE the per-finding
loop can raise (R8-5): that loop is wrapped, and any exception out of it writes
the record built from whatever accumulated so far and only THEN propagates. So
neither a budget stop nor an unwritable pack dir, a re-raised programmer error
from replay, or store shape drift can leave a run that spent money with no
artifact, no report and no spend record (spec §12). The guarantee stops at the
loop, deliberately: `build_discovery_task` and `_run_discovery_eval` run
OUTSIDE the wrap, so a raise out of `inspect_eval`/`read_eval_log` — after the
eval has already spent — still leaves no record. Widening the wrap to cover the
eval is a real behaviour change, logged for Plan #4, not smuggled in here.
(`reconcile` cannot raise; it is fail-open.)

Spend accounting is the subtle part, and two facts from the meter design shape
it:

* **Two spend sources, reconciled from different logs.** The live `SpendMeter`
  charges the agent's own reasoning calls and a conservative estimate for each
  hidden-usage tier-3 confirmation. `reconcile(log)` re-derives spend
  authoritatively from `log.stats.model_usage` — but only for calls made inside
  the eval whose log it is handed. The discovery log therefore carries agent
  spend (because the hunt runs inside the sample); each replay is a *separate*
  eval with its own log carrying judge/replay spend. Both must be reconciled.
  Each replay's reconciled cost is ALSO charged back into the live meter, so
  `--max-usd` is a real ceiling on the replay phase: every metered call
  finishes inside the eval before the first replay, and a meter that never
  moves again makes the replay-skip guard a constant.

* **`max`, never `sum` (R8-14).** The artifact keeps the live figure and the
  summed reconciled figure as SEPARATE fields; the reported spend and any
  budget decision use `max(live, reconciled)`. The reason is an asymmetry: a
  provider that omits `ModelOutput.usage` makes the live meter *over*-charge
  loudly (the pessimistic fallback) and makes `reconcile` *under*-report
  silently. `mockllm` synthesises usage, so a green test proves the plumbing is
  wired, NOT that any real provider populates usage — taking the max is the
  fail-safe direction. Adding the two would double-count every metered call.

* **Per-replay log dirs (R8-15).** `ReplayResult.log_path` can be a *directory*
  (the error fallback). Each replay is given its OWN dir, so reconciling that
  dir cannot sweep up an earlier replay's log and charge it twice.

* **Bounded overshoot (R8-11).** One `SpendMeter` is shared by every hunt and
  `exhausted()` is a check-then-act across `await` points, so concurrent
  sessions can each spend one call past the cap. The overshoot is bounded by
  the discovery concurrency gate (solver.py) and accepted, not locked away —
  documented here so it is not rediscovered as a bug.

Nothing here adds a scorer (R8-8) or a judge≠generator family check (that is
Task 9, R8-16): confirmation already happened inside the session, at the trust
boundary, before any of this ran.
"""
from __future__ import annotations

import asyncio
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from evalyn.discovery import solver
from evalyn.discovery.config import DiscoveryConfig
from evalyn.discovery.dedup import scan_duplicates
from evalyn.discovery.emit import (
    candidate_probe,
    load_prior_discoveries,
    probe_yaml,
    stage_probe,
)
from evalyn.discovery.loop import SessionResult
from evalyn.discovery.meter import SpendMeter, reconcile
from evalyn.discovery.objectives import get_objective
from evalyn.discovery.replay import ReplayResult, replay_staged_probe
from evalyn.discovery.task_builder import build_discovery_task
from evalyn.engine.run import atomic_write_artifact, pack_fingerprint
from evalyn.targets.loader import Pack


# --------------------------------------------------------------------------
# replay verdict: reproduced | failed | SKIPPED are three distinct states
# --------------------------------------------------------------------------

@dataclass
class ReplaySkipped:
    """Replay was not run — distinct from a replay that ran and did not
    reproduce (R8-3). Skipping happens for two UNRELATED reasons and `budget`
    is which: the meter was exhausted (a truncation we did not choose — the run
    is `partial`), or replay was disabled in config (`--no-replay`, which
    skipped nothing involuntarily and must not raise the budget banner).

    A flag, not a substring of `reason`: prose is for humans, and `partial` is
    read by machines.
    """

    reason: str
    budget: bool = True

    def to_dict(self) -> dict:
        return {"skipped": True, "reason": self.reason, "budget": self.budget}


def _replay_to_dict(replay: ReplayResult | ReplaySkipped) -> dict:
    if isinstance(replay, ReplaySkipped):
        return replay.to_dict()
    return {"skipped": False, **asdict(replay)}


def _replay_from_dict(d: dict) -> ReplayResult | ReplaySkipped:
    d = dict(d)
    if d.pop("skipped", False):
        # Artifacts written before the flag existed cannot say which kind of
        # skip they recorded; read them as budget skips, the conservative side
        # (it keeps a legacy run flagged partial rather than silently promoting
        # it to complete).
        return ReplaySkipped(reason=d.get("reason", ""),
                             budget=bool(d.get("budget", True)))
    return ReplayResult(**d)


# --------------------------------------------------------------------------
# the run record
# --------------------------------------------------------------------------

@dataclass
class Finding:
    """One confirmed hunt, emitted as a staged probe and replayed once."""

    objective_id: str
    confirmed: bool
    probe_path: str
    replay: ReplayResult | ReplaySkipped
    duplicate_of: str | None = None
    duplicate_reason: str | None = None
    persona_id: str = ""
    playbook_id: str = ""

    def to_dict(self) -> dict:
        return {
            "objective_id": self.objective_id,
            "confirmed": self.confirmed,
            "probe_path": self.probe_path,
            "replay": _replay_to_dict(self.replay),
            "duplicate_of": self.duplicate_of,
            "duplicate_reason": self.duplicate_reason,
            "persona_id": self.persona_id,
            "playbook_id": self.playbook_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        d = dict(d)
        return cls(
            objective_id=d["objective_id"],
            confirmed=d["confirmed"],
            probe_path=d["probe_path"],
            replay=_replay_from_dict(d["replay"]),
            duplicate_of=d.get("duplicate_of"),
            duplicate_reason=d.get("duplicate_reason"),
            persona_id=d.get("persona_id", ""),
            playbook_id=d.get("playbook_id", ""),
        )


@dataclass
class DiscoveryArtifact:
    """The `discover` run record. Mirrors `RunArtifact`'s to_dict/from_dict.

    `error_count` (R8-2/R8-17) counts sessions with `stop_reason == "error"`
    AND samples that left no store entry at all — both are failed hunts a
    `fail_on_error=False` run would otherwise lose silently. `live_spend_usd`
    and `reconciled_spend_usd` are kept SEPARATE (R8-14); `effective_spend_usd`
    is `max` of the two.

    `eval_status` is the Inspect eval's own status. It is here because every
    per-session counter goes to ZERO when the eval itself fails: an `"error"`
    or `"cancelled"` log carries no samples, so a run that never looked is
    otherwise byte-identical to a run that looked and found nothing. Additive
    with a default, so an artifact written before the field still loads.
    """

    pack_name: str
    pack_hash: str
    agent_model: str
    judge_model: str
    rubric_judge_model: str | None
    created_at: str
    findings: list[Finding]
    error_count: int
    sessions_total: int
    confirmed_count: int
    live_spend_usd: float
    reconciled_spend_usd: float
    budget_exhausted: bool
    partial: bool
    objectives: list[str]
    log_path: str
    eval_status: str = "success"

    @property
    def eval_ok(self) -> bool:
        """Did the discovery eval itself complete? False makes the run INVALID
        — its zeroes mean "no data", never "nothing found"."""
        return self.eval_status == "success"

    @property
    def effective_spend_usd(self) -> float:
        """The reported spend: the LARGER of live and reconciled (R8-14) — never
        the sum (double-counts), never letting reconciliation lower the figure."""
        return max(self.live_spend_usd, self.reconciled_spend_usd)

    def to_dict(self) -> dict:
        return {
            "pack_name": self.pack_name,
            "pack_hash": self.pack_hash,
            "agent_model": self.agent_model,
            "judge_model": self.judge_model,
            "rubric_judge_model": self.rubric_judge_model,
            "created_at": self.created_at,
            "findings": [f.to_dict() for f in self.findings],
            "error_count": self.error_count,
            "sessions_total": self.sessions_total,
            "confirmed_count": self.confirmed_count,
            "live_spend_usd": self.live_spend_usd,
            "reconciled_spend_usd": self.reconciled_spend_usd,
            "effective_spend_usd": self.effective_spend_usd,  # derived, recorded
            "budget_exhausted": self.budget_exhausted,
            "partial": self.partial,
            "objectives": list(self.objectives),
            "log_path": self.log_path,
            "eval_status": self.eval_status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DiscoveryArtifact":
        d = dict(d)
        d.pop("effective_spend_usd", None)  # derived — recomputed by the property
        try:
            findings = [Finding.from_dict(f) for f in d.pop("findings")]
        except (TypeError, KeyError) as e:
            raise ValueError(
                "artifact has no valid 'findings' list; this does not match the "
                "DiscoveryArtifact schema") from e
        try:
            return cls(findings=findings, **d)
        except TypeError as e:
            raise ValueError(
                "artifact fields do not match the DiscoveryArtifact schema "
                f"({e}); this artifact does not match the current schema") from e


# --------------------------------------------------------------------------
# the eval seam (R8-10) — a module-level function so tests can inject a log
# --------------------------------------------------------------------------

async def _run_discovery_eval(task, log_dir: str):
    """Run the discovery task as one eval, OFF the running loop.

    `inspect_eval` drives its own event loop, so it cannot be called from inside
    one (R8-10) — the worker thread gets the loop, this one stays free, exactly
    as `replay.py` does. A distinct module-level function so a test can replace
    it with a crafted log without a real eval.
    """
    logs = await asyncio.to_thread(
        inspect_eval, task, model="mockllm/model", log_dir=log_dir,
        display="none")
    log = logs[0]
    if getattr(log, "samples", None) is None and getattr(log, "location", None):
        log = await asyncio.to_thread(read_eval_log, log.location)
    return log


def _answered_turns(session: SessionResult) -> list[str]:
    """The user turns the target actually answered, rebuilt from the steps.

    The confirmed probe was content-addressed over `answered_user_turns(transcript)`
    inside the loop; a "sent" step is exactly a user turn the target answered, so
    this reproduces the same turn list (and therefore the same probe id) from the
    stored `SessionResult` alone — the live transcript is not in the store."""
    return [s.message for s in session.steps
            if s.action == "send" and s.outcome == "sent" and s.message]


def _provenance(session: SessionResult, cfg: DiscoveryConfig) -> dict:
    """Header provenance for the staged probe. Agent-influenced text (the
    confirmation reason, the turn excerpts) is swept by emit's widened
    sanitizer (R8-4) — a C1 char or lone surrogate here must not make the
    staged YAML unparseable."""
    return {
        "objective": session.objective_id,
        "persona": session.persona_id,
        "playbook": session.playbook_id,
        "agent_model": cfg.agent_model,
        "stop_reason": session.stop_reason,
        "usd_estimated": f"{session.usd_estimated:.4f}",
        "confirmation": session.confirmed.reason if session.confirmed else "",
        "turns": " | ".join(_answered_turns(session)),
    }


def _reconcile_one(location: str) -> float:
    """Read and reconcile a single log file — fail-open. A finished run's
    accounting must never crash on an unreadable/partial log (R8-5); `reconcile`
    is already fail-open, and the read is guarded the same way."""
    try:
        return reconcile(read_eval_log(location))
    except Exception as e:  # noqa: BLE001 — a corrupt log is not worth a crash
        warnings.warn(
            f"could not reconcile replay log {location!r} "
            f"({type(e).__name__}: {e}) — counted as $0 for this log",
            RuntimeWarning, stacklevel=2)
        return 0.0


def _reconcile_path(path: str) -> float:
    """Reconcile every eval log at `path`, once. `path` is a single log file on
    the normal replay path, or a DIRECTORY on the error fallback (R8-15) — each
    replay owns its dir, so a directory scan cannot capture another replay's
    log."""
    if not path:
        return 0.0
    p = Path(path)
    if p.is_dir():
        files = sorted({*p.glob("*.eval"), *p.glob("*.json")})
        return sum(_reconcile_one(str(f)) for f in files)
    return _reconcile_one(str(p))


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------

async def run_discovery(pack: Pack, cfg: DiscoveryConfig, *,
                        run_id: str | None = None) -> DiscoveryArtifact:
    """Run one `discover` pass and return its record. Never raises on budget.

    `run_id` (keyword-only, `None` = mint as before) reaches the writer from the
    CLI's `EVALYN_RUN_ID` read. It has to travel this far because discover owns
    its own writes — including the partial one on the failing path, which is the
    write a cockpit most needs to find.
    """
    meter = SpendMeter(cfg.limits.max_usd)
    task = build_discovery_task(pack, cfg, meter=meter)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    log_root = Path(cfg.out_dir) / "logs" / f"discover-{stamp}"
    disc_log_dir = str(log_root / "discovery")

    log = await _run_discovery_eval(task, disc_log_dir)

    # The eval's own verdict on itself. `"error"`/`"cancelled"` (an unwritable
    # log_dir, a provider outage, Ctrl-C) leaves `log.samples` empty, so every
    # counter below reads zero and the record is indistinguishable from a clean
    # run that found nothing. `engine/run.py` and `replay.py` both RAISE here;
    # this path deliberately does not — it sits OUTSIDE the R8-5 durability
    # wrap, so raising would leave a run that already spent with no artifact at
    # all. Record it instead; the CLI turns it into exit 3 (run-invalid).
    eval_status = str(getattr(log, "status", "") or "success")

    # Log-authoritative spend, accumulated across the discovery log and every
    # replay log. `reconcile` returns usd and does NOT mutate the meter — the
    # live figure stays independent (R8-14).
    reconciled = reconcile(log)
    log_location = str(getattr(log, "location", "") or disc_log_dir)

    findings: list[Finding] = []
    error_count = 0
    confirmed_count = 0
    sessions_total = 0
    budget_stops = False

    staging_dir = Path(cfg.staging_dir) if cfg.staging_dir is not None \
        else pack.root / "discoveries"

    def _build_artifact(*, aborted: bool = False) -> DiscoveryArtifact:
        """The run record built from whatever has accumulated SO FAR.

        A closure over the loop's accumulators, so the record written on the
        happy path and the one written from a half-finished loop are built by
        the same code and cannot drift. The cap decision uses the LARGER of the
        two spend sources (R8-14): the live meter trips at the cap, and an
        authoritative reconciled figure at or over the cap counts too —
        reconciliation must never LOWER a breach.
        """
        cap = cfg.limits.max_usd
        exhausted = meter.exhausted() or (cap > 0 and reconciled >= cap)
        # `partial` = this run did not do all the work it set out to do, so
        # absence is not evidence of absence. A replay skipped because the
        # OPERATOR disabled it was not work we failed to do — only a
        # budget-forced skip counts (`ReplaySkipped.budget`); folding both in
        # made `--no-replay` on a $0.01 run print the BUDGET banner.
        partial = aborted or exhausted or budget_stops or (
            eval_status != "success") or any(
            isinstance(f.replay, ReplaySkipped) and f.replay.budget
            for f in findings)
        return DiscoveryArtifact(
            pack_name=pack.spec.name,
            pack_hash=pack_fingerprint(pack),
            agent_model=cfg.agent_model,
            judge_model=cfg.judge_model,
            rubric_judge_model=cfg.rubric_judge_model,
            created_at=datetime.now(timezone.utc).isoformat(),
            findings=list(findings),
            error_count=error_count,
            sessions_total=sessions_total,
            confirmed_count=confirmed_count,
            live_spend_usd=meter.spent_usd,
            reconciled_spend_usd=reconciled,
            budget_exhausted=exhausted,
            partial=partial,
            objectives=list(cfg.objectives),
            log_path=log_location,
            eval_status=eval_status,
        )

    # R8-5 made real. This loop CAN raise — `stage_probe` on an unwritable pack
    # dir or a full disk, `replay_staged_probe` re-raising a programmer error,
    # `session_from_store` on shape drift — and by then the money is already
    # spent. Every accumulator lives in THIS scope, so a raise mid-loop still
    # leaves a complete record of the findings made and the dollars burned.
    try:
        for sample in getattr(log, "samples", None) or []:
            sessions_total += 1
            stored = (getattr(sample, "store", None) or {}).get(
                solver.DISCOVERY_STORE_KEY)
            session = solver.session_from_store(stored)
            if session is None:
                # A sample that errored OUTSIDE the solver left no store entry
                # (R8-17): a failed hunt, never "no data".
                error_count += 1
                continue
            if session.stop_reason == "error":
                error_count += 1
            if session.stop_reason == "budget":
                budget_stops = True
            if not (session.confirmed and session.confirmed.confirmed):
                continue

            confirmed_count += 1
            objective = get_objective(session.objective_id)
            slots = session.probe_slots or {}
            turns = _answered_turns(session)
            probe = candidate_probe(objective, slots, turns)

            # Dedup BEFORE staging this probe, so the candidate does not match
            # its own just-written file; earlier findings from this same run
            # (already staged) DO count as priors.
            priors = load_prior_discoveries(staging_dir)
            dup = scan_duplicates(probe, priors)

            yaml_text = probe_yaml(probe, provenance=_provenance(session, cfg))
            staged = stage_probe(pack, probe, yaml_text,
                                 staging_dir=cfg.staging_dir)

            replay = await _replay_finding(pack, cfg, meter, probe.id, staged,
                                           log_root)
            if isinstance(replay, ReplayResult) and replay.log_path:
                replay_usd = _reconcile_path(replay.log_path)
                reconciled += replay_usd
                # ...and charge it back into the LIVE meter, or `--max-usd` is
                # not the run ceiling it is documented to be: every agent and
                # confirmation call completes inside the eval BEFORE the first
                # replay, so without this the meter is frozen for the whole
                # replay phase and `_replay_finding`'s `exhausted()` guard
                # evaluates identically every time (at `--max-sessions 50`, 50
                # replays the cap could not stop). Both spend series gain the
                # same term, so `max(live, reconciled)` still never sums.
                meter.charge_estimate(replay_usd)

            findings.append(Finding(
                objective_id=session.objective_id,
                confirmed=True,
                probe_path=str(staged),
                replay=replay,
                duplicate_of=dup.probe_id if dup else None,
                duplicate_reason=dup.reason if dup else None,
                persona_id=session.persona_id,
                playbook_id=session.playbook_id,
            ))
    except BaseException:
        # Write what we have, THEN let the original failure propagate. The
        # original is never LOST: a double failure (loop raises AND the fallback
        # write fails) still re-raises it, warning about the write. One caveat,
        # so nobody reads this as absolute — under `-W error::RuntimeWarning`
        # the warning becomes the surfaced exception and the original is demoted
        # to its `__context__`. Benign under default filters, and the chain
        # always carries both.
        try:
            write_discovery_artifact(_build_artifact(aborted=True),
                                     out_dir=str(cfg.out_dir), run_id=run_id)
        except Exception as e:  # noqa: BLE001 — report it, never swallow it
            warnings.warn(
                f"discovery run failed AND its partial artifact could not be "
                f"written ({type(e).__name__}: {e}) — the spend record for this "
                f"run is lost", RuntimeWarning, stacklevel=2)
        raise

    artifact = _build_artifact()

    # Write BEFORE returning — and, on the failing path above, before the raise
    # — so neither a budget stop nor a mid-loop exception leaves a run that
    # spent money with no record (spec §12 / R8-5).
    write_discovery_artifact(artifact, out_dir=str(cfg.out_dir), run_id=run_id)
    return artifact


async def _replay_finding(pack: Pack, cfg: DiscoveryConfig, meter: SpendMeter,
                          probe_id: str, staged: Path,
                          log_root: Path) -> ReplayResult | ReplaySkipped:
    """Replay one staged probe — or skip it, distinctly, when we must not spend.

    Replay of a tier-3 probe invokes the real rubric judge, which is money the
    live meter cannot see in advance (R8-3). So: skip entirely when the meter is
    already exhausted, and record a `ReplaySkipped` (never a failed replay).
    `judge_model` is passed EXPLICITLY — the default `mockllm/model` would make a
    required judge-graded check fabricate `reproduced=True`."""
    if not cfg.replay:
        return ReplaySkipped("skipped (replay disabled in config)", budget=False)
    if meter.exhausted():
        return ReplaySkipped("skipped (budget) — meter exhausted before replay",
                             budget=True)
    # Each replay gets its OWN log dir so the directory fallback cannot capture
    # another replay's log and double-charge it (R8-15).
    replay_dir = str(log_root / f"replay-{probe_id}")
    return await replay_staged_probe(
        pack, staged, judge_model=cfg.judge_model,
        rubric_model=cfg.rubric_judge_model, log_dir=replay_dir)


# --------------------------------------------------------------------------
# write + report
# --------------------------------------------------------------------------

def write_discovery_artifact(artifact: DiscoveryArtifact,
                             out_dir: str = "runs",
                             *, run_id: str | None = None) -> Path:
    """Atomic temp-then-rename write — the shared house writer (R8-13), suffixed
    `-discover`.

    `run_id=None` mints exactly as before; a caller that passes one gets
    `runs/<run_id>-discover.json`."""
    return atomic_write_artifact(artifact.to_dict(), artifact.pack_name, out_dir,
                                 suffix="-discover", run_id=run_id)


def _replay_line(replay: ReplayResult | ReplaySkipped) -> str:
    if isinstance(replay, ReplaySkipped):
        return f"replay SKIPPED — {replay.reason}"
    if replay.reproduced:
        line = (f"replay REPRODUCED (pass^k {replay.pass_k} over "
                f"{replay.trials} trial(s))")
        # `reproduced` only says SOME trial failed. A human deciding whether to
        # adopt needs the two weaker cases named, not hidden behind the verdict.
        caveats = []
        if replay.pass_at_k > 0.0:
            caveats.append(f"FLAKY: some trial PASSED (pass@k {replay.pass_at_k})")
        if replay.expected_trials and replay.trials < replay.expected_trials:
            caveats.append(f"PARTIAL: only {replay.trials} of "
                           f"{replay.expected_trials} expected trial(s) scored")
        if caveats:
            line += " — " + "; ".join(caveats)
        return line
    return f"replay did NOT reproduce — {replay.reason or 'see log'}"


def render_discovery_report(artifact: DiscoveryArtifact) -> str:
    """A human-facing summary: title, prominent error count (R8-2), spend and
    budget banner, then one block per finding with its replay verdict and any
    duplicate flag."""
    a = artifact
    lines = [f"# Evalyn discover — {a.pack_name}", "",
             f"agent: `{a.agent_model}` · judge: `{a.judge_model}` · "
             f"pack: `{a.pack_hash[:12]}`", ""]
    lines.append(f"**{a.confirmed_count} finding(s)** from {a.sessions_total} "
                 f"hunt(s).")

    # Before anything else: if the eval itself did not complete, every number
    # above it is "no data", not "nothing found". Loudest line in the report.
    if not a.eval_ok:
        lines.append(
            f"**RUN INVALID — the discovery eval ended `{a.eval_status}`.** No "
            f"samples were produced, so the counts above are the absence of "
            f"data, NOT the absence of weaknesses. Check the eval log "
            f"(`{a.log_path}`) and re-run; do not read this as a clean pass.")

    # R8-2: the error count is a TOP-LEVEL line, not a per-session detail. A run
    # where every hunt errored is the worst case (looks like a clean empty run).
    if a.error_count:
        all_errored = a.sessions_total > 0 and a.error_count >= a.sessions_total
        prefix = "**ALL " if all_errored else "**"
        lines.append(f"{prefix}{a.error_count} session(s) errored** — failed "
                     f"hunts (crashed or left no result), not clean empties.")

    spend = (f"spend ${a.effective_spend_usd:.4f} (live ${a.live_spend_usd:.4f} "
             f"/ reconciled ${a.reconciled_spend_usd:.4f})")
    if a.partial and a.budget_exhausted:
        # Only when the CAP is what truncated the run. Every budget-caused
        # partial implies an exhausted meter (a budget stop or a budget-skipped
        # replay can only happen once `exhausted()` is true, and the meter never
        # goes down), so this banner cannot miss one — and, since a
        # config-disabled replay no longer sets `partial`, it can no longer
        # appear on a run that skipped nothing involuntarily.
        lines.append(
            f"**BUDGET: partial run** — {spend}; some work was skipped to stay "
            f"under the cap. Findings below are real; absence is not evidence.")
    elif a.partial:
        lines.append(
            f"**PARTIAL run** — {spend}; the run did not finish everything it "
            f"planned (the cap was not what stopped it — see above). Findings "
            f"below are real; absence is not evidence.")
    else:
        lines.append(
            f"Spend ${a.effective_spend_usd:.4f} "
            f"(live ${a.live_spend_usd:.4f} / reconciled "
            f"${a.reconciled_spend_usd:.4f}).")

    if a.findings:
        lines += ["", "## Findings"]
        for f in a.findings:
            lines.append(f"- **{f.objective_id}** ({f.persona_id or 'persona?'}"
                         f"/{f.playbook_id or 'playbook?'}) → `{f.probe_path}`")
            lines.append(f"  - {_replay_line(f.replay)}")
            if f.duplicate_of:
                lines.append(f"  - possible DUPLICATE of `{f.duplicate_of}`: "
                             f"{f.duplicate_reason}")
    else:
        lines += ["", "## Findings", "(none confirmed this run)"]

    return "\n".join(lines)
