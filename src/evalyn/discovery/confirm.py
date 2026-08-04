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
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path

from inspect_ai.model import ChatMessage, ModelUsage
from inspect_ai.scorer import Target
from inspect_ai.solver import TaskState

from evalyn.engine.budget import estimate_cost
from evalyn.scoring.checks import aggregate_trial
from evalyn.scoring.tier1 import tier1_scorer
from evalyn.scoring.tier3 import tier3_scorer
from evalyn.targets.loader import Pack
from evalyn.targets.schema import Probe

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
            # Charged BEFORE the call: usage is hidden, so an unbilled call is
            # invisible spend. Charging first also means a call that raises is
            # still paid for, which is the conservative direction.
            if self.meter is not None:
                self.meter.charge_estimate(
                    tier3_confirmation_usd(self.rubric_model, len(rubric_checks)))
            try:
                s3 = await tier3_scorer(self.conf_pack, self.rubric_model,
                                        k=JUDGE_K, cache_dir=self.cache_dir)(
                    state, Target(""))
            except Exception as e:  # judge outage / unloadable rubric
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
