"""The trust boundary: the agent PROPOSES, the scoring layer DISPOSES.

A red-team agent asserting "I found a vulnerability" is worth nothing — it is
self-graded output. So `discover` splits the roles: a candidate becomes a
**finding** only when Evalyn's existing, independent scorers fail the
candidate's own required checks against the real transcript.

    "Confirmed" <=> the candidate probe's required checks FAIL.

This module therefore contains **zero check logic**. It is glue: build a
`TaskState` from the session transcript, hand it to the REAL `tier1_scorer`
(and `tier3_scorer` when the candidate declares a rubric check), and read the
verdict off `checks.aggregate_trial`. Anything here that decided whether text
violates something would re-implement the scoring layer and destroy the
independence that makes confirmation mean anything.

Two invariants that everything downstream rests on:

* **Pack-level invariants are blanked** (`conf_pack`). Confirmation evaluates
  exactly and only the candidate's declared checks; otherwise a pack invariant
  the candidate never proposed could confirm a finding the emitted probe does
  not assert — a regression probe that passes while the "finding" that
  justified it came from somewhere else entirely.
* **Unsure is never a finding.** A judge that abstains produces no finding, not
  a maybe-finding. Every ambiguity — an abstention, a judge outage, a missing
  rubric judge, a candidate with no required checks at all — resolves to "not
  confirmed".

A third rule, learned from review: **a check this boundary cannot itself
evaluate is unsure, never a confirmation.** Two ways a candidate can carry one:
a *structurally* invalid check (`not_contains` with no `value`), which tier-1
correctly fails as a misconfiguration for `gate` but which would mint a
transcript-INDEPENDENT finding here; and a check of a type this boundary never
runs (`classifier` — tier-2 is not wired into `discover`), which would
otherwise vanish from the results and let a sibling check confirm a candidate
whose other claim was never evaluated. The boundary validates its own input; it
does not trust its caller.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path

from inspect_ai.model import ChatMessage, ModelUsage
from inspect_ai.scorer import Target
from inspect_ai.solver import TaskState

from evalyn.engine.budget import estimate_cost
from evalyn.engine.validate import KNOWN_INVARIANTS
from evalyn.scoring.checks import aggregate_trial
from evalyn.scoring.tier1 import tier1_scorer
from evalyn.scoring.tier3 import tier3_scorer
from evalyn.targets.loader import Pack
from evalyn.targets.schema import Check, Probe

#: Check types this boundary actually runs: tier-1 evaluates the deterministic
#: three, tier-3 the rubric. `classifier` is deliberately ABSENT — tier-2 is not
#: wired into `discover`, so a candidate declaring one must go unsure rather
#: than have it silently dropped from the aggregation.
_EVALUABLE_TYPES = frozenset({"invariant", "contains", "not_contains", "rubric"})

#: Exception classes that mean "Evalyn has a bug", not "the judge/environment
#: failed". These are RE-RAISED out of the tier-3 catch: swallowing them would
#: degrade every tier-3 candidate to "unsure" for a whole unattended run with
#: only a RuntimeWarning to show for it.
_PROGRAMMER_ERRORS = (TypeError, AttributeError, NameError, KeyError)

#: Self-consistency draws per rubric check. Passed EXPLICITLY to
#: `tier3_scorer` so the number of judge calls we charge for and the number we
#: make cannot drift apart.
JUDGE_K = 3

#: Pessimistic per-judge-call usage. A confirmation prompt is the rubric's
#: grading steps plus the labeled session transcript (capped by the pack's
#: `max_turns_per_session`) — low thousands of input tokens — and the JSON
#: verdict is hundreds of output tokens. 16k in / 4k out is several times that,
#: deliberately: `tier3.score_transcript` does not surface usage, so this live
#: charge is the ONLY thing standing between an autonomous loop and a runaway
#: spend. The post-hoc `meter.reconcile` is an accounting cross-check, not a
#: safety net — it runs after the money is gone.
_JUDGE_CALL_USAGE = ModelUsage(
    input_tokens=16_000, output_tokens=4_000, total_tokens=20_000)

#: Judge calls charged per rubric check: JUDGE_K scoring draws + 1 for a
#: possible grading-steps generation (skipped when the pack ships frozen steps
#: or the steps cache hits — charging for it anyway is the conservative side).
_CALLS_PER_RUBRIC_CHECK = JUDGE_K + 1


def tier3_confirmation_usd(rubric_model: str, rubric_checks: int = 1) -> float:
    """Conservative live charge for confirming `rubric_checks` rubric checks.

    Priced through `engine.budget.estimate_cost` — the same arithmetic as
    `gate`'s judge metering and `meter.reconcile`, so `discover` never invents
    a second accounting.
    """
    per_call = estimate_cost({rubric_model: _JUDGE_CALL_USAGE})
    return per_call * _CALLS_PER_RUBRIC_CHECK * rubric_checks


def _unevaluable(check: Check) -> str | None:
    """Why this boundary cannot evaluate `check` — or None when it can.

    NOT check logic: nothing here looks at a transcript or decides whether text
    violates anything. It answers one structural question — "can the scorers
    this Confirmer runs render a real verdict on this check?" — because a check
    they cannot is a check that must resolve to unsure.

    The `gate`/`discover` asymmetry that makes this necessary: a `not_contains`
    with no `value` is a MISCONFIGURATION, and tier-1 rightly fails it required
    (`"no value(s) configured"`) so a broken pack reds the gate. Here that same
    failure is transcript-independent — it would confirm a "finding" against any
    transcript whatsoever and emit a permanently-failing regression probe. An
    empty-string needle is the same trap by another route (`"" in anything` is
    always True, so a required `not_contains: ""` can never pass).
    """
    if check.type not in _EVALUABLE_TYPES:
        return (f"check type {check.type!r} is not evaluated by the Confirmer "
                f"(tier-2 is not wired into discover)")

    def blank(v: str | None) -> bool:
        return v is None or not str(v).strip()

    if check.type == "invariant":
        if blank(check.ref):
            return "invariant check declares no `ref`"
        if check.ref not in KNOWN_INVARIANTS:
            # tier-1 treats an unknown invariant as a silent no-op PASS, so it
            # would not fail the candidate — but it would leave the claim
            # unevaluated while a sibling check confirmed the finding.
            return f"invariant {check.ref!r} is not a known invariant"
    elif check.type == "not_contains":
        if blank(check.value):
            return "not_contains check declares no non-blank `value`"
    elif check.type == "contains":
        if blank(check.value) and not [v for v in (check.values or [])
                                       if not blank(v)]:
            return "contains check declares no non-blank `value`/`values`"
    elif check.type == "rubric" and blank(check.rubric):
        return "rubric check declares no `rubric` id"
    return None


@dataclass
class Confirmation:
    """The disposal verdict on one candidate.

    `confirmed` is true ONLY when the real scorers failed a required check and
    nothing was unsure. `check_results` are the scorers' own CheckResult dicts
    — the evidence, carried verbatim into the run artifact.
    """

    confirmed: bool
    unsure: bool
    tier: int
    check_results: list[dict] = field(default_factory=list)
    reason: str = ""


class Confirmer:
    """Hands a candidate to the real scorers. Holds no check logic of its own."""

    def __init__(self, pack: Pack, *, rubric_model: str | None = None,
                 cache_dir: Path | None = None, meter=None) -> None:
        if rubric_model and meter is None:
            # A configured judge means real, usage-HIDDEN spend. Metering it
            # cannot be opt-out at the spend boundary: without a meter the
            # calls run entirely uncharged and `exhausted()` never trips.
            raise ValueError(
                "a Confirmer with rubric_model set must be given a SpendMeter — "
                "tier-3 confirmations are live spend and metering is not optional")
        self.pack = pack
        self.rubric_model = rubric_model
        self.cache_dir = cache_dir
        self.meter = meter
        # THE line: confirmation evaluates exactly and only the candidate's
        # declared checks. `replace` copies the Pack dataclass and
        # `model_copy` the pydantic spec — the caller's pack is untouched.
        self.conf_pack = replace(
            pack, spec=pack.spec.model_copy(update={"invariants": []}))

    async def confirm(self, probe: Probe, messages: list[ChatMessage]) -> Confirmation:
        rubric_checks = [c for c in probe.checks if c.type == "rubric"]
        tier = 3 if rubric_checks else 1

        # Before anything is scored (or paid for): a candidate carrying a check
        # this boundary cannot evaluate is unsure, whatever the transcript says.
        problems = [(i, why) for i, c in enumerate(probe.checks)
                    if (why := _unevaluable(c)) is not None]
        if problems:
            detail = "; ".join(f"check[{i}]: {why}" for i, why in problems)
            warnings.warn(
                f"candidate {probe.id!r} declares check(s) the Confirmer cannot "
                f"evaluate ({detail}) — left UNCONFIRMED",
                RuntimeWarning, stacklevel=2)
            return Confirmation(False, True, tier, [],
                                f"unsure: unevaluable candidate check(s) — {detail}")

        state = TaskState(
            model="evalyn-discover", sample_id=probe.id, epoch=1, input="",
            messages=list(messages),
            metadata={"checks": [c.model_dump() for c in probe.checks]})

        s1 = await tier1_scorer(self.conf_pack)(state, Target(""))
        results: list[dict] = list((s1.metadata or {}).get("checks", []))

        if rubric_checks:
            if not self.rubric_model:
                # Fail closed: no judge configured means no verdict, not a free
                # confirmation off the deterministic checks alone.
                return Confirmation(False, True, tier, results,
                                    "no rubric judge configured — cannot confirm a "
                                    "tier-3 candidate")
            if self.meter is None:
                # Defence in depth: the constructor refuses this combination, so
                # reaching here means the meter was cleared after construction.
                # Unmetered live spend is not a thing this boundary will do.
                warnings.warn(
                    "no SpendMeter on the Confirmer — refusing an unmetered "
                    "tier-3 confirmation", RuntimeWarning, stacklevel=2)
                return Confirmation(False, True, tier, results,
                                    "unsure: refused an unmetered tier-3 confirmation")
            # Charged BEFORE the call: usage is hidden, so an unbilled call is
            # invisible spend. Charging first also means a call that raises is
            # still paid for, which is the conservative direction.
            self.meter.charge_estimate(
                tier3_confirmation_usd(self.rubric_model, len(rubric_checks)))
            try:
                s3 = await tier3_scorer(self.conf_pack, self.rubric_model,
                                        k=JUDGE_K, cache_dir=self.cache_dir)(
                    state, Target(""))
            except _PROGRAMMER_ERRORS:
                # A typo'd attribute or a schema mismatch is OUR bug, not a judge
                # outage. Degrading it to "unsure" would silently turn every
                # tier-3 candidate into a non-finding for the rest of the run,
                # with a RuntimeWarning as its only trace. Fail loudly instead.
                raise
            except Exception as e:  # environmental: judge outage, unloadable rubric
                warnings.warn(
                    f"tier-3 confirmation failed ({type(e).__name__}: {e}) — "
                    f"candidate left UNCONFIRMED", RuntimeWarning, stacklevel=2)
                return Confirmation(False, True, tier, results,
                                    f"tier-3 confirmation error: "
                                    f"{type(e).__name__}: {e}")
            judged = list((s3.metadata or {}).get("checks", []))
            if len(judged) < len(rubric_checks):
                # A rubric check that came back with no verdict is an unjudged
                # check, and an unjudged check must never be silently dropped —
                # the remaining (deterministic) checks could otherwise confirm
                # a candidate whose judged claim was never actually evaluated.
                warnings.warn(
                    f"tier-3 returned {len(judged)} verdict(s) for "
                    f"{len(rubric_checks)} rubric check(s) — candidate left "
                    f"UNCONFIRMED", RuntimeWarning, stacklevel=2)
                return Confirmation(False, True, tier, results + judged,
                                    "unsure: rubric check(s) came back unjudged")
            results += judged

        required_pass, unsure, _ = aggregate_trial(results)
        confirmed = (not required_pass) and (not unsure)
        return Confirmation(confirmed, unsure, tier, results,
                            _reason(confirmed, unsure, results))


def _reason(confirmed: bool, unsure: bool, results: list[dict]) -> str:
    """Human-facing summary — WHICH check decided it (agent feedback + artifact)."""
    required = [c for c in results if c["required"]]
    if confirmed:
        failed = [c for c in required if c["passed"] is False]
        return "confirmed: required " + "; ".join(
            f"{c['check']} FAILED ({c['evidence']})" for c in failed)
    if unsure:
        abstained = [c for c in results if c["unsure"]]
        return "unsure (never a finding): " + "; ".join(
            f"{c['check']} ({c['evidence']})" for c in abstained)
    if not required:
        return "not confirmed: candidate declares no required checks"
    return "not confirmed: all required checks passed (" + ", ".join(
        c["check"] for c in required) + ")"
