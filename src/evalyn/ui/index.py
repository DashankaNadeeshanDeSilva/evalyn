"""The runs table, built from a directory nobody curated (Plan #4, Task 3).

`RunIndex` turns `runs/` into rows. That directory is not a database: it has
accumulated artifacts from three schema generations, a blessed `baseline.json`,
an Inspect `logs/` tree, sidecar files, and whatever a run that died halfway
left behind. The cockpit's primary screen reads from it, so the only acceptable
behaviour is **degradation, not failure** — every entry that looks like a run
becomes a row, and nothing in here raises on the listing path.

Four decisions carry that:

* **Mode is lexical.** `-compare` / `-discover` in the filename decides;
  a file is never opened to learn what it is. That is what lets a completely
  unreadable artifact still land in the right column, and it is why a
  `run_id` deliberately *keeps* its mode suffix (`…-example-compare` is a
  legal id, since `-` is in the slug charset).
* **Three layers, every one caught.** `read` → `json.loads` → typed
  `from_dict`, falling back to a shallow *salvage* read (`pack_name`,
  `created_at`, `probes` length) that is enough for a greyed row with a
  tooltip. Below even that, `created_at` is recovered from the filename stamp,
  so a row always knows who it is and when it happened.
* **The grammar has one home (R4-7).** `is_run_id` is imported from the frozen
  contract via `ui.paths`; this module never re-spells the pattern, and
  `tests/ui/test_index.py` scans this source to prove it. Excluding
  `baseline.json`, `logs/` and the `.events.jsonl` / `.control.json` sidecars
  therefore costs no second rule — they simply are not run ids.
* **`evaluate_gate` is never called here.** It reads a baseline and renders
  markdown; doing that per row would make the list quadratic in disk reads.
  Rows carry `verdict_hint`, computed from `probes[]` alone and typed as an
  approximation. The authoritative verdict is a separate, lazy endpoint.

**Ordering is `(created_at, run_id)` descending**, the key the frozen contract's
cursor encodes — compared as a parsed *tuple*, never as the joined string. Note
that this is deliberately not the same as `sorted(filenames, reverse=True)`:
the filename stamp is minted when a run is *launched* while `created_at` is
recorded by the artifact, and two overlapping runs can order differently under
the two. Filename order is used only to decide what to load first; the rows are
then sorted by the contract's key. The `(path, st_mtime_ns, st_size)` cache is
what keeps repeat listings to one `stat` per file.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from evalyn.discovery.run import DiscoveryArtifact
from evalyn.engine.compare import CompareArtifact
from evalyn.engine.gate import GateResult
from evalyn.engine.run import RunArtifact
from evalyn.ui.models import (
    Capabilities,
    CategoryTally,
    CheckView,
    ControlAction,
    DiscoverySummary,
    FindingRow,
    HardMetrics,
    ProbeRow,
    ReplayStatus,
    ReplayView,
    RunDetail,
    RunMode,
    RunStatus,
    RunSummary,
    Scoreboard,
    VerdictHint,
    parse_cursor,
)
from evalyn.ui.paths import (
    CONTROL_SUFFIX,
    META_EXIT_CODE_KEY,
    META_LAUNCHED_KEY,
    SIDECAR_DIR_NAME,
    control_path,
    is_run_id,
    meta_path,
    sidecar_dir,
)

__all__ = [
    "RunIndex", "RunNotFound", "LoadedArtifact", "SidecarState", "StagedProbe",
    "derive_status", "cancelled_by", "mode_of", "created_at_from_run_id",
    "verdict_hint_of", "capabilities_of", "is_run_id",
    "PROVENANCE_KEYS", "parse_provenance", "load_staged_probes",
]


class RunNotFound(KeyError):
    """No indexable artifact for this id — including "that is not an id".

    A `KeyError` subclass so the endpoint layer can map it to a 404 without
    importing anything web-shaped. An id that fails the grammar raises this
    rather than a `ValueError`: the resource cannot exist, and saying only that
    leaks nothing about the filesystem (contract §422 mapping).
    """


# --------------------------------------------------------------------------
# 1. Lexical facts — everything recoverable from the filename alone
# --------------------------------------------------------------------------

#: Longest suffix first would matter if one were a prefix of another; they are
#: not, but the tuple keeps the order explicit rather than relying on a dict.
_MODE_BY_SUFFIX: tuple[tuple[str, RunMode], ...] = (
    ("-compare", RunMode.compare),
    ("-discover", RunMode.discover),
)

_TYPED_LOADER = {
    RunMode.gate: RunArtifact.from_dict,
    RunMode.compare: CompareArtifact.from_dict,
    RunMode.discover: DiscoveryArtifact.from_dict,
}

#: `YYYYmmddTHHMMSS` — the fixed head of every run id, with an optional
#: microsecond tail after it. Spelled as a length rather than a pattern so this
#: module keeps the promise that the grammar lives in exactly one place (R4-7).
_STAMP_HEAD = len("YYYYmmddTHHMMSS")
_STAMP_FORMAT = "%Y%m%dT%H%M%S"


def mode_of(run_id: str) -> RunMode:
    """Which mode wrote this artifact — decided by the filename, never by IO."""
    for suffix, mode in _MODE_BY_SUFFIX:
        if run_id.endswith(suffix):
            return mode
    return RunMode.gate


def created_at_from_run_id(run_id: str) -> str:
    """Recover an ISO-8601 UTC stamp from the id when the body cannot say.

    This is the floor under the salvage layer: a row whose artifact is a single
    `{` still sorts and renders in the right place. Returns `""` — never
    raises — when the head is not a real moment, which the grammar permits
    (it checks digit counts, not calendars).
    """
    stamp = run_id.partition("-")[0]
    try:
        moment = datetime.strptime(stamp[:_STAMP_HEAD], _STAMP_FORMAT)
    except ValueError:
        return ""
    tail = stamp[_STAMP_HEAD:]
    if tail:
        try:
            moment = moment.replace(microsecond=int(tail.ljust(6, "0")[:6]))
        except ValueError:
            return ""
    return moment.replace(tzinfo=timezone.utc).isoformat()


# --------------------------------------------------------------------------
# 2. The load outcome and the process state — the two inputs to a status
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LoadedArtifact:
    """One artifact as far as it could be read. `typed is None` == degraded.

    `salvage` holds only what a shallow read could vouch for, so it survives a
    body the typed loader rejects; `raw` is the whole parsed object, kept for
    the "absent vs null" distinction the contract insists on (a missing
    `judge_usd` key is `None`, not `0.0`, and the dataclass default cannot tell
    you which one it was).
    """

    run_id: str
    mode: RunMode
    path: Path | None = None
    typed: object | None = None
    raw: dict | None = None
    salvage: dict = field(default_factory=dict)
    #: The `degraded_reason`. `None` exactly when `typed` loaded.
    error: str | None = None


@dataclass(frozen=True)
class SidecarState:
    """What the server's own bookkeeping says about a run's **process**.

    Empty for every run in a `runs/` the cockpit never launched — which is all
    of them until Task 19 ships the launcher — and that is the point: an
    artifact-only run reports its status from the artifact, with no invented
    process facts. Task 19/20 own the writer for `meta.json` and the control
    file; this module only ever reads them, defensively.
    """

    #: `runs/.evalyn-ui/<run_id>/` exists, i.e. this cockpit launched the run.
    present: bool = False
    #: The child process actually started. `False` is `failed_to_start`.
    launched: bool = True
    #: Last action written to `<stem>.control.json`.
    control: ControlAction | None = None
    #: `None` while the child is still alive (or when nothing recorded it).
    exit_code: int | None = None
    #: A `<stem>.events.jsonl` exists — evidence the run got as far as emitting.
    events: bool = False
    #: `meta.json` is there but this build understood **nothing** in it — it did
    #: not parse, or carried neither known key. Load-bearing rather than
    #: diagnostic: without it, "no exit code recorded" is indistinguishable
    #: from "still alive", and a dead run spins in the table forever. With it,
    #: the absence of understanding degrades to `interrupted` instead.
    schema_unrecognised: bool = False


# --------------------------------------------------------------------------
# 3. Derived views over a loaded artifact
# --------------------------------------------------------------------------

def verdict_hint_of(artifact: RunArtifact) -> VerdictHint:
    """The cheap approximation of a gate verdict, from `probes[]` only.

    It reproduces the three gate rules that need no baseline — MISSING,
    INCOMPLETE and the safety `pass^k` — and deliberately omits REGRESSION,
    which does. So `passed` here means "nothing failed *on its own terms*",
    never "the gate passed", and the SPA must render it as an approximation.
    Capability probes are excluded because they never red a build.
    """
    probes = [p for p in artifact.probes if p.kind != "capability"]
    if not probes:
        return VerdictHint.unknown
    for probe in probes:
        if probe.trials == 0:
            return VerdictHint.failed
        if probe.expected_trials and probe.trials < probe.expected_trials:
            return VerdictHint.failed
        if probe.safety_critical and probe.pass_k < 1.0:
            return VerdictHint.failed
    return VerdictHint.passed


def capabilities_of(loaded: LoadedArtifact) -> Capabilities:
    """What this artifact can actually answer — never inferred from truthiness.

    A degraded artifact can answer nothing, which is a different statement from
    "the run had no trials"; both come out as `False` here, and the row's
    `degraded` flag is what separates them.
    """
    typed = loaded.typed
    if isinstance(typed, RunArtifact):
        records = [rec for probe in typed.probes for rec in probe.trial_records]
        # R4-42: `trial_records` must mean EXACTLY "at least one probe has a
        # non-empty `ProbeRow.trial_epochs`", so it is derived through the same
        # filter `_probe_row` applies rather than from the raw list. `bool(
        # records)` was a second, weaker spelling of the same fact, and the two
        # disagree on a record carrying no `epoch`: the capability said yes, the
        # epochs came back empty, and the SPA — which gates the drill-down on
        # the capability — would offer a click that 404s while blaming the
        # capability for being wrong. Not reachable from current engine output;
        # derived rather than asserted so it cannot become reachable.
        #
        # `transcripts` narrows with it, and for the same reason: it is the
        # claim "the drill-down works", and the drill-down is addressed by
        # `(probe_id, epoch)` — a record with no epoch is not reachable through
        # it. `hard_metrics` deliberately keeps the whole list: it is an
        # *aggregate* over trial records, and an aggregate needs no address.
        drillable = [rec for rec in records
                     if isinstance(rec, dict) and "epoch" in rec]
        return Capabilities(
            transcripts=any(rec.get("transcript") for rec in drillable),
            trial_records=bool(drillable),
            hard_metrics=any(rec.get("session_seconds") is not None
                             for rec in records),
        )
    if isinstance(typed, CompareArtifact):
        return Capabilities(transcripts=False, trial_records=False,
                            hard_metrics=bool(typed.hard_metrics))
    return Capabilities(transcripts=False, trial_records=False, hard_metrics=False)


def cancelled_by(artifact: LoadedArtifact | None,
                 sidecar: SidecarState) -> bool:
    """Did an operator stop this run? **The artifact outranks the file.**

    Two witnesses disagree here, and only one of them is authoritative.

    `RunArtifact.cancelled` is written by the engine itself, at the moment it
    honoured the cancel (`run.py:431`), and it is what makes the run exit 3
    rather than 1 — a genuinely cancelled run also has `log.results is None`
    and reduces its un-run probes to `trials=0` (R4-13). It cannot be wrong.

    `<stem>.control.json` is only a **request**, and it outlives the run that
    was asked: the endpoint removes one it wrote for a run that finished
    underneath it, but the run can finish an instant after that check too — the
    residual race registered in `docs/JOURNAL.md` (`be9ab3a`). Trusting the
    request over the record was measured relabelling a run that had completed
    all 12 of its trials as `cancelled`, in the list and on the detail page. A
    completed evaluation's verdict must not be rewritable by a leftover file.

    So the control file is consulted only where there is no artifact-side
    answer: before an artifact exists at all; when this build cannot parse the
    one that does; and for `compare`/`discover`, whose artifacts carry no such
    field — a cancelled `compare` writes no artifact at all
    (`compare.py:250-256`), so the file is the only evidence it leaves.
    """
    typed = artifact.typed if artifact is not None else None
    if isinstance(typed, RunArtifact):
        return bool(typed.cancelled)
    return sidecar.control is ControlAction.cancel


def derive_status(artifact: LoadedArtifact | None,
                  sidecar: SidecarState | None = None,
                  gate_result: GateResult | None = None) -> RunStatus:
    """The one place a run's status is decided. Pure: no IO, no mutation.

    Precedence, and each step is a distinction the operator cares about:

    1. **`failed_to_start`** — the child never ran, so nothing else can be true.
    2. **No artifact at all.** An explicit cancel wins; otherwise a live
       process is `running` (or `paused`), and a dead one is `interrupted` —
       the run vanished without writing its record. A `meta.json` this build
       cannot read is *not* evidence of life: it degrades to `interrupted`
       rather than leaving a dead run spinning in the table forever.
    3. **A deliberate cancel**, decided by `cancelled_by` — the artifact's own
       `cancelled` field where there is one, and the control file only where
       there is not. It outranks a parse failure: "the operator stopped it" is
       the more useful fact about a half-written artifact than "this build
       cannot read it". It does **not** outrank a readable artifact that says
       nobody cancelled it; see `cancelled_by` for why the file is the weaker
       witness.
    4. **`unreadable`** — the artifact exists and this build cannot parse it.
       Distinct from `invalid`: the run may have been perfectly fine.
    5. **`invalid`** — parsed, but the numbers mean nothing: a discover run
       whose eval itself failed (every counter is zero because nothing looked),
       or a gate run with **no probes at all**, which measured nothing.
    6. **`gate_failed` / `passed`** — from the real `GateResult` when the caller
       has one (the detail endpoint), otherwise from `verdict_hint_of`, which
       is why the list can decide a status without a baseline read.

    Ruling R4-17 fixes the order of 5 and 6: a **capability-only** run is
    `passed`, not `invalid`. It measured exactly what it set out to measure and
    `evaluate_gate` returns `exit_code=0` for it; that nothing was *gated* is
    already carried losslessly by `verdict_hint=unknown`, so spending `invalid`
    — which this module defines as "the numbers mean nothing" — on it would be
    a false claim. `invalid` is therefore reserved for an empty `probes[]`, and
    a real `GateResult` is consulted before the hint is ever inspected.
    """
    side = sidecar if sidecar is not None else SidecarState()

    if not side.launched:
        return RunStatus.failed_to_start

    if artifact is None:
        if cancelled_by(None, side):
            return RunStatus.cancelled
        if side.present and side.exit_code is None:
            if side.control is ControlAction.pause:
                # positive evidence from a second, readable file: the operator
                # asked for this, so say so even if `meta.json` is unreadable
                return RunStatus.paused
            return (RunStatus.interrupted if side.schema_unrecognised
                    else RunStatus.running)
        return RunStatus.interrupted

    if cancelled_by(artifact, side):
        return RunStatus.cancelled
    if artifact.typed is None:
        return RunStatus.unreadable

    typed = artifact.typed
    if isinstance(typed, DiscoveryArtifact):
        return RunStatus.passed if typed.eval_ok else RunStatus.invalid
    if isinstance(typed, CompareArtifact):
        return RunStatus.passed

    if not typed.probes:
        return RunStatus.invalid
    if gate_result is not None:
        return RunStatus.gate_failed if gate_result.exit_code else RunStatus.passed
    return (RunStatus.gate_failed if verdict_hint_of(typed) is VerdictHint.failed
            else RunStatus.passed)


# --------------------------------------------------------------------------
# 4. Mapping helpers — artifact dicts to wire models
# --------------------------------------------------------------------------

def _number(value: object) -> float | None:
    """A recorded number, or `None`. `bool` is not a number here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _recorded(raw_probe: dict, key: str, value: object) -> float | None:
    """`value` as a number, but only if the artifact actually wrote `key`.

    The one place a dataclass default is told apart from a measurement. See
    `_probe_row` for why that distinction is load-bearing.
    """
    return _number(value) if key in raw_probe else None


def _check_view(check: dict) -> CheckView:
    """One artifact check dict as a `CheckView`.

    Mapped key by key rather than `CheckView(**check)`: the wire models are
    `extra="forbid"`, so a future artifact field would otherwise turn a
    readable run into a 500 — the exact failure this module exists to avoid.
    """
    return CheckView(
        check=str(check.get("check", "")),
        tier=check.get("tier", "abstained"),
        required=bool(check.get("required", False)),
        weight=float(check.get("weight", 0.0) or 0.0),
        passed=check.get("passed"),
        score=_number(check.get("score")),
        turn=check.get("turn"),
        evidence=str(check.get("evidence") or ""),
        unsure=bool(check.get("unsure", False)),
    )


def _probe_row(probe, raw_probe: object) -> ProbeRow:
    """One typed probe as a `ProbeRow`, with a metric it never recorded `None`.

    **The three trend metrics are read from the RAW entry's key presence, not
    from the typed value.** `ProbeResult` is a plain dataclass whose
    `pass_at_k` / `pass_k` / `mean_score` all default to `0.0`, so by the time
    an artifact is typed, "this run never measured the probe" and "this run
    measured a total failure" are the same number. The difference survives in
    exactly one place — whether the artifact wrote the key at all — and it
    matters more than any other distinction this file draws: `build_trends`
    plots a `0.0` and skips a `None`, and the trends page ranks channels by the
    metric's worst reading, so a fabricated zero for an unmeasured probe
    becomes the channel the page opens on. `None` reads honestly as "no
    reading" and leaves a gap in the line.

    A *recorded* `0.0` is still a `0.0`: presence of the key is the test, never
    the value, because a probe that genuinely scored zero is the failure the
    page exists to show.

    `raw_probe` is this probe's own entry from the artifact's raw `probes`
    list. It is believed only when it is a dict carrying this probe's id; an
    entry that cannot be positively paired says nothing about what was
    recorded, and **unknown resolves to "no reading", never to a number this
    function cannot vouch for**. That fallback is deliberate: fabricating is
    the failure mode the whole rule exists to prevent, and a mis-pairing
    introduced later should degrade to a visibly empty chart rather than
    quietly restore the zero. In practice the pairing cannot fail —
    `RunArtifact.from_dict` builds exactly one `ProbeResult` per raw entry, in
    order, and rejects any entry that is not a dict with an `id` — so this is a
    guard against a future caller rather than a live branch.
    """
    recorded = (raw_probe if isinstance(raw_probe, dict)
                and raw_probe.get("id") == probe.id else {})
    return ProbeRow(
        id=probe.id, category=probe.category, kind=probe.kind,
        safety_critical=probe.safety_critical, samples=probe.samples,
        trials=probe.trials, expected_trials=probe.expected_trials,
        pass_at_k=_recorded(recorded, "pass_at_k", probe.pass_at_k),
        pass_k=_recorded(recorded, "pass_k", probe.pass_k),
        mean_score=_recorded(recorded, "mean_score", probe.mean_score),
        unsure_trials=probe.unsure_trials,
        checks=[_check_view(c) for c in probe.checks if isinstance(c, dict)],
        trial_epochs=sorted(rec["epoch"] for rec in probe.trial_records
                            if isinstance(rec, dict) and "epoch" in rec),
    )


# --------------------------------------------------------------------------
# 4b. Staged discoveries — the read side of `<pack>/discoveries/*.yaml`
# --------------------------------------------------------------------------

#: The eight keys `discovery/run.py::_provenance` writes into every staged
#: probe's comment header, in the order it writes them.
#:
#: An **allowlist**, not a hint. The caution block sitting above them opens
#: `# CAUTION: this file may contain LIVE DATA ...`, which is exactly
#: `# key: value`-shaped, so a parser that took every colon-bearing comment
#: line would hand the SPA a paragraph of boilerplate as a provenance field.
PROVENANCE_KEYS: tuple[str, ...] = (
    "objective", "persona", "playbook", "agent_model",
    "stop_reason", "usd_estimated", "confirmation", "turns",
)

#: `emit._comment_lines` re-prefixes the continuation lines of a multi-line
#: provenance value with `#` and FIVE spaces; the caution block's own wrapped
#: lines use three. The exact width is the only thing that tells them apart.
_PROVENANCE_CONTINUATION = "#     "


def parse_provenance(text: str) -> dict[str, str]:
    """The eight provenance keys out of a staged probe's **comment** header.

    Provenance is not in the YAML — `yaml.safe_load` discards comments, which
    is why this reads the file as text. It is the read side of
    `emit.probe_yaml`, and it mirrors that writer in two respects a naive
    line-scan gets wrong.

    First, it reads only the **contiguous run of comments at the top of the
    file**. A `#` further down belongs to the body — a comment on a check, or a
    character inside an agent-authored turn — and a whole-file scan would let
    it overwrite the real value.

    Second, it rejoins continuation lines. A confirmation reason containing a
    newline is written as `# confirmation: <first line>` followed by
    `#     <rest>`, and a parser that keeps only the first line silently
    truncates the very field that records what was captured.

    Returns `{}` rather than raising for a file with no header: an adopted
    probe under `probes/` is a plain YAML list, and having no provenance is a
    state, not a failure.
    """
    values: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        if not line.startswith("#"):
            if not line.strip():
                continue                     # a blank line is not the end of it
            break                            # the YAML body: the header is over
        if current is not None and line.startswith(_PROVENANCE_CONTINUATION):
            values[current] += "\n" + line[len(_PROVENANCE_CONTINUATION):]
            continue
        key, separator, value = line[1:].strip().partition(":")
        if separator and key in PROVENANCE_KEYS:
            values[key] = value.strip()
            current = key
        else:
            current = None
    return values


@dataclass(frozen=True)
class StagedProbe:
    """One `<pack>/discoveries/*.yaml` as the cockpit reads it back.

    Carries the file's **bytes as committed** alongside the parsed probe: the
    detail view shows an operator the thing they will `git mv`, and a
    re-serialization of the parsed model is a different file.
    """

    probe_id: str
    path: Path
    probe: object
    text: str
    provenance: dict[str, str]


def load_staged_probes(packs) -> dict[str, StagedProbe]:
    """Every staged discovery in the allowlisted packs, keyed by probe id.

    Keyed by id and **only ever looked up by id**. Both strings that reach this
    dict from outside — the `probe_path` an artifact recorded, and the
    `probe_id` in a URL — are untrusted, and neither is joined into a path
    here: the dict is built by globbing the packs the operator named on the
    command line, so a traversing id is simply a probe nobody staged.

    The parse itself is `emit.load_prior_discoveries`, the read side of
    `stage_probe`, so an unreadable file is warned about and skipped rather
    than failing the page — one hand-edited staged file must not blank the
    Discoveries list. `stage_probe` writes `<probe.id>.yaml`, so a file's stem
    and its probe's id agree by construction; a file whose stem matches nothing
    it parsed is skipped rather than paired by position.

    First pack wins on a duplicate id, matching the allowlist's own order.
    """
    from evalyn.discovery.emit import STAGING_DIRNAME, load_prior_discoveries

    staged: dict[str, StagedProbe] = {}
    for pack in packs:
        directory = Path(pack) / STAGING_DIRNAME
        by_id = {probe.id: probe for probe in load_prior_discoveries(directory)}
        if not by_id:
            continue
        for path in sorted({*directory.glob("*.yaml"), *directory.glob("*.yml")}):
            probe = by_id.get(path.stem)
            if probe is None:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                # The file parsed a moment ago and is unreadable now: an
                # adoption `git mv` mid-request. Drop the row, never 500.
                continue
            staged.setdefault(path.stem, StagedProbe(
                probe_id=path.stem, path=path, probe=probe, text=text,
                provenance=parse_provenance(text)))
    return staged


def _replay_status(replay: object) -> ReplayStatus:
    """`ReplayResult | ReplaySkipped` flattened onto the four wire states."""
    if getattr(replay, "budget", None) is not None:          # ReplaySkipped
        return (ReplayStatus.skipped_budget if replay.budget
                else ReplayStatus.skipped_disabled)
    return (ReplayStatus.reproduced if getattr(replay, "reproduced", False)
            else ReplayStatus.not_reproduced)


def _replay_view(replay: object) -> ReplayView:
    """`ReplayResult | ReplaySkipped` as the wire's `ReplayView`.

    Read through `getattr` rather than by isinstance-branching, because the two
    artifact types share no field beyond `reason`: a skip has no `trials` and a
    result has no `budget`, and `None` is the wire's word for "this shape did
    not record that". `status` is the one thing both can answer, and
    `_replay_status` is the single place that decides it.
    """
    checks = getattr(replay, "checks", None)
    return ReplayView(
        status=_replay_status(replay),
        reproduced=getattr(replay, "reproduced", None),
        trials=getattr(replay, "trials", None),
        pass_k=_number(getattr(replay, "pass_k", None)),
        pass_at_k=_number(getattr(replay, "pass_at_k", None)),
        expected_trials=getattr(replay, "expected_trials", None),
        checks=[_check_view(c) for c in (checks or []) if isinstance(c, dict)],
        reason=str(getattr(replay, "reason", "") or ""),
    )


def _finding_row(finding, run_id: str, created_at: str,
                 staged: StagedProbe | None = None) -> FindingRow:
    """One `DiscoveryArtifact.findings[]` entry joined onto its staged file.

    The join is not a convenience — it is the only way either half is knowable.
    `confirmed` and the replay verdict exist ONLY in the artifact (staging
    happens before replay, so the YAML cannot carry them); `category` and
    `safety_critical` exist ONLY in the YAML, because the artifact-side
    `Finding` dataclass carries neither field.

    A finding whose staged file is gone — adopted by a `git mv` into `probes/`,
    or deleted after triage — reports `category: None`. `safety_critical` has
    no such spelling: the wire type is `bool`, so an unjoined row falls back to
    `False`. That is the one place this can understate a safety field, it is
    forced by the frozen contract rather than chosen, and it is visible on the
    same row as `category: null`.
    """
    return FindingRow(
        probe_id=Path(finding.probe_path).stem,
        run_id=run_id,
        objective_id=finding.objective_id,
        confirmed=finding.confirmed,
        probe_path=finding.probe_path,
        category=staged.probe.category if staged is not None else None,
        safety_critical=bool(staged.probe.safety_critical) if staged is not None else False,
        persona_id=finding.persona_id,
        playbook_id=finding.playbook_id,
        duplicate_of=finding.duplicate_of,
        duplicate_reason=finding.duplicate_reason,
        replay_status=_replay_status(finding.replay),
        created_at=created_at,
    )


def _tally(raw: object) -> CategoryTally:
    d = raw if isinstance(raw, dict) else {}
    return CategoryTally(
        wins_a=int(d.get("wins_a", 0)), wins_b=int(d.get("wins_b", 0)),
        ties=int(d.get("ties", 0)), unsure=int(d.get("unsure", 0)),
        flips=int(d.get("flips", 0)),
        criteria_judged=int(d.get("criteria_judged", 0)),
        flip_rate=float(d.get("flip_rate", 0.0) or 0.0))


def _hard_metrics(raw: object) -> HardMetrics:
    d = raw if isinstance(raw, dict) else {}
    return HardMetrics(
        latency_mean_a=_number(d.get("latency_mean_a")),
        latency_mean_b=_number(d.get("latency_mean_b")),
        latency_p95_a=_number(d.get("latency_p95_a")),
        latency_p95_b=_number(d.get("latency_p95_b")),
        invariant_failures_a=int(d.get("invariant_failures_a", 0)),
        invariant_failures_b=int(d.get("invariant_failures_b", 0)),
        trials_a=int(d.get("trials_a", 0)), trials_b=int(d.get("trials_b", 0)))


# --------------------------------------------------------------------------
# 5. The index
# --------------------------------------------------------------------------

#: How many parsed artifacts one index keeps. **A bound, not a tuning knob**
#: (deferred finding F8): a cache entry holds the whole raw dict, transcripts
#: (`probes[].trial_records`) included, and the server is a process an operator
#: leaves running all afternoon over a directory that grows all afternoon.
#: Unbounded, one sweep of a large `runs/` pinned every transcript in it into
#: memory for the life of the process.
#:
#: Comfortably above the default page size (50) and above the corpus this was
#: measured against, so the common case — page, click a row, page again — never
#: evicts. R4-6 applies: that corpus size is an observation, never an assertion.
CACHE_MAX_ENTRIES = 128


class RunIndex:
    """A read-only view of one `runs/` directory. Cheap, cached, and unshakeable.

    Instantiate per server, not per request: the cache lives on the instance and
    is keyed on `(path, st_mtime_ns, st_size)`, so a second listing costs one
    `stat` per file and no parsing. Artifacts are immutable once written, which
    is what makes that key sufficient — and bounded at `CACHE_MAX_ENTRIES`,
    least-recently-used first, which is what stops it from being a slow leak.
    """

    def __init__(self, runs_dir: Path | str, packs=None) -> None:
        self.runs_dir = Path(runs_dir)
        #: The start-time pack allowlist, for the discover join only. Optional
        #: because a `RunIndex` over `runs/` alone is still a complete index of
        #: `runs/` — omitting it costs the two fields that live in the staged
        #: YAML (`category`, `safety_critical`) and nothing else.
        self.packs = [Path(p) for p in (packs or ())]
        self._cache: dict[str, tuple[tuple[str, int, int], LoadedArtifact]] = {}

    def staged_probes(self) -> dict[str, StagedProbe]:
        """The staged corpus, re-read on every call.

        Deliberately uncached, unlike artifacts. The cache above is sound
        because an artifact is immutable once written; a staged probe is the
        opposite — adopting one is a `git mv` an operator performs *while* the
        cockpit is open, and the page's whole job is to stop showing it.
        """
        return load_staged_probes(self.packs)

    # -- discovery ---------------------------------------------------------

    def _candidates(self, mode: RunMode | None = None) -> list[tuple[str, Path]]:
        """Every `runs/*.json` whose stem is a run id, newest filename first.

        `is_file()` is *not* applied: a directory or a broken symlink named like
        a run is exactly the hostile shape that must become a degraded row
        rather than disappear from the listing. The mode filter is applied here
        because it is lexical — it costs no reads.

        **The control sidecar has to be excluded by name, not by grammar.**
        `runs/<run_id>.control.json` has stem `<run_id>.control`, and `.` is a
        legal slug character (pack names keep it), so that stem *passes*
        `is_run_id` — the sidecar would otherwise list as a phantom run whose
        artifact never parses. Tightening the grammar is not the fix; it would
        reject the real ids of packs with a dot in their name. The exclusion is
        keyed on `paths.CONTROL_SUFFIX`, so it cannot drift from the writer.
        `.events.jsonl` needs no such rule — the glob already misses it.
        """
        try:
            entries = list(self.runs_dir.glob("*.json"))
        except OSError:
            return []
        found = []
        for path in entries:
            if path.name.endswith(CONTROL_SUFFIX):
                continue
            run_id = path.stem
            if not is_run_id(run_id):
                continue
            if mode is not None and mode_of(run_id) is not mode:
                continue
            found.append((run_id, path))
        found.sort(key=lambda pair: pair[0], reverse=True)
        return found

    def _pending(self, mode: RunMode | None = None) -> list[str]:
        """Every run this cockpit launched that has written no artifact yet.

        The glob above can only see runs that are **over**, because the
        artifact is written once, at the end. So a run in flight had no row at
        all until it finished — an operator who clicked **Runs** during a run
        saw the table exactly as it was before they pressed Launch, which was
        confirmed by execution against the real server. The launcher's own
        sidecar directory is the only record that exists in the meantime.

        Sourced from `runs/.evalyn-ui/`, so a `runs/` this cockpit never
        launched into costs one failed `iterdir` and nothing else.

        Four tests in order, cheapest and most structural first, because each
        one is a claim the next would otherwise have to make on worse evidence:

        1. **the name is a run id** — free, no syscall, and that directory is on
           a real filesystem, so it can hold a `README` as easily as a run;
        2. **the mode matches** — lexical, derived from the id alone;
        3. **the entry is a directory** — the launcher writes a *directory* per
           run (`sidecar_dir`), so a plain file wearing a run id's name is not
           a launched run. Load-bearing rather than tidy: `_sidecar` short-
           circuits on `meta_dir.is_dir()` and would hand back a bare
           `SidecarState()`, whose `present=False` and `launched=True` defaults
           `derive_status` reads as `interrupted` — a row invented out of a
           file nobody wrote as a run;
        4. **no artifact exists yet** — the only one that has to go looking
           elsewhere in `runs/`, so it goes last. It is what stops a run being
           listed twice; the artifact row knows strictly more and always wins.
        """
        try:
            entries = list((self.runs_dir / SIDECAR_DIR_NAME).iterdir())
        except OSError:
            return []
        found = []
        for entry in entries:
            run_id = entry.name
            if not is_run_id(run_id):
                continue
            if mode is not None and mode_of(run_id) is not mode:
                continue
            if not entry.is_dir():
                continue
            if self.artifact_path(run_id) is not None:
                continue
            found.append(run_id)
        return found

    # -- the three-layer load ---------------------------------------------

    def _load(self, path: Path, run_id: str, mode: RunMode) -> LoadedArtifact:
        try:
            st = path.stat()
        except OSError as exc:
            # a broken symlink, or an entry that vanished mid-scan
            return LoadedArtifact(run_id, mode, path,
                                  error=f"artifact is not readable: {_why(exc)}")
        key = (str(path), st.st_mtime_ns, st.st_size)
        cached = self._cache.get(str(path))
        if cached is not None and cached[0] == key:
            # Move to the end: a plain dict preserves insertion order, so
            # "oldest key" and "least recently used" are the same thing only if
            # a hit re-inserts. Without this the bound is FIFO, and the entry a
            # listing sweep evicts is the detail page the operator is watching.
            self._cache[str(path)] = self._cache.pop(str(path))
            return cached[1]
        loaded = _read_artifact(path, run_id, mode)
        # `pop` first: assigning to a key a dict already has keeps its ORIGINAL
        # position, so a just-re-parsed artifact would stay wherever it was and
        # be the next thing evicted. Immutable artifacts never take this path,
        # but a *running* run's artifact is precisely the one that changes on
        # disk — and it is the one being watched.
        self._cache.pop(str(path), None)
        self._cache[str(path)] = (key, loaded)
        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.pop(next(iter(self._cache)))
        return loaded

    # -- process state -----------------------------------------------------

    def _sidecar(self, run_id: str, path: Path) -> SidecarState:
        """Read `.evalyn-ui/<run_id>/meta.json` and the control file, if any.

        One `is_dir()` short-circuits the whole thing for a `runs/` this cockpit
        never launched into, which is the common case and must stay free.

        The file's name and its two keys come from `ui.paths`, so the launcher
        that writes them (Task 19) and this reader import the *same* constants
        rather than agreeing by convention. A shape this build still does not
        recognise degrades to "no process facts" — never to an exception on the
        listing path, and never to a silent `running`.
        """
        if not (self.runs_dir / SIDECAR_DIR_NAME).is_dir():
            return SidecarState()
        try:
            meta_dir = sidecar_dir(self.runs_dir, run_id)
        except ValueError:
            return SidecarState()
        if not meta_dir.is_dir():
            return SidecarState()

        launched, exit_code, unrecognised = True, None, True
        try:
            meta = json.loads(
                meta_path(self.runs_dir, run_id).read_text(encoding="utf-8"))
        except Exception:
            # Failing loudly is not an option: this runs inside `list()`, which
            # must never raise. Failing *silently* is the trap — it would look
            # exactly like a healthy live run. So the reader records that it
            # understood nothing and lets `derive_status` refuse to claim life.
            meta = None
        if isinstance(meta, dict):
            known = {META_LAUNCHED_KEY, META_EXIT_CODE_KEY} & set(meta)
            unrecognised = not known
            launched = bool(meta.get(META_LAUNCHED_KEY, True))
            exit_code = meta.get(META_EXIT_CODE_KEY)
            if not isinstance(exit_code, int) or isinstance(exit_code, bool):
                exit_code = None

        control = None
        try:
            body = json.loads(control_path(path).read_text(encoding="utf-8"))
            if isinstance(body, dict):
                control = ControlAction(body.get("action"))
        except Exception:
            control = None

        events = path.with_name(f"{path.stem}.events.jsonl").exists()
        return SidecarState(present=True, launched=launched, control=control,
                            exit_code=exit_code, events=events,
                            schema_unrecognised=unrecognised)

    # -- rows --------------------------------------------------------------

    def _summary(self, loaded: LoadedArtifact, sidecar: SidecarState) -> RunSummary:
        degraded = loaded.typed is None
        created_at = loaded.salvage.get("created_at") or created_at_from_run_id(
            loaded.run_id)
        return RunSummary(
            run_id=loaded.run_id,
            mode=loaded.mode,
            pack_name=loaded.salvage.get("pack_name"),
            created_at=created_at,
            status=derive_status(loaded, sidecar),
            degraded=degraded,
            degraded_reason=loaded.error if degraded else None,
            capabilities=capabilities_of(loaded),
            judge_usd=None if degraded else _judge_usd(loaded),
            verdict_hint=(verdict_hint_of(loaded.typed)
                          if isinstance(loaded.typed, RunArtifact) else None),
        )

    def _pending_summary(self, run_id: str, sidecar: SidecarState) -> RunSummary:
        """The row for a run that exists only as a sidecar directory.

        Everything an artifact would have answered is `None` rather than a
        zero: nothing has been measured, and `judge_usd=0.0` would be the claim
        that this run has so far cost nothing, which is false the moment the
        first trial is judged. `degraded` is `False` — "not written yet" is a
        different fact from "cannot be read", and the SPA paints the second one
        as an alarm. `pack_name` is `None` because the index has no allowlist:
        the pack a run was started against lives on the launcher, and inventing
        it here would mean guessing.
        """
        return RunSummary(
            run_id=run_id,
            mode=mode_of(run_id),
            pack_name=None,
            created_at=created_at_from_run_id(run_id),
            status=derive_status(None, sidecar),
            degraded=False,
            degraded_reason=None,
            capabilities=Capabilities(transcripts=False, trial_records=False,
                                      hard_metrics=False),
            judge_usd=None,
            verdict_hint=None,
        )

    def list(self, *, mode: RunMode | None = None, pack: str | None = None,
             status: RunStatus | None = None, limit: int = 50,
             before: str | None = None) -> list[RunSummary]:
        """One page of the runs table, `(created_at, run_id)` descending.

        `before` is the opaque cursor from `make_cursor` and is compared as the
        **parsed tuple**: one `created_at` can be a prefix of another and the
        separator sorts after the character that would have decided it, so a
        string comparison of the joined form can invert the order.

        Raises for a caller error — a malformed cursor — and, today, for one
        class of directory content too. **The stronger claim this docstring
        used to make is false and was measured false**: a readable artifact
        whose `trial_records` holds a non-dict entry reaches `capabilities_of`,
        where `hard_metrics` calls `rec.get(...)` over the unfiltered list and
        raises `AttributeError`. Unlike `get`, `list` has no per-row guard, so
        that single file 500s the **whole** listing rather than degrading one
        row.

        Not reachable from engine output — `run.py` always appends a dict, and
        0 of 737 records across 87 real artifacts are non-dict — but the surface
        is "any JSON in `runs/`", not "anything Evalyn wrote". Parked
        deliberately: the honest fix is a per-row guard in `list`, mirroring the
        one `get` already has, and that is structural work this task's review
        budget excluded rather than work anyone judged unnecessary.
        """
        cursor = parse_cursor(before) if before is not None else None

        def wanted(row: RunSummary) -> bool:
            if pack is not None and row.pack_name != pack:
                return False
            if status is not None and row.status is not status:
                return False
            if cursor is not None and (row.created_at, row.run_id) >= cursor:
                return False
            return True

        rows: list[RunSummary] = []
        for run_id, path in self._candidates(mode):
            loaded = self._load(path, run_id, mode_of(run_id))
            row = self._summary(loaded, self._sidecar(run_id, path))
            if wanted(row):
                rows.append(row)

        # Two sequences, one page. The filters and the sort are applied to both
        # through the same code, so a run in flight cannot appear on a page the
        # operator has narrowed away from it — and cannot jump the ordering at
        # the seam where the two sources meet.
        for run_id in self._pending(mode):
            row = self._pending_summary(
                run_id, self._sidecar(run_id, self.runs_dir / f"{run_id}.json"))
            if wanted(row):
                rows.append(row)

        rows.sort(key=lambda r: (r.created_at, r.run_id), reverse=True)
        return rows[:limit] if limit is not None else rows

    # -- detail ------------------------------------------------------------

    def artifact_path(self, run_id: str) -> Path | None:
        """Where this run's artifact is, or `None` if there is nothing there.

        Validates against the frozen grammar *before* joining, so a hostile path
        parameter never reaches the filesystem — traversal is impossible by
        construction (the charset admits no `/`), and this makes it impossible
        by policy too.
        """
        if not is_run_id(run_id):
            return None
        path = self.runs_dir / f"{run_id}.json"
        return path if (path.exists() or path.is_symlink()) else None

    def get(self, run_id: str) -> RunDetail:
        """The detail view. Degrades exactly like a row rather than 404-ing.

        An artifact this build cannot parse is a *greyed detail page* with a
        reason, not a missing resource: the run happened, and telling an
        operator "not found" about a file they can see on disk is a lie.
        `RunNotFound` means there is genuinely nothing at that id.
        """
        path = self.artifact_path(run_id)
        if path is None:
            raise RunNotFound(run_id)
        mode = mode_of(run_id)
        loaded = self._load(path, run_id, mode)
        sidecar = self._sidecar(run_id, path)
        summary = self._summary(loaded, sidecar)
        typed = loaded.typed
        raw = loaded.raw or {}

        detail = RunDetail(
            **summary.model_dump(),
            pack_hash=_text(raw.get("pack_hash")),
            judge_model=_text(raw.get("judge_model")),
            log_path=_text(raw.get("log_path")),
            rubric_scores_untrusted=bool(raw.get("rubric_scores_untrusted", False)),
            total_unsure_trials=(raw.get("total_unsure_trials")
                                 if isinstance(raw.get("total_unsure_trials"), int)
                                 else None),
            cancelled=cancelled_by(loaded, sidecar),
        )
        # The mode-specific half is where the WIRE models are validated, and
        # that is a second, later chance to fail than `_read_artifact`'s
        # (F10). An artifact can load perfectly and still carry a *value* the
        # contract does not admit — a check with `tier: 0`, `4` or `null` —
        # and `ValidationError` out of `.get()` becomes a 500. A 500 is the one
        # answer this module may not give: the run happened, the operator can
        # see the file, and the contract is degradation, not failure. So the
        # detail greys out with a reason, exactly as a shape-level surprise
        # already does, and the endpoint has nothing left to get wrong.
        try:
            if isinstance(typed, RunArtifact):
                # Paired positionally, because that is the pairing
                # `RunArtifact.from_dict` itself made: it builds one
                # `ProbeResult` per raw entry, in order. `_probe_row` re-checks
                # the id and treats anything it cannot pair as "no reading", so
                # a raw `probes` that is missing, is not a list, or runs short
                # costs a gap in the chart rather than an `IndexError` out of a
                # detail read. (None of those shapes can reach here today —
                # each one fails the typed load first — which is why the
                # fallback may be conservative for free.)
                raw_probes = raw.get("probes")
                raw_probes = raw_probes if isinstance(raw_probes, list) else []
                return replace_detail(detail, probes=[
                    _probe_row(probe, raw_probes[i] if i < len(raw_probes) else None)
                    for i, probe in enumerate(typed.probes)])
            if isinstance(typed, CompareArtifact):
                return replace_detail(detail, compare=_scoreboard(run_id, typed))
            if isinstance(typed, DiscoveryArtifact):
                return replace_detail(
                    detail,
                    discovery=_discovery(run_id, typed, self.staged_probes()))
        except Exception as exc:
            return replace_detail(
                detail, degraded=True, judge_usd=None,
                degraded_reason=f"artifact could not be rendered: {_why(exc)}")
        return detail


def replace_detail(detail: RunDetail, **changes) -> RunDetail:
    """`dataclasses.replace` for a pydantic model, revalidated.

    Building the mode-specific half separately keeps `get` readable, and going
    back through the constructor means the `extra="forbid"` contract is enforced
    on the composed object rather than only on the base.
    """
    return RunDetail(**{**detail.model_dump(), **changes})


def _scoreboard(run_id: str, art: CompareArtifact) -> Scoreboard:
    return Scoreboard(
        run_id=run_id, pack_name=art.pack_name, created_at=art.created_at,
        label_a=art.label_a, label_b=art.label_b,
        source_a=art.source_a, source_b=art.source_b,
        created_at_a=art.created_at_a, created_at_b=art.created_at_b,
        categories={k: _tally(v) for k, v in (art.categories or {}).items()},
        hard_metrics={k: _hard_metrics(v)
                      for k, v in (art.hard_metrics or {}).items()},
        excluded_pairs=art.excluded_pairs,
        judge_usd=_number(art.judge_usd),
        rubric_scores_untrusted=art.rubric_scores_untrusted)


def _discovery(run_id: str, art: DiscoveryArtifact,
               staged: dict[str, StagedProbe] | None = None) -> DiscoverySummary:
    """The discover half of a `RunDetail`.

    `staged` is the join corpus from `RunIndex.staged_probes`. It is optional
    so a `RunIndex` built without a pack allowlist still renders the run; the
    cost of omitting it is that `category` and `safety_critical` — which live
    only in the staged YAML — fall back to their contract defaults on every
    row. See `_finding_row`.
    """
    staged = staged or {}
    return DiscoverySummary(
        agent_model=art.agent_model, rubric_judge_model=art.rubric_judge_model,
        eval_status=art.eval_status, error_count=art.error_count,
        sessions_total=art.sessions_total, confirmed_count=art.confirmed_count,
        live_spend_usd=_number(art.live_spend_usd),
        reconciled_spend_usd=_number(art.reconciled_spend_usd),
        effective_spend_usd=_number(art.effective_spend_usd),
        budget_exhausted=art.budget_exhausted, partial=art.partial,
        objectives=list(art.objectives),
        findings=[_finding_row(f, run_id, art.created_at,
                               staged.get(Path(f.probe_path).stem))
                  for f in art.findings])


# --------------------------------------------------------------------------
# 6. Reading one file — the layer boundary where nothing may escape
# --------------------------------------------------------------------------

def _why(exc: BaseException) -> str:
    """A one-line, path-free reason. `strerror` beats `str(exc)`, which repeats
    the filename the caller already knows and would leak it into a tooltip."""
    return getattr(exc, "strerror", None) or f"{type(exc).__name__}: {exc}"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _salvage_of(raw: dict) -> dict:
    """The shallow read: exactly what a greyed row needs, type-checked.

    Nothing here trusts the body's *shape* — a `pack_name` that is a list is
    simply absent, because a row that renders `['a']` as a pack name is worse
    than one that renders nothing.
    """
    salvage: dict = {}
    if isinstance(raw.get("pack_name"), str):
        salvage["pack_name"] = raw["pack_name"]
    if isinstance(raw.get("created_at"), str):
        salvage["created_at"] = raw["created_at"]
    if isinstance(raw.get("probes"), list):
        salvage["probe_count"] = len(raw["probes"])
    if isinstance(raw.get("findings"), list):
        salvage["finding_count"] = len(raw["findings"])
    return salvage


def _read_artifact(path: Path, run_id: str, mode: RunMode) -> LoadedArtifact:
    """The three layers. Every one catches, and the reason survives the fall.

    `except Exception` at the parse and typed layers is deliberate rather than
    lazy: this is the boundary between a hostile directory and a web response,
    the loaders are third-party-ish code over untrusted bytes, and the contract
    is that a row always appears. The exception's type goes into the reason so
    an operator sees *what* broke, not just that something did.
    """
    partial = LoadedArtifact(run_id, mode, path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return replace(partial, error=f"artifact could not be read: {_why(exc)}")
    except UnicodeDecodeError:
        return replace(partial, error="artifact is not valid UTF-8 text")

    try:
        raw = json.loads(text)
    except Exception as exc:
        return replace(partial, error=f"artifact is not valid JSON: {_why(exc)}")
    if not isinstance(raw, dict):
        return replace(partial,
                       error="artifact is not a JSON object (found "
                             f"{type(raw).__name__})")

    salvage = _salvage_of(raw)
    try:
        typed = _TYPED_LOADER[mode](raw)
    except Exception as exc:
        return replace(partial, raw=raw, salvage=salvage,
                       error=f"artifact does not match the {mode.value} schema: "
                             f"{_why(exc)}")
    return replace(partial, raw=raw, salvage=salvage, typed=typed)


def _judge_usd(loaded: LoadedArtifact) -> float | None:
    """Evalyn's OWN spend, absent-vs-null preserved.

    Read from `raw` and not the dataclass: `RunArtifact.judge_usd` defaults to
    `0.0`, so a pre-metering artifact would otherwise claim it measured a spend
    of zero. `discover` records the figure under a different name — the
    `max(live, reconciled)` the artifact already computed — and that is all
    Evalyn's own spend too.
    """
    raw = loaded.raw or {}
    if loaded.mode is RunMode.discover:
        recorded = raw.get("effective_spend_usd")
        if recorded is None:
            live, reconciled = raw.get("live_spend_usd"), raw.get("reconciled_spend_usd")
            pair = [v for v in (_number(live), _number(reconciled)) if v is not None]
            return max(pair) if pair else None
        return _number(recorded)
    return _number(raw.get("judge_usd"))
