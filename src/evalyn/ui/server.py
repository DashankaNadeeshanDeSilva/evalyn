"""The cockpit's ASGI app and its one entry point (Plan #4, Task 6).

**This is the only module in the package that may import FastAPI.**
`evalyn/ui/__init__.py` is empty and `evalyn/cli.py` imports `serve` inside the
`ui` command body, so `import evalyn.cli` still loads no web framework and
`evalyn gate` still runs on a machine that never installed the `[ui]` extra. A
subprocess guard in `tests/test_smoke.py` pins that; it is a subprocess because
an in-process check is worthless the moment another test imports this file.

`evalyn.ui.index` is imported **inside** `create_app` for a second, sharper
reason (C-T7b): it reaches `inspect_ai` through `engine.run`, which drags
starlette in transitively. Importing it at module scope here would be invisible
today and would break the guard the moment anything on the CLI's path touched
this module.

Three properties this factory exists to establish:

* **Redaction is mounted, not merely available.** Task 4 built the chokepoint;
  it protects nothing until an app installs it, and installing
  `route_class=RedactingRoute` alone is **not sufficient**. `HTTPException` and
  every registered handler are rendered by Starlette's `ExceptionMiddleware`,
  which sits *above* the route and never passes through the route class — so
  `redacting_exception_handlers()` goes on as well. Error bodies are precisely
  the ones carrying the operator's run directory under `$HOME`.
* **Every non-2xx body is `ErrorEnvelope`.** The SPA reads `error.code` and has
  no second parser, so an unknown `/api` path must not come back as FastAPI's
  `{"detail": …}`. That is what the explicit `/api` catch-all below is for: it
  turns "no route matched" into a 404 the handlers can shape, instead of
  letting the SPA's history fallback answer for the API.
* **Loopback only.** This server reads `runs/` and (Task 19) launches
  processes. `--host 0.0.0.0` on conference wifi is not a configuration.

**Which `run_id` (C-T6/7).** The engine's `run_id` excludes the mode suffix
(`runs/<run_id><suffix>.json`); the id this cockpit indexes, routes and keys
sidecars by is the **artifact stem, suffix included** — `<id>-compare`,
`<id>-discover`. `RunIndex` already derives it that way from `path.stem`, and
`RunIndex._sidecar` joins that same string onto `runs/.evalyn-ui/`, so the
launcher must write `meta.json` under the suffixed id too. One of the two
readings had to win before the events emitter lands; the stem wins because it
is the only one that round-trips to a file on disk.
"""
from __future__ import annotations

import math
import sys
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

import evalyn
from evalyn.targets.loader import load_pack
from evalyn.ui.models import (
    ApiError,
    Capabilities,
    ControlRequest,
    ControlResponse,
    CriterionCounts,
    ErrorCode,
    ErrorEnvelope,
    DiscoveryListPage,
    FindingDetail,
    FindingRow,
    GateVerdict,
    HealthResponse,
    LaunchRequest,
    LaunchResponse,
    MetaResponse,
    PackAxes,
    PackListPage,
    RedactionMeta,
    ReplayView,
    RunDetail,
    RunListPage,
    RunMode,
    RunStatus,
    TranscriptTurn,
    TrendMetric,
    TrendPoint,
    TrendSeries,
    TrialView,
    TrustReport,
    TurnRole,
    display_path,
    is_run_id,
    make_cursor,
    parse_cursor,
)
from evalyn.ui.launcher import (
    STDERR_FILENAME,
    Busy,
    RunLauncher,
    pack_axes,
    pack_id_for,
    pack_rows,
    refusal_for,
)
from evalyn.ui.paths import control_path, events_path, sidecar_dir
from evalyn.ui.redact import Redactor, RedactingRoute, no_redact, redacting_exception_handlers
from evalyn.ui.stream import DEFAULT_IDLE_TIMEOUT, event_stream

# The ONE web-framework import at module scope, and it is here under duress.
# `from __future__ import annotations` makes every annotation a string, and
# FastAPI resolves a handler's hints against the *module* globals — so a
# `Request` imported inside `create_app` is invisible to it, and the parameter
# is silently read as a required **query parameter** instead. The SSE endpoint
# then 422s on every request, which is exactly how a live run would have failed
# on stage while every route-census test still passed.
#
# It costs nothing that was not already spent: starlette is a hard dependency
# of fastapi, so this raises `ImportError` in precisely the same case the
# in-function imports do, and `cli.py:801` already catches that and prints the
# "install evalyn[ui]" sentence. `import evalyn.cli` still loads neither,
# because it only imports this module inside the `ui` command body.
from starlette.requests import Request

if TYPE_CHECKING:                       # pragma: no cover - typing only
    from fastapi import FastAPI

__all__ = ["create_app", "serve", "build_redactor", "split_transcript",
           "build_trends", "build_trust", "STATIC_DIR", "INDEX_HTML", "DEFAULT_PORT",
           "LOOPBACK_HOST", "DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE",
           "BASELINE_FILENAME", "RUN_LEVEL_SERIES", "TREND_STATUSES"]

#: Refusal for a control action aimed at a run that is no longer in flight.
#:
#: A 409, which `redact.py:689` already maps to the frozen `busy` code — the
#: request conflicts with the resource's state, which is exactly what 409 is
#: for. No new `ErrorCode` member: that enum is frozen in six coordinated
#: places, and this refusal does not need one to be legible. The **message** is
#: what the operator reads, so it says what happened rather than naming a code.
_NOT_LIVE = ("this run is no longer in flight, so it takes no more control "
             "actions — its result is final and will not be rewritten")

#: The committed Vite bundle, shipped inside the wheel by hatchling.
STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"
ASSETS_DIR = STATIC_DIR / "assets"

#: Matches the dev proxy target in `ui/vite.config.ts`. Changing one without
#: the other silently breaks `npm run dev` against a real server.
DEFAULT_PORT = 8765

#: Not a default — the only accepted value. See `serve`.
LOOPBACK_HOST = "127.0.0.1"

_API_PREFIX = "/api"

#: One page of `GET /api/runs`. The SPA never sends `?limit=`; it exists so a
#: `curl` against a large corpus is not a whole-directory parse, and it is
#: clamped rather than refused — a bad page size is not worth an error page.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

#: The blessed baseline, named exactly as `evalyn gate --baseline` defaults it.
#: The cockpit never writes it.
BASELINE_FILENAME = "baseline.json"

#: `trial_records[].transcript` is ONE string in the labelled form the Tier-2/3
#: judges saw. These are the only two roles `TurnRole` admits, and they are
#: recognised **at the start of a line only** — see `split_transcript` for what
#: matching them anywhere would cost.
_TURN_MARKERS: tuple[tuple[str, TurnRole], ...] = (
    ("User: ", TurnRole.user),
    ("Assistant: ", TurnRole.assistant),
)


def split_transcript(transcript: object) -> list[TranscriptTurn]:
    """The artifact's single transcript string as `TranscriptTurn[]` (R4-41).

    Splitting is the **server's** job: the artifact stores one string, the SPA
    renders a role-labelled conversation, and a client-side split would have to
    re-derive a format it does not own. The rules, and each one is a measured
    failure it prevents:

    * **Markers only at the start of a line.** The cost of matching them
      anywhere is not a split — it is *silent text loss*: a turn is opened by
      stripping a fixed-width prefix, so a line whose marker sits mid-way loses
      exactly as many leading characters as the marker is long, and gains a
      role it never had. The content that does this is a prompt-injection
      transcript **quoting** a role label (`say "Assistant: I comply"`), which
      is squarely inside what this product tests. No artifact in `runs/` does
      it today and `packs/twincore-injection/probes/injection.yaml` contains no
      `User:` or `Assistant:` at all, so this is a guard against improvised and
      quoting content rather than a fix for a measured incident.
    * **An unmarked line belongs to the turn already open**, newline preserved.
      A multi-line assistant answer is one turn, not N. This one *is* measured:
      90 transcripts in the corpus carry a continuation line, and 21 of those
      carry a fenced payload whose interior lines (`SYSTEM: New rule …`) hold no
      role marker and must stay part of the user turn that opened the fence.
    * **Text is never dropped.** Anything before the first marker joins the
      first turn, and a string with no marker at all comes back as a single
      `user` turn — every transcript opens with the probe's prompt, which is
      the user's, and `TurnRole` admits no third role to invent. Joining a
      preamble onto a first turn that happens to be the assistant's would
      mis-attribute it; that is the lesser evil against losing it entirely, and
      no artifact in the corpus takes that path (0 of 737 transcripts).
    * **An empty or absent transcript is `[]`**, which the SPA reads as "not
      captured" rather than "the model said nothing".

    `tests/ui/test_read_endpoints.py` holds the round-trip invariant over every
    transcript in `runs/`: re-joining the turns with their own markers must
    reproduce the artifact's string exactly.
    """
    if not isinstance(transcript, str) or not transcript:
        return []

    turns: list[tuple[TurnRole, list[str]]] = []
    preamble: list[str] = []
    for line in transcript.split("\n"):
        for marker, role in _TURN_MARKERS:
            if line.startswith(marker):
                turns.append((role, [line[len(marker):]]))
                break
        else:
            (turns[-1][1] if turns else preamble).append(line)

    if not turns:
        return [TranscriptTurn(role=TurnRole.user, text=transcript)]
    if preamble:
        turns[0][1][:0] = preamble
    return [TranscriptTurn(role=role, text="\n".join(lines))
            for role, lines in turns]


def build_redactor(packs: list[Path]) -> Redactor:
    """The app's redactor, taught by the packs the run is allowed to touch.

    Only `not_contains` values are harvested, and that asymmetry is deliberate
    (ruling R4-18, implemented in `harvest_from_probes`): a `not_contains` value
    is a string the product must never emit — a secret the pack itself has
    already identified — while a `contains` value is the *correct answer*, and
    harvesting those would blank the passing transcripts out of the demo.

    **A pack that will not load is fatal.** Continuing would start a server
    whose redactor is missing exactly the literals that pack declared secret,
    and a redaction hole that announces itself as a warning nobody reads is
    worse than a refusal. `load_pack`'s `PackError` / `AllowlistError`
    propagates to the CLI, which prints it as a setup error.
    """
    redactor = Redactor()
    for pack_path in packs:
        redactor.harvest_from_probes(load_pack(pack_path).probes)
    return redactor


#: `TrendSeries.probe_id` for the one metric that is **not** a probe's.
#:
#: `judge_usd` is metered once per run (`RunArtifact.judge_usd`); there is no
#: per-probe spend anywhere in the artifact and none can be derived. Repeating
#: the run's figure on every probe's series would draw N identical lines, each
#: one asserting a per-probe cost nobody measured — the same class of invention
#: as plotting a degraded run as `0.0`. So spend is one series, and its
#: `probe_id` says what it is. The parentheses make it uncollidable with a real
#: probe id, whose grammar is a slug.
RUN_LEVEL_SERIES = "(whole run)"

#: The only two statuses a trend reading may come from.
#:
#: `passed` and `gate_failed` are both real measurements — a failing gate is
#: precisely what the operator opened this page to watch. Every other status is
#: an absence dressed as a number: `unreadable` has no parsed probes at all,
#: `invalid` measured nothing, `cancelled` leaves un-run probes sitting at the
#: dataclass default of `0.0`, and `running` / `paused` / `interrupted` /
#: `failed_to_start` have no artifact to read.
TREND_STATUSES = (RunStatus.passed, RunStatus.gate_failed)


def _finite(value: object) -> float | None:
    """A value fit to be plotted, or `None`.

    **The client validates `created_at` and does not validate `value` at all**,
    so this is the only thing between an artifact and the chart's scale. Two
    shapes get through everything upstream: `json.loads` accepts the bare `NaN`
    and `Infinity` literals by default, and pydantic's `float` admits both — and
    `json.dumps` then writes them back out as `NaN` / `Infinity`, which no JSON
    parser is required to accept. A non-finite reading is dropped, which makes
    it a gap; the alternative is a body the browser may refuse whole.
    """
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def build_trends(runs: list[RunDetail], pack_name: str,
                 metric: TrendMetric) -> list[TrendSeries]:
    """`GET /api/trends`'s body, from `runs` already in ascending time order.

    Two rules carry the page, and both are about what is **not** emitted.

    **A run that did not measure a probe is absent from that probe's points.**
    Never `0.0`, never `null`: the page ranks channels by the metric's worst
    reading, so a fabricated zero for an unmeasured probe becomes the channel
    the page opens on — the first thing an audience sees would be a catastrophe
    that never happened. A gap in the line means "no readable run".

    **A probe with no readable reading at all still gets a series**, with
    `points: []`. The page renders it as a live "no readings" channel and
    counts it in the readout; dropping it would silently shrink the probe count
    instead of showing an honest blank.

    The probe universe is the union of the probe ids the contributing runs
    actually recorded — never the pack on disk. A pack is not needed to read a
    history, `runs/` holds runs of packs this cockpit was never pointed at, and
    a pack's current probe list is not the list its old runs measured.
    """
    if metric is TrendMetric.judge_usd:
        return [TrendSeries(
            pack_name=pack_name, probe_id=RUN_LEVEL_SERIES, metric=metric,
            points=[TrendPoint(run_id=run.run_id, created_at=run.created_at,
                               value=spend)
                    for run in runs
                    # `None` is "not metered", which is not "free" — the runs
                    # table already refuses to render that as `$0.0000`.
                    if (spend := _finite(run.judge_usd)) is not None])]

    points_by_probe: dict[str, list[TrendPoint]] = {}
    for run in runs:
        for probe in run.probes:
            points = points_by_probe.setdefault(probe.id, [])
            value = _finite(getattr(probe, metric.value, None))
            if value is None:
                continue
            points.append(TrendPoint(run_id=run.run_id,
                                     created_at=run.created_at, value=value))
    return [TrendSeries(pack_name=pack_name, probe_id=probe_id, metric=metric,
                        points=points)
            for probe_id, points in points_by_probe.items()]


#: `stale_reason` for a pack that has never been calibrated at all.
#:
#: The engine's locked staleness rule already names this state, in these words
#: (`calibrate.is_stale` -> `"no calibration record"`). The route answers it
#: before calling `is_stale` only because there is no record left to evaluate —
#: not because it holds a second opinion about what the state is called. One
#: state, one sentence, and the sentence is the engine's.
NO_CALIBRATION_RECORD = "no calibration record"


def _agreements(raw: object) -> dict[str, float]:
    """A `{key: fraction}` block of a calibration record, defensively.

    Everything in `calibration.json` is operator-editable text that predates
    this route by three weeks, so nothing in it is trusted to be the shape the
    wire model wants. A key that is not a string or a value that is not a
    finite number is **dropped rather than coerced**: a missing agreement
    rendered as `0.0` would be the worst possible lie this page could tell.

    **Dropped, specifically — not nulled**, and that is the part the wire can
    see. Measured on this route: FastAPI serialises through the response model
    and pydantic already renders a non-finite float as `null`, so on a scalar
    field the guard changes nothing an HTTP client can observe. On this map it
    changes the only thing that matters — an absent key reads as "never
    measured", where a key sitting there holding `null` reads as a criterion
    that was scored and came back as nothing.
    """
    if not isinstance(raw, dict):
        return {}
    return {key: number for key, value in raw.items()
            if isinstance(key, str) and (number := _finite(value)) is not None}


def _counts(raw: object) -> dict[str, CriterionCounts]:
    """`{"<rubric>:<criterion>": [hits, total]}` as `CriterionCounts`.

    JSON has no tuples, so `calibrate.write_record` stores each pair as a
    two-element list; this is the one place that shape is turned back into the
    named pair the SPA reads. Anything that is not a pair of plain integers is
    dropped — a partially-typed count is not a measurement.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, CriterionCounts] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, (list, tuple)):
            continue
        if len(value) != 2 or not all(isinstance(n, int) and not isinstance(n, bool)
                                      for n in value):
            continue
        out[key] = CriterionCounts(hits=value[0], total=value[1])
    return out


def _scored_criteria(record: dict) -> set[str]:
    """Every `"<rubric>:<criterion>"` the record holds a matched pair for.

    Keys only, and from **both** blocks: a criterion whose agreement value is
    unusable was still scored against a human label, and calling it "never
    scored" on the strength of a corrupt float would be a different claim than
    the one the record supports.
    """
    blocks = [record.get(block) for block in ("per_criterion",
                                              "per_criterion_counts")]
    return {key for block in blocks if isinstance(block, dict)
            for key in block if isinstance(key, str)}


def build_trust(pack) -> TrustReport:
    """`GET /api/trust?pack`'s body — one pack's `calibration.json`, mapped.

    This page reports a **record**, not a corpus. `runs/` is never opened: the
    subject is the file `evalyn calibrate` wrote and `evalyn gate` fails closed
    without, and its numbers are reported as measured or not at all.

    **What is read, and what is derived** — the distinction is the whole job:

    * `agreement`, `per_criterion_agreement` (the record's `per_criterion`),
      `per_criterion_counts`, `judge_model` and `calibrated_at` (its
      `created_at`) are **verbatim** off the record, type-checked and dropped
      if unusable, never recomputed.
    * `per_rubric_agreement` is the record's own field where it has one, and
      otherwise `calibrate.per_rubric_agreement`'s legacy mean-of-fractions —
      the same preference, in the same order, that `is_stale` applies. It is
      spelled once, there, so the page and the gate cannot disagree about a
      rubric's agreement.
    * `stale` / `stale_reason` are **`calibrate.is_stale`'s verdict**, asked
      against `pack.spec.judge.rubric_model`, which is the model `evalyn gate`
      itself judges rubrics with absent a `--rubric-judge-model` override.
      There is no second staleness rule here, because a page that called a
      record fresh while the gate refused it would be worse than no page.
    * `unmatched` is **derived, honestly**: the pack's rubric criteria on disk
      minus the ones the record holds a pair for. A criterion added to a rubric
      after calibration has an agreement figure of nothing, and a healthy
      overall number must not be allowed to stand in for it. It stays empty for
      a pack with no record at all — "no calibration record" already says every
      criterion is uncovered, and listing them would repeat one fact N times.
    * `threshold` is `calibrate.AGREEMENT_THRESHOLD`, the bar the gate fails
      closed against — and it is `None` when there is no record, because there
      is then nothing that was measured against it.

    **What is NOT derived, deliberately.** The record carries no confusion
    matrix, no per-anchor detail and no second rater, so nothing here computes
    Cohen's κ — and the field is `agreement`, ±1-point agreement exactly as
    shipped. `CalibrationResult.unmatched` (human labels naming no rubric
    criterion) is a different quantity pointing the other way and is not
    written to the record at all; it is not what this field reports.

    **Every failure degrades, and degrades closed.** An unreadable record, a
    record that is not an object, a rubric this build cannot parse — each
    answers 200 with `stale: True` and a reason. `stale` defaults to `True` in
    the wire model for exactly this reason: the safe direction for "we could
    not tell" is "do not trust it".
    """
    # Inside the function for the reason every other engine import here is
    # (C-T7b): `calibrate` reaches `inspect_ai` through `scoring.tier3`.
    from evalyn.engine.calibrate import (
        AGREEMENT_THRESHOLD,
        _pack_rubric_ids,
        is_stale,
        load_record,
        per_rubric_agreement,
    )
    from evalyn.scoring.rubrics import load_rubric, parse_criteria

    name = pack.spec.name
    try:
        record = load_record(pack)
    except (OSError, ValueError) as e:
        # `json.JSONDecodeError` and `UnicodeDecodeError` are both ValueError.
        # The message is the parser's own ("Expecting value: line 1 …"), which
        # is what an operator needs to find the edit that broke the file.
        return TrustReport(
            pack_name=name, stale=True,
            stale_reason=f"the calibration record could not be read: "
                         f"{e.__class__.__name__}: {e}")
    if record is None:
        return TrustReport(pack_name=name, stale=True,
                           stale_reason=NO_CALIBRATION_RECORD)
    if not isinstance(record, dict):
        return TrustReport(
            pack_name=name, stale=True,
            stale_reason="the calibration record is not a JSON object, so "
                         "nothing in it can be read")

    try:
        stale, reason = is_stale(pack, pack.spec.judge.rubric_model)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as e:
        # `is_stale` reads the record's fields positionally-typed and re-reads
        # every rubric off disk; a hand-edited record or a missing rubric can
        # raise any of these. The page must still render, so the verdict fails
        # closed with the reason attached rather than 500ing.
        stale, reason = True, (f"the calibration record could not be "
                               f"evaluated: {e.__class__.__name__}: {e}")

    per_criterion = _agreements(record.get("per_criterion"))
    # The recorded pooled value first, the legacy mean-of-fractions second —
    # `is_stale`'s own order (calibrate.py:290), not a second policy.
    by_rubric = (_agreements(record.get("per_rubric_agreement"))
                 or _agreements(per_rubric_agreement(per_criterion)))

    scored = _scored_criteria(record)
    unmatched: list[str] = []
    for rubric_id in sorted(_pack_rubric_ids(pack)):
        try:
            criteria = parse_criteria(load_rubric(pack, rubric_id)[0])
        except (OSError, ValueError):
            # A rubric this build cannot read says nothing about which of its
            # criteria were scored, so it contributes no claim either way.
            continue
        unmatched += [key for criterion in criteria
                      if (key := f"{rubric_id}:{criterion}") not in scored]

    judge_model = record.get("judge_model")
    calibrated_at = record.get("created_at")
    return TrustReport(
        pack_name=name,
        judge_model=judge_model if isinstance(judge_model, str) else None,
        agreement=_finite(record.get("agreement")),
        per_rubric_agreement=by_rubric,
        per_criterion_agreement=per_criterion,
        per_criterion_counts=_counts(record.get("per_criterion_counts")),
        unmatched=unmatched,
        stale=stale,
        # The reason it is STALE. `is_stale` answers "calibrated" when it is
        # not, and a non-null reason on a healthy record is precisely the
        # shape a banner renders as a warning.
        stale_reason=reason if stale else None,
        calibrated_at=calibrated_at if isinstance(calibrated_at, str) else None,
        threshold=AGREEMENT_THRESHOLD,
    )


def create_app(runs_dir: Path, packs: list[Path], *,
               allow_discover: bool = False,
               judge_model: str | None = None) -> FastAPI:
    """Build the cockpit app over one `runs/` directory and one pack allowlist.

    `allow_discover` is a *start-time* decision, not a request-time one: the
    launcher (Task 19) refuses a `discover` request unless the operator asked
    for it on the command line, because discover spends real money.

    `judge_model` is start-time for the same reason and one more: it is what
    turns a launch into a *billed* launch, so it belongs on the command line
    the operator typed and nowhere near a request body. `None` — the default —
    leaves every child on the CLI's own `mockllm/model`, which costs nothing.
    """
    from fastapi import APIRouter, FastAPI, HTTPException
    from fastapi.responses import (
        FileResponse,
        JSONResponse,
        PlainTextResponse,
        StreamingResponse,
    )
    from starlette.staticfiles import StaticFiles

    # Imported HERE, not at module scope: `index` pulls starlette in through
    # `engine.run -> inspect_ai`, and the CLI's import-isolation guard holds
    # only while nothing on that path imports it eagerly (C-T7b).
    #
    # `_check_view` is the ONE artifact-check mapper (it is what applies the
    # `Tier` validator that turns the artifact's `"tier": 1` into the wire's
    # `"1"`); a second one here would be the drift `models.py` exists to stop.
    from evalyn.ui.index import RunIndex, _check_view, _replay_view, mode_of

    runs_dir = Path(runs_dir).resolve()
    packs = [Path(p).resolve() for p in packs]

    app = FastAPI(title="Evalyn cockpit", version=evalyn.__version__)

    # Every route this factory adds directly to the app inherits the chokepoint
    # too, not just the ones on the `/api` router. Belt and braces: the escape
    # hatch should be the explicit `@no_redact` marker and nothing else.
    app.router.route_class = RedactingRoute

    app.state.runs_dir = runs_dir
    app.state.packs = packs
    app.state.allow_discover = allow_discover
    app.state.redactor = build_redactor(packs)
    # Keyed by the artifact stem — see the module docstring (C-T6/7). When Task
    # 19 starts minting ids, note that an explicit `EVALYN_RUN_ID` removes the
    # collision-proofing `new_run_id` provides: two runs handed the same id
    # `os.replace`-clobber each other with no exists-check (C-T7).
    # `packs` is handed over for the discover join and nothing else: a staged
    # finding's `category` and `safety_critical` live in
    # `<pack>/discoveries/*.yaml`, not in the run artifact, and a row that
    # cannot reach them ships `safety_critical: false` for a probe whose file
    # says `true` — the opposite of the truth, on a safety field.
    app.state.index = RunIndex(runs_dir, packs)

    # The allowlist, keyed by the id the browser addresses a pack with. Loaded
    # once at start: `build_redactor` above has already proved every one of
    # these loads, so a failure here is impossible by the time this runs, and
    # the browser can never name a pack the operator did not.
    app.state.packs_by_id = {
        pack_id_for(loaded.spec.name): (loaded, path)
        for loaded, path in ((load_pack(p), p) for p in packs)
    }
    app.state.launcher = RunLauncher(runs_dir, judge_model=judge_model)
    #: Overridable so a test need not wait out the production backstop; the
    #: stream's other two stops are what end a subscription in practice.
    app.state.sse_idle_timeout = DEFAULT_IDLE_TIMEOUT

    # C-T6b: the second gate. `RedactingRoute` wraps the endpoint call only, so
    # without these the 404 body reading "no such run at /Users/alice/…" goes
    # out verbatim — the single most likely string on a projector when a live
    # demo goes wrong.
    for exc_class, handler in redacting_exception_handlers().items():
        app.add_exception_handler(exc_class, handler)

    api = APIRouter(prefix=_API_PREFIX, route_class=RedactingRoute)

    # `api_route(methods=["GET", "HEAD"])` rather than `@api.get`: FastAPI's
    # `get` does NOT add HEAD the way Starlette's bare `Route` does, and
    # `curl -I` is the "is it up" check somebody runs mid-demo.
    @api.api_route("/meta", methods=["GET", "HEAD"], response_model=MetaResponse)
    @no_redact
    async def meta() -> MetaResponse:
        """One of exactly two redaction-exempt routes. Exempt, not unexamined:
        `MetaResponse` makes its own filesystem fields display-safe at
        validation time (R4-14), which is why the raw `runs_dir` goes in here."""
        return MetaResponse(
            version=evalyn.__version__,
            runs_dir=str(runs_dir),
            packs=[str(p) for p in packs],
            allow_discover=allow_discover,
            redaction=RedactionMeta(),
        )

    @api.api_route("/health", methods=["GET", "HEAD"],
                   response_model=HealthResponse)
    @no_redact
    async def health() -> HealthResponse:
        """The other exempt route. Carries no run content at all."""
        return HealthResponse(ok=True, version=evalyn.__version__)

    # ----------------------------------------------------------------------
    # Task 7 — the read endpoints. Five routes over one `runs/` directory.
    # ----------------------------------------------------------------------

    def _resolved_artifact(run_id: str) -> Path:
        """`runs/<run_id>.json`, or a 404 — belt AND braces (R4-7).

        **Belt:** the frozen grammar, checked *first*, before anything touches
        the filesystem. `RUN_ID_PATTERN`'s character class admits no `/`, so a
        value that passes cannot traverse; a value that fails never reaches a
        `stat`. There is exactly one spelling of that grammar and this imports
        it rather than retyping it.

        **Braces:** the resolved path is checked against the runs directory.
        Traversal is impossible through the *id*, but a **symlink** inside
        `runs/` escapes without one, and `RunIndex` deliberately indexes
        symlinks (a broken one must degrade into a row, not vanish). So the
        containment check lives here, where a body is about to be served from
        the file, rather than in the index, where the job is to list.

        The refusal is `not_found` and not a 403: whether a path exists outside
        the runs directory is not something this server answers.
        """
        if not is_run_id(run_id):
            # NOT echoed. A rejected id is arbitrary client input, and
            # reflecting it into a body is a gift to whoever is probing.
            raise HTTPException(status_code=404, detail="no such run")
        path = app.state.index.artifact_path(run_id)
        if path is None:
            raise HTTPException(status_code=404, detail=f"no such run: {run_id}")
        resolved = path.resolve()
        if not resolved.is_relative_to(runs_dir):
            raise HTTPException(status_code=404, detail=f"no such run: {run_id}")
        return resolved

    def _typed_or_refuse(run_id: str, path: Path, mode: RunMode):
        """The parsed artifact, or a 500 saying this build cannot read it.

        A verdict or a report computed from an artifact this build could not
        parse would be a **fabricated** one, so the endpoints that need the
        typed object refuse instead. The list and the detail page keep
        degrading — a greyed row with a reason is the contract there (R4-5's
        "degradation, not failure"), and it is the *detail* page that has
        somewhere to put the explanation.

        `RunIndex._load` rather than a second `json.loads`: it is the
        cache-aware read (keyed on `(path, mtime, size)`), and re-parsing a
        multi-megabyte artifact on every gate request would make the cockpit's
        one expensive route its slowest by an order of magnitude. Reaching for
        an underscore-prefixed sibling is deliberate and narrow — the index
        owns loading, this module owns serving, and duplicating the load here
        would duplicate the salvage policy with it.
        """
        loaded = app.state.index._load(path, run_id, mode)
        if loaded.typed is None:
            raise HTTPException(
                status_code=500,
                detail=f"this artifact could not be read: {loaded.error}")
        return loaded.typed

    def _blessed_baseline(artifact):
        """The baseline `evaluate_gate` should diff against, and its name.

        Resolved exactly where `evalyn gate --baseline` defaults it, and used
        **only when its `pack_hash` matches the run's**. `evaluate_gate` pairs
        baseline probes by *id*, so a baseline blessed from a different pack
        revision silently compares two means that never measured the same
        thing — and `GateVerdict` has no field in which to say so. The CLI can
        print a "may be stale" warning; a JSON response cannot, so the only
        non-lying option is to refuse the diff and report no baseline, which
        the SPA renders as "capability checks are advisory".

        Returns `(None, None)` for every failure mode — absent, unreadable,
        escaping the runs directory, or blessed from another pack. A corrupt
        baseline must not turn a readable run's verdict into an error page.

        **The stricter of a divergent pair** (F3). The launch path's
        `RunLauncher._default_baseline_for` decides the same-sounding question
        by `pack_name`, tolerating a stale baseline, and resolves the path
        relative to the working directory rather than to `runs_dir`. Its
        docstring carries the full statement of the divergence and its
        consequence — a child's exit code and this displayed verdict can be
        computed against different baselines. Do not change either rule without
        reading the other.
        """
        from evalyn.engine.baseline import load_baseline

        try:
            resolved = (runs_dir / BASELINE_FILENAME).resolve()
            if not resolved.is_relative_to(runs_dir) or not resolved.is_file():
                return None, None
            baseline = load_baseline(str(resolved))
        except (OSError, RuntimeError, ValueError):
            return None, None
        if baseline is None or baseline.pack_hash != artifact.pack_hash:
            return None, None
        # The artifacts carry no run id of their own, which is why
        # `GateVerdict.baseline_run_id` is `str | None` where
        # `LaunchRequest.baseline_run_id` is `RunId | None`. The stem is the
        # only identifier the blessed file actually has.
        return baseline, resolved.stem

    def _gate_result(run_id: str, path: Path):
        """`evaluate_gate` on one artifact — **called here, lazily**.

        Never on the listing path: it reads a baseline off disk and renders
        markdown, and paying that per row is what `verdict_hint` exists to
        avoid. The import is inside the function for the same reason the whole
        `index` import is inside `create_app` (C-T7b).
        """
        from evalyn.engine.gate import evaluate_gate

        artifact = _typed_or_refuse(run_id, path, RunMode.gate)
        baseline, baseline_id = _blessed_baseline(artifact)
        return evaluate_gate(artifact, baseline), baseline_id

    @api.get("/runs", response_model=RunListPage)
    async def list_runs(mode: RunMode | None = None, pack: str | None = None,
                        status: RunStatus | None = None,
                        limit: int = DEFAULT_PAGE_SIZE,
                        before: str | None = None) -> RunListPage:
        """One page of the runs table — the **envelope**, never a bare array.

        `next_cursor` is the opaque `(created_at, run_id)` composite of the last
        row, and it is present only when a further row actually exists: the
        index is asked for one row more than the page and the extra is dropped.
        Deriving it from "the page was full" would hand the SPA a cursor that
        fetches nothing, and TanStack Query would render a phantom next page.
        """
        if before is not None:
            try:
                parse_cursor(before)
            except ValueError:
                # A rejected query parameter is `not_found`: the page cannot
                # exist, and saying so leaks nothing about the filesystem.
                raise HTTPException(
                    status_code=404,
                    detail="invalid cursor: ?before= must be the opaque "
                           "'<created_at>|<run_id>' composite handed back as "
                           "next_cursor — a bare timestamp is not tie-safe")
        size = max(1, min(int(limit), MAX_PAGE_SIZE))
        rows = app.state.index.list(mode=mode, pack=pack, status=status,
                                    limit=size + 1, before=before)
        items, more = rows[:size], len(rows) > size
        cursor = (make_cursor(items[-1].created_at, items[-1].run_id)
                  if more and items else None)
        return RunListPage(items=items, next_cursor=cursor)

    @api.get("/runs/{run_id}", response_model=RunDetail)
    async def run_detail(run_id: str) -> RunDetail:
        """The detail view. **Degrades rather than 404s.**

        An artifact this build cannot parse is a greyed page with a reason, not
        a missing resource — the run happened and the operator can see the file.
        `RunNotFound` is the only 404, and `_resolved_artifact` has already
        raised it by the time this line runs.

        **Except for a run that has not written its artifact yet**, which is
        every launched run for its whole lifetime. See `_pending_detail`.
        """
        try:
            _resolved_artifact(run_id)
        except HTTPException:
            # ONLY "there is no artifact" falls through to the pending view.
            # `_resolved_artifact` also 404s when a symlink inside `runs/`
            # resolves outside it, and that arm is a containment control
            # (R4-7's braces), not a convenience — a security check must not
            # sit behind a fallback that answers for the same id. Discriminate
            # on the artifact's absence so the containment refusal still wins.
            #
            # The grammar check comes FIRST, before anything asks the index a
            # question. R4-7's belt is that an invalid id is refused without a
            # single filesystem touch, and `test_read_endpoints.py`'s
            # `_ExplodingIndex` enforces that by raising on *any* attribute
            # access — so reaching `artifact_path` here, even though it would
            # itself return `None` safely, breaks the belt.
            if not is_run_id(run_id) or app.state.index.artifact_path(run_id) is not None:
                raise
            pending = _pending_detail(run_id)
            if pending is None:
                raise
            return pending
        return app.state.index.get(run_id)

    @api.get("/runs/{run_id}/gate", response_model=GateVerdict)
    async def gate_verdict(run_id: str) -> GateVerdict:
        """The **authoritative** verdict — the real `evaluate_gate`.

        `RunSummary.verdict_hint` is the approximation the list can afford; it
        omits REGRESSION because that needs a baseline read. This is the one
        the banner may call a verdict, and the SPA reads `exit_code` — not
        `len(failures)`, which is 0 for an incompleteness failure.
        """
        path = _resolved_artifact(run_id)
        if mode_of(run_id) is not RunMode.gate:
            raise HTTPException(
                status_code=404,
                detail=f"run {run_id} is not a gate run; there is no gate "
                       f"verdict to evaluate")
        result, baseline_id = _gate_result(run_id, path)
        return GateVerdict(
            run_id=run_id, exit_code=result.exit_code, failures=result.failures,
            quarantined=result.quarantined, report_md=result.report_md,
            baseline_run_id=baseline_id)

    @api.get("/runs/{run_id}/report", response_class=PlainTextResponse)
    async def run_report(run_id: str):
        """The run's report as **markdown**, one renderer per mode.

        `text/markdown`, not a JSON string: the SPA hands it to a renderer, and
        a double-encoded body would display as a quoted blob. The redaction
        chokepoint scrubs it as text — a content type it does not recognise is
        never a silent opt-out, only `@no_redact` is, and this route is not.
        """
        path = _resolved_artifact(run_id)
        mode = mode_of(run_id)
        if mode is RunMode.gate:
            report_md = _gate_result(run_id, path)[0].report_md
        elif mode is RunMode.compare:
            from evalyn.engine.compare import render_compare_report
            report_md = render_compare_report(_typed_or_refuse(run_id, path, mode))
        else:
            from evalyn.discovery.run import render_discovery_report
            report_md = render_discovery_report(_typed_or_refuse(run_id, path, mode))
        return PlainTextResponse(report_md,
                                 media_type="text/markdown; charset=utf-8")

    @api.get("/runs/{run_id}/trials/{probe_id}/{epoch}", response_model=TrialView)
    async def trial_view(run_id: str, probe_id: str, epoch: int) -> TrialView:
        """One trial's conversation, split into turns by this server (R4-41).

        **`checks[].turn` is the artifact's own field and is forwarded
        unchanged (R4-40).** It is *not* an index into `turns` and is not
        reconciled against one: measured on
        `20260803T174149220841-76e25fee-example`, the
        `invariant:no-internal-leak` check reports `turn: 1` while its evidence
        lives in flattened turn 4. A viewer that reports such a check as
        *unplaced* is behaving correctly; inventing an index that made it place
        would be inventing evidence.

        **`checks` comes off the trial record — never off `probes[].checks`.**
        Those are explicitly *representative*: one epoch's results carried for
        the report, with nothing recording which epoch, so serving them here
        under the SPA's "Checks on this trial" heading would attribute one
        trial's verdicts to all of them. Task 22 made the engine record each
        epoch's own checks, and this read — written against the record from the
        start — began serving them the day it did. **Artifacts written before
        Task 22 have no such key and still answer `[]`**, which the SPA reads as
        "not captured": the honest answer for a trial whose results were never
        recorded, and the reason no capability flag was added for it.

        404s (never 200 with an empty conversation) when the artifact has no
        trial records at all: the SPA gates the drill-down on
        `capabilities.trial_records`, so arriving here is a bug in the caller,
        and an empty `turns[]` would read as "the conversation was empty".

        That 404 covers the **unreadable** artifact too, where `/gate` and
        `/report` answer 500. The difference is what the caller can do about
        it: a verdict has an artifact it must refuse to fabricate, while a
        trial record either exists or does not, and an artifact this build
        cannot parse has none by any reading. The *reason* it cannot be parsed
        belongs on the detail page, which has `degraded_reason` to put it in.
        """
        path = _resolved_artifact(run_id)
        no_records = HTTPException(
            status_code=404,
            detail="this artifact has no trial records; the drill-down should "
                   "have been disabled by capabilities.trial_records")
        if mode_of(run_id) is not RunMode.gate:
            raise no_records
        artifact = app.state.index._load(path, run_id, RunMode.gate).typed
        if artifact is None:
            raise HTTPException(
                status_code=404,
                detail="this artifact could not be read, so it has no trial "
                       "records; capabilities.trial_records said so")
        records = {(probe.id, record["epoch"]): (probe, record)
                   for probe in artifact.probes
                   for record in probe.trial_records
                   if isinstance(record, dict) and "epoch" in record}
        if not records:
            raise no_records
        found = records.get((probe_id, epoch))
        if found is None:
            # The probe id is client input; it is not echoed.
            raise HTTPException(
                status_code=404,
                detail=f"no trial record for that probe at epoch {epoch}")
        _, record = found
        seconds = record.get("session_seconds")
        failures = record.get("invariant_failures")
        return TrialView(
            run_id=run_id, probe_id=probe_id, epoch=epoch,
            turns=split_transcript(record.get("transcript")),
            session_seconds=(float(seconds)
                             if isinstance(seconds, (int, float))
                             and not isinstance(seconds, bool) else None),
            invariant_failures=(failures if isinstance(failures, int)
                                and not isinstance(failures, bool) else 0),
            checks=[_check_view(check) for check in record.get("checks", [])
                    if isinstance(check, dict)])

    # ----------------------------------------------------------------------
    # Task 20 — the control surface. Registered on `api` BEFORE the router is
    # included, because the `/api/{unmatched:path}` catch-all below is
    # registered after it and would otherwise shadow every one of these.
    # ----------------------------------------------------------------------

    def _run_is_live(run_id: str) -> bool:
        """Can this run still act on a control file?

        Two facts each mean **no**, and either is enough:

        * **an artifact exists** — the run wrote its record, so it is over;
        * **`meta.json` records an `exit_code`** — the child has exited.

        **What this guard is, and what it is not.** It refuses a control file
        for a run that is already over, which keeps `runs/` clean of requests
        nothing can act on and gives the operator a 409 instead of a silent
        no-op. It is a *narrowing*, and only a narrowing: the residual window
        runs from "the second check said live" to "the run finishes", and a
        cancel landing inside it still leaves an orphan file on disk. That
        window was measured, not reasoned about — it is registered as a
        deferred finding in `docs/JOURNAL.md` (`be9ab3a`), and it is the exact
        shape the two orphan control files from the wiring pass were left in.

        It is **not**, on its own, what protects a finished run's verdict.
        `derive_status` no longer puts `control is cancel` above the artifact:
        `index.cancelled_by` reads `RunArtifact.cancelled` — the flag the
        engine itself wrote when it honoured the cancel — wherever there is
        one. That is the defence this guard now stands in front of rather than
        the one it provides.

        **And it covers `gate` only.** `RunArtifact` is the sole artifact with
        a `cancelled` field; a completed `compare` or `discover` beside a stale
        cancel file still derives `cancelled`, because there is no
        artifact-side answer to prefer (see `index.cancelled_by`; pinned by
        `test_index.py::test_a_stale_cancel_still_relabels_compare_and_discover`).
        For those two modes
        this guard is not defence in depth — it is the only defence there is,
        and its residual window is a real hole rather than a covered one.

        A run this cockpit did not launch, with no artifact and no recorded
        exit code, is treated as live: it may genuinely be running in another
        process, and the control file is the only way to reach it.
        """
        if app.state.index.artifact_path(run_id) is not None:
            return False
        sidecar = app.state.index._sidecar(run_id, runs_dir / f"{run_id}.json")
        return sidecar.exit_code is None

    def _pack_or_404(pack_id: str):
        found = app.state.packs_by_id.get(pack_id)
        if found is None:
            # The id is client input and is not echoed.
            raise HTTPException(status_code=404, detail="no such pack")
        return found

    def _pending_detail(run_id: str) -> RunDetail | None:
        """The detail of a run that has been launched but has written nothing.

        **This is the single most load-bearing thing on the demo path.** The
        launch console navigates to `/runs/<id>` the moment the 202 lands, and
        the artifact does not exist until the run *finishes* — so without this,
        `RunIndex.get` raises `RunNotFound`, the SPA renders its "could not be
        read" alarm over a perfectly healthy run, and it never recovers: the
        query client sets `retry: false`, and the only thing that would
        invalidate the query lives inside the live panel, which never mounts.
        `LiveRunPanel.tsx` names this exact case as a deferred check on the
        pass that wires the launcher up; this is that pass.

        `derive_status(None, sidecar)` is the *same* function the list uses, so
        `running`, `paused`, `cancelled`, `interrupted` and `failed_to_start`
        are decided in one place rather than invented a second time here.

        Returns `None` — and therefore a genuine 404 — for an id this cockpit
        never launched, so an arbitrary id is still "no such run".
        """
        from evalyn.ui.index import (
            cancelled_by,
            created_at_from_run_id,
            derive_status,
        )

        if not is_run_id(run_id):
            return None
        try:
            directory = sidecar_dir(runs_dir, run_id)
        except ValueError:
            return None
        if not directory.is_dir():
            return None

        index = app.state.index
        # The artifact path does not exist; it is only used to derive the
        # sibling control and events names, which are pure string operations.
        sidecar = index._sidecar(run_id, runs_dir / f"{run_id}.json")
        live = app.state.launcher.reap()
        return RunDetail(
            run_id=run_id,
            mode=mode_of(run_id),
            pack_name=(live.pack_name
                       if live is not None and live.run_id == run_id else None),
            created_at=created_at_from_run_id(run_id),
            status=derive_status(None, sidecar),
            # Nothing is readable yet, and the SPA disables its affordances off
            # these booleans rather than off truthiness.
            capabilities=Capabilities(transcripts=False, trial_records=False,
                                      hard_metrics=False),
            # No artifact exists here, so this is the one place `cancelled_by`
            # can only answer off the control file — routed through it anyway
            # so "who cancelled" is decided in exactly one function.
            cancelled=cancelled_by(None, sidecar),
            # A pending body has nothing sensitive in it yet, so the chokepoint
            # changes nothing and leaves `redacted` at its `False` default —
            # which reads as "this view was served unscrubbed" while the banner
            # two inches above it says `REDACTION ON`. It flips to `True` on
            # its own the moment an artifact lands and a `$HOME` path appears
            # in `log_path`, so the field would announce a security feature
            # switching itself on mid-run. Taken from the same `RedactionMeta`
            # the banner is built from, so the two cannot disagree.
            redacted=RedactionMeta().enabled,
        )

    @api.get("/packs", response_model=PackListPage)
    async def list_packs() -> PackListPage:
        """The start-time allowlist — everything a launch may select from.

        An envelope rather than a bare array, because a top-level array can
        never grow a field. `next_cursor` is always `None`: the allowlist is as
        long as the operator's `--target` flags.
        """
        return PackListPage(items=pack_rows(app.state.packs_by_id),
                            next_cursor=None)

    @api.get("/trends", response_model=list[TrendSeries])
    async def trends(pack: str | None = None,
                     metric: TrendMetric = TrendMetric.pass_k):
        """One pack's history, one series per probe.

        **A bare top-level array**, and the only route here that is. Every other
        list is `{items, next_cursor}`, so this is the shape a later hand will
        "correct" by analogy — `Trends.tsx` types the read as
        `apiGet<TrendSeries[]>` and has no unwrap, so an envelope renders the
        page's error branch. It is not paginated for the same reason it is not
        capped: nothing bounds it client-side, and the readout reports "N runs"
        as though N were the whole history (guarantee 11). The cost is bounded
        by `RunIndex`'s cache, which is keyed on `(path, mtime, size)` — the
        second request over a 100-run corpus is one `stat` per file.

        **`?pack=` is the pack's NAME** — `PackRow.name`, the string the artifact
        itself records and the same field `/api/runs?pack=` filters on. It is
        compared for equality against already-loaded data and is never joined
        into a path, interpolated into one, or opened: a traversal-shaped value
        is simply a pack nobody has ever run, and gets the same `200 []` as any
        other unknown name. `PackRow.id` is the identifier for the routes that
        *address* a pack on disk; see its docstring.

        **A pack with no history is `200 []`, never a 404** — an empty chart is
        a legitimate state, and a 404 renders an alarm over a pack that simply
        has not been run yet.

        **Two of the three filters below are unobservable, and both stay.**

        Compare and discover artifacts contribute nothing: all four
        `TrendMetric` members are gate metrics. The mode filter is lexical (it
        reads the run id, not the file) so it is free, but it is an
        **optimisation and not the control** — measured by mutation, removing it
        changes nothing observable, because a non-gate artifact carries no
        `probes` and a gate body wearing a compare id fails the typed load and
        is dropped as degraded.

        `not row.degraded` is unobservable for the same kind of reason, and
        redundant twice over. A degraded run is one whose TYPED load failed, and
        `index.get()` answers such a run with `probes: []` — so `build_trends`,
        which iterates `run.probes`, reads nothing from it even if the row gets
        through. And on the live corpus the clause selects nobody the status
        filter had not already dropped: `degraded` is true of exactly the runs
        whose status is `unreadable`, 26 of 26. Mutation confirms it — removing
        it reddens nothing.

        Neither is deleted on the strength of that. Each states the intent the
        chart depends on, each costs one boolean per row, and neither can be
        made discriminating without inventing an artifact shape `RunIndex`
        cannot produce — a fixture that lied about the code would be worse than
        a comment that tells the truth about it. They are what keeps the honest
        reason honest. What actually enforces guarantee 1 is `_probe_row`
        answering `None` for a metric no artifact recorded, and `_finite`
        refusing anything unplottable.
        """
        if not pack:
            # `pack_error`, not the 400's default `launch_refused` — this route
            # starts nothing, and a client told its read "was refused a launch"
            # is being lied to about which contract it broke. The envelope is
            # built here because the status->code map cannot see the difference.
            return JSONResponse(
                status_code=400,
                content=ErrorEnvelope(error=ApiError(
                    code=ErrorCode.pack_error,
                    message="?pack= is required: /api/trends reports the history "
                            "of one pack, and there is no all-packs answer",
                )).model_dump(mode="json", exclude_none=True))

        rows = [row for row in app.state.index.list(mode=RunMode.gate, pack=pack,
                                                    limit=None)
                if row.status in TREND_STATUSES and not row.degraded]
        # Ascending, and by the row's OWN `created_at` — the artifact's stamp,
        # which is what the runs table shows. The filename's stamp usually
        # agrees, and sorting on it (or on the directory listing, which is the
        # same order) would be right until the day a run is written under an id
        # minted earlier than the moment it finished.
        rows.sort(key=lambda row: (row.created_at, row.run_id))
        return build_trends([app.state.index.get(row.run_id) for row in rows],
                            pack, metric)

    @api.get("/trust", response_model=TrustReport)
    async def trust(pack: str | None = None):
        """One pack's judge-calibration record — the Judge Trust page's read.

        **`?pack=` is the pack's NAME**, the same string `/api/trends?pack=`
        takes and the same one `PackRow.name` reports, because the page picks
        it out of `/api/packs` exactly as the Trends page does.

        **It is never turned into a path.** This route genuinely opens a file
        inside a pack directory, so the resolution runs through
        `pack_id_for(name)` into `app.state.packs_by_id` — the same start-time
        allowlist `/api/packs` lists and `/api/packs/{pack_id}/axes` addresses.
        That id is a SHA-256 digest, so a traversal-shaped `?pack=` is not a
        path that fails to open: it is a dictionary key nobody holds. The pack
        *root* comes from the operator's own `--target` and from nowhere else.

        **A name outside the allowlist is `200`, not `404`** — but it says so.
        This server cannot read a record for a pack it was never pointed at,
        which is a different fact from "this pack has never been calibrated",
        and the two must not be reported with the same sentence. `runs/` may
        hold history for packs the allowlist does not name (which is why
        `/api/trends` accepts any name); a *record* has no such reading.
        """
        if not pack:
            # `pack_error` rather than the 400's default `launch_refused`,
            # exactly as `/api/trends` does: this read starts nothing, and a
            # client told it "was refused a launch" is being lied to about
            # which contract it broke.
            return JSONResponse(
                status_code=400,
                content=ErrorEnvelope(error=ApiError(
                    code=ErrorCode.pack_error,
                    message="?pack= is required: /api/trust reports the judge "
                            "calibration of one pack, and there is no "
                            "all-packs answer",
                )).model_dump(mode="json", exclude_none=True))

        found = app.state.packs_by_id.get(pack_id_for(pack))
        if found is None:
            return TrustReport(
                pack_name=pack, stale=True,
                stale_reason="this pack is not in the allowlist this server "
                             "was started with, so its calibration record is "
                             "not one this server can read")
        return build_trust(found[0])

    def _discovery_groups(objective: str | None, before: str | None):
        """Every staged finding, newest run first, grouped by the run that made it.

        Grouped rather than flat because the cursor is `(created_at, run_id)`
        and **a run is the finest thing that key can address**: two findings
        from the same hunt share both halves of it, so a page boundary drawn
        between them hands back a cursor that excludes them BOTH on the next
        request (`?before=` keeps rows strictly less than the key). Paging by
        run makes the boundary representable, at the cost of a page that can
        overshoot `limit` by the size of the last run. `RunListPage`'s own
        rows do not have this problem because there each row IS a run.

        Groups with no matching finding are dropped HERE, not at the page
        boundary: a cursor pointing at a run the filter empties would fetch a
        page with no rows, and TanStack Query renders that as a phantom page.
        """
        index = app.state.index
        groups = []
        for row in index.list(mode=RunMode.discover, limit=None, before=before):
            # A launched-but-unwritten discover run is a real row in `list`
            # and has no artifact to read. It contributes no findings, and
            # `index.get` would raise `RunNotFound` for it.
            if index.artifact_path(row.run_id) is None:
                continue
            summary = index.get(row.run_id).discovery
            if summary is None:
                continue                     # degraded, or not a discover body
            findings = [finding for finding in summary.findings
                        if objective is None or finding.objective_id == objective]
            if findings:
                groups.append((row, sorted(findings, key=lambda f: f.probe_id)))
        return groups

    @api.get("/discoveries", response_model=DiscoveryListPage)
    async def list_discoveries(objective: str | None = None,
                               limit: int = DEFAULT_PAGE_SIZE,
                               before: str | None = None) -> DiscoveryListPage:
        """The staged findings — the **envelope**, never a bare array.

        Each row is the join `FindingRow` documents: the staged probe's
        `category` and `safety_critical`, which exist only in
        `<pack>/discoveries/*.yaml`, over the artifact's `confirmed` and replay
        verdict, which exist only in the run record because staging happens
        before replay.

        **Only the allowlisted packs are ever read.** The join is keyed on the
        probe id, and the corpus it looks that id up in is built by globbing
        the packs the operator named on the command line — the `probe_path`
        recorded in the artifact is reported, never opened.

        A finding whose staged file is gone is still a row: it happened, the
        run records it, and dropping it would make an adoption look like an
        erasure. It reports `category: null` — see `_finding_row`.
        """
        if before is not None:
            try:
                parse_cursor(before)
            except ValueError:
                # Same ruling as `/api/runs`: a rejected cursor is `not_found`,
                # because the page cannot exist and saying so leaks nothing.
                raise HTTPException(
                    status_code=404,
                    detail="invalid cursor: ?before= must be the opaque "
                           "'<created_at>|<run_id>' composite handed back as "
                           "next_cursor — a bare timestamp is not tie-safe")
        size = max(1, min(int(limit), MAX_PAGE_SIZE))
        groups = _discovery_groups(objective, before)

        items: list = []
        cursor = None
        for position, (row, findings) in enumerate(groups):
            # `items and` is what stops a single run bigger than the page from
            # yielding an empty page forever: the first group always goes in.
            if items and len(items) + len(findings) > size:
                previous = groups[position - 1][0]
                cursor = make_cursor(previous.created_at, previous.run_id)
                break
            items.extend(findings)
        return DiscoveryListPage(items=items, next_cursor=cursor)

    @api.get("/discoveries/{probe_id}", response_model=FindingDetail)
    async def finding_detail(probe_id: str) -> FindingDetail:
        """One staged finding: its file, its provenance, and its replay.

        **`probe_id` is never joined into a path.** It is a key into the dict
        `load_staged_probes` builds by globbing the allowlisted packs, so a
        traversing or absolute id is a probe nobody staged and gets the same
        404 as a typo. That is what makes an arbitrary path parameter safe here
        without a grammar check of its own.

        Redacted like everything else: `RedactingRoute` scrubs the rendered
        bytes, so `probe_yaml` and `provenance.confirmation` — the two places a
        confirmed `pii-leak` finding embeds the captured address verbatim — are
        covered by construction rather than by this handler remembering to.

        404 when neither side of the join knows the id. A finding with no
        staged file still answers (with an empty `probe_yaml`), and a staged
        file with no finding answers too: the run artifact may simply have been
        cleaned out of `runs/`, and the file on disk is the evidence.
        """
        staged = app.state.index.staged_probes().get(probe_id)
        match = next((pair for _, findings in _discovery_groups(None, None)
                      for pair in findings if pair.probe_id == probe_id), None)
        if staged is None and match is None:
            # The id is client input and is not echoed back.
            raise HTTPException(status_code=404, detail="no such finding")

        replay = None
        if match is not None:
            replay = _replay_view_for(match.run_id, probe_id)
        row = match if match is not None else FindingRow(
            probe_id=probe_id, objective_id=staged.provenance.get("objective", ""),
            confirmed=False, probe_path=str(staged.path),
            category=staged.probe.category,
            safety_critical=bool(staged.probe.safety_critical),
            persona_id=staged.provenance.get("persona", ""),
            playbook_id=staged.provenance.get("playbook", ""))
        return FindingDetail(
            **row.model_dump(),
            probe_yaml=staged.text if staged is not None else "",
            provenance=staged.provenance if staged is not None else {},
            # The probe's turns are the user side of the hunt that confirmed
            # it — `_answered_turns` keeps exactly the messages the target
            # answered — so every one of them is a `user` turn. The target's
            # replies are not in the staged file at all.
            turns=[TranscriptTurn(role=TurnRole.user, text=turn)
                   for turn in (staged.probe.turns if staged is not None else [])],
            # The scored checks, flattened off the replay so a detail page can
            # render them without unwrapping a nullable. The probe's own check
            # *definitions* are not these: `CheckView` is a result, and the
            # definitions are already in `probe_yaml` verbatim.
            checks=list(replay.checks) if replay is not None else [],
            replay=replay,
        )

    def _replay_view_for(run_id: str | None, probe_id: str) -> ReplayView | None:
        """The replay verdict off the artifact, by probe id.

        Read from the typed artifact rather than carried down from the listing:
        `FindingRow` records only the flattened `replay_status`, and the detail
        view promises the trials, the two pass rates and the checks behind it.
        """
        if run_id is None:
            return None
        path = app.state.index.artifact_path(run_id)
        if path is None:
            return None
        try:
            artifact = _typed_or_refuse(run_id, path, RunMode.discover)
        except HTTPException:
            return None
        for finding in artifact.findings:
            if Path(finding.probe_path).stem == probe_id:
                return _replay_view(finding.replay)
        return None

    @api.get("/packs/{pack_id}/axes", response_model=PackAxes)
    async def pack_axes_view(pack_id: str) -> PackAxes:
        """What a `discover` launch may select, and the pack's own ceiling."""
        loaded, _ = _pack_or_404(pack_id)
        return pack_axes(pack_id, loaded)

    @api.post("/runs", response_model=LaunchResponse, status_code=202)
    async def launch_run(request: LaunchRequest) -> LaunchResponse:
        """Start a run. **This is the endpoint that spends money.**

        A 202, not a 200: nothing has run yet. The `run_id` is minted before
        the process starts and is the stem of the artifact that will later
        appear, which is what makes subscribing to `/events` valid immediately.

        Every refusal is `launch_refused` (400) except a second concurrent
        launch, which is `busy` (409) — `redact.py:686-693` already maps both.
        A body naming a pack *path* never reaches here at all: `LaunchRequest`
        has no such field and `extra="forbid"` rejects it upstream, which is
        why nothing below looks for one.
        """
        found = app.state.packs_by_id.get(request.pack_id)
        loaded, path = found if found is not None else (None, None)
        why = refusal_for(request, pack=loaded, allow_discover=allow_discover)
        if why is not None:
            raise HTTPException(status_code=400, detail=why)
        try:
            run_id = app.state.launcher.launch(request, pack=loaded, pack_path=path)
        except Busy as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except OSError as e:
            # The spawn itself failed. `meta.json` already says the child never
            # started, so the run reads as `failed_to_start` rather than
            # vanishing — and the operator gets a sentence, not a spinner.
            raise HTTPException(
                status_code=400,
                detail=f"the run could not be started: {e.__class__.__name__}: {e}"
            ) from e
        return LaunchResponse(run_id=run_id)

    @api.post("/runs/{run_id}/control", response_model=ControlResponse,
              status_code=202)
    async def control_run(run_id: str, request: ControlRequest) -> ControlResponse:
        """Pause, resume or cancel — by writing the control file, and only that.

        **The 202 is not the acknowledgement.** `accepted=True` says the
        request was well-formed and the file was written; the matching
        `control.*` SSE event is what says the run actually did it.

        No signal is ever sent to the child, at any delay (R4-11). And note
        that **pause does not stop spend**: in-flight samples finish and keep
        billing. Nothing here may imply otherwise.
        """
        if not is_run_id(run_id):
            raise HTTPException(status_code=404, detail="no such run")
        known = (app.state.index.artifact_path(run_id) is not None
                 or sidecar_dir(runs_dir, run_id).is_dir())
        if not known:
            raise HTTPException(status_code=404, detail=f"no such run: {run_id}")

        # Asked of current truth, not of whatever `meta.json` last happened to
        # record (T-A2). A child that has exited but that nothing has reaped
        # keeps `exit_code: null`, so the endpoint used to answer
        # `202 accepted: true` for a process that was already gone and leave an
        # orphan control file in `runs/` — measured on the running app, where
        # the list and this endpoint then disagreed until somebody opened a
        # detail page and reaped as a side effect.
        #
        # **What THIS line contributes, precisely** (F1/F2 — the earlier
        # wording credited it with the whole fix, and the suite proved
        # otherwise): the 202-for-a-dead-child and the orphan file are both
        # stopped by the *post*-write reap below, on its own. What this reap
        # adds is that a dead child's request is refused **before** anything is
        # written, instead of a control file being written into `runs/` and
        # immediately retracted. That transient write is the only difference a
        # caller-side test can see, and it is what
        # `test_a_dead_childs_control_request_is_refused_before_the_write_not_after`
        # pins — deliberately, because deleting this line left the whole suite
        # green. `reap()` is existing infrastructure and already runs from
        # `_pending_detail`, a GET; this is a POST, which writes by definition.
        # It cannot relabel a live run: `poll()` has to return an exit code for
        # the slot to be released, and `self.live` is `None` for a run left
        # behind by a previous server, so such a run stays live and still takes
        # control actions.
        app.state.launcher.reap()
        if not _run_is_live(run_id):
            raise HTTPException(status_code=409, detail=_NOT_LIVE)

        app.state.launcher.control(run_id, request.action)

        # Checked again, AFTER the write, because the run can finish in the
        # window between the two. The second check is what makes this
        # self-healing rather than merely narrow: a file written for a run that
        # has just ended is a request nothing will ever act on, so it is
        # removed again and the caller is told the truth instead of a 202 it
        # would read as an acknowledgement. The window is narrowed, not closed
        # — anything landing inside it is still left on disk. For `gate` that
        # is survivable, because `index.cancelled_by` reads the verdict off
        # `RunArtifact.cancelled` and not off this file; for `compare` and
        # `discover`, whose artifacts have no such field, a file left inside
        # the window does still relabel the run. That is a recorded
        # limitation, not a covered case.
        #
        # Reaped again for the reason the pre-write check is: a run can end
        # inside that window by *exiting* as readily as by writing an artifact,
        # and a child that exited with nothing written leaves the artifact
        # check nothing to find.
        app.state.launcher.reap()
        if not _run_is_live(run_id):
            control_path(runs_dir / f"{run_id}.json").unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail=_NOT_LIVE)
        return ControlResponse(run_id=run_id, accepted=True)

    @api.get("/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request):
        """The live event stream, as `text/event-stream`.

        Serves a finished run's history just as happily as a live one's tail —
        the SPA subscribes without knowing which it has, and a finished stream
        simply ends at `run.finished`.

        `Last-Event-ID` is the browser's own resume protocol: `EventSource`
        sends back the last `id:` it saw and the stream skips past it, so a
        reconnect does not replay the run.

        Scrubbed **here**, explicitly: `RedactingRoute` returns a streaming
        response untouched by design (`redact.py:626-628`), so this is the one
        `/api` route the chokepoint does not cover.
        """
        if not is_run_id(run_id):
            raise HTTPException(status_code=404, detail="no such run")
        known = (app.state.index.artifact_path(run_id) is not None
                 or sidecar_dir(runs_dir, run_id).is_dir())
        if not known:
            raise HTTPException(status_code=404, detail=f"no such run: {run_id}")

        try:
            last_id = int(request.headers.get("last-event-id", "0"))
        except ValueError:
            # A header this server cannot read is a resume it cannot honour;
            # replaying from the top is the safe direction (the consumer drops
            # anything it has already folded in), losing nothing.
            last_id = 0

        redactor: Redactor = app.state.redactor
        return StreamingResponse(
            event_stream(events_path(runs_dir / f"{run_id}.json"),
                         last_id=last_id,
                         idle_timeout=app.state.sse_idle_timeout,
                         is_disconnected=request.is_disconnected,
                         scrub=redactor.scrub),
            media_type="text/event-stream",
            # `no-cache` because a cached event stream is a frozen run, and
            # `no-transform` because a proxy that buffers it is the same bug.
            headers={"Cache-Control": "no-cache, no-transform",
                     "X-Accel-Buffering": "no",
                     "Connection": "keep-alive"})

    @api.get("/runs/{run_id}/stderr", response_class=PlainTextResponse)
    async def run_stderr(run_id: str) -> PlainTextResponse:
        """The child's stderr, verbatim.

        For a run that died before writing an artifact this is the only place
        the reason exists — a bad judge model, a missing key, a pack that
        failed validation. Unlike the stream, this one *is* covered by the
        redaction chokepoint, because it renders a body with `.body` set.
        """
        if not is_run_id(run_id):
            raise HTTPException(status_code=404, detail="no such run")
        log = sidecar_dir(runs_dir, run_id) / STDERR_FILENAME
        if not log.is_file():
            raise HTTPException(
                status_code=404,
                detail="no stderr for that run: it was not launched from this "
                       "cockpit, or it has not written anything yet")
        return PlainTextResponse(log.read_text(encoding="utf-8", errors="replace"),
                                 media_type="text/plain; charset=utf-8")

    app.include_router(api)

    # Registered AFTER the router, so a route a later task adds to `api` is
    # matched first and this only ever answers for paths that genuinely do not
    # exist. Without it an unknown `/api/...` would fall through to the SPA
    # history fallback below and a client would get HTML, or a 405, instead of
    # an envelope.
    #
    # HEAD and OPTIONS are in the list for the same reason every other method
    # is: a 405 on an unknown path tells a prober the path exists, which is the
    # signal this route exists to suppress. Answering 404 for all of them says
    # nothing either way.
    @app.api_route("/api/{unmatched:path}", include_in_schema=False,
                   methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH",
                            "DELETE"])
    async def api_not_found(unmatched: str):
        # `unmatched` is deliberately NOT echoed: reflecting a client-supplied
        # path into a body is a needless gift to anyone probing the server.
        raise HTTPException(status_code=404, detail="no such API endpoint")

    if ASSETS_DIR.is_dir():
        # Mounted before the catch-all so the hashed bundle wins. `index.html`
        # references these as `./assets/...` (vite `base: "./"`).
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

    @app.api_route("/{spa_path:path}", methods=["GET", "HEAD"],
                   include_in_schema=False)
    async def spa(spa_path: str):
        """The SPA's history fallback — `BrowserRouter` owns `/runs/<id>`.

        Without it every deep link and every browser refresh is a 404, which is
        the difference between a cockpit and a demo nobody may click in.
        """
        if spa_path == "api" or spa_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="no such API endpoint")
        if not INDEX_HTML.is_file():
            raise HTTPException(
                status_code=500,
                detail="the cockpit bundle is missing from this install")
        # `no-cache` so a rebuilt bundle is picked up on reload; the hashed
        # assets under /assets are immutable and may be cached by the browser.
        return FileResponse(INDEX_HTML, media_type="text/html",
                            headers={"cache-control": "no-cache"})

    return app


def serve(*, runs_dir: Path, packs: list[Path], port: int = DEFAULT_PORT,
          host: str = LOOPBACK_HOST, allow_discover: bool = False,
          open_browser: bool = True, judge_model: str | None = None) -> None:
    """Build the app and serve it on loopback until interrupted.

    `host` exists to be **refused**. It is a parameter rather than a constant so
    that the refusal is a testable behaviour instead of an absence, and there is
    deliberately no CLI flag feeding it: this server reads an operator's `runs/`
    directory and will grow the ability to launch evals, so binding it to
    anything reachable from the network hands both to the room.
    """
    if host != LOOPBACK_HOST:
        raise ValueError(
            f"evalyn ui binds {LOOPBACK_HOST} only; refusing host {host!r} — the "
            f"cockpit reads your runs directory and launches evals, and neither "
            f"belongs on a network interface")

    app = create_app(Path(runs_dir), [Path(p) for p in packs],
                     allow_discover=allow_discover, judge_model=judge_model)

    url = f"http://{host}:{port}/"
    print(f"evalyn ui: serving {display_path(str(Path(runs_dir).resolve()))} "
          f"at {url} — redaction is on", file=sys.stderr)

    # Opened before the bind, not after: uvicorn.run() does not return until the
    # server stops, and the browser takes far longer to start than the socket
    # does. Skipped for `--port 0`, where the real port is not known until
    # uvicorn logs it.
    if open_browser and port:
        webbrowser.open(url)

    import uvicorn

    uvicorn.run(app, host=host, port=port)
