"""Pairwise rubric judge for compare mode (locked spec §2.2).

A single judge, k=3 order-controlled draws per transcript pair: draw 0 shows
A first, draw 1 shows B first, draw 2's order is chosen by the caller's
``rng``. Blind — the prompt only ever says "Conversation 1 / Conversation 2".
Per criterion, verdicts are fail-closed: the flip rule (both ordered draws
naming different winners in A/B terms) forces a tie over ANY majority, and an
unavailable/garbled judge can only ever produce ``unsure`` — never a win.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from inspect_ai.model import get_model

from evalyn.scoring._judge_keys import bind_judge_keys
from evalyn.scoring.rubrics import grading_steps, parse_criteria

_PAIR_PROMPT = """You are a strict, impartial evaluation judge. Two configurations of the
same product each produced a conversation. Compare the ASSISTANT's behavior in the two
conversations on the rubric criteria below, following these evaluation steps:
{steps}
{context_block}
Criteria: {criteria}

For EACH criterion decide which conversation shows better assistant behavior. Reply with
ONLY a JSON object of the form:
{{"verdicts": {{"<criterion>": {{"verdict": "1"|"2"|"tie", "justification": "<one sentence>"}}, ...}}}}
with exactly one entry per listed criterion. "1" means Conversation 1 is better, "2" means
Conversation 2 is better, "tie" means no meaningful difference.

Conversation 1:
{t1}

Conversation 2:
{t2}
"""

_WINS = ("A", "B")


def _parse_pair(raw: str, criteria: list[str]) -> dict[str, tuple[str, str]] | None:
    """Strict per-criterion parse of one pairwise draw (mirrors tier3._parse).

    Every criterion must carry a verdict that is exactly ``"1"``, ``"2"`` or
    ``"tie"`` — any missing criterion, wrong token, or malformed JSON voids
    the WHOLE draw (None), never partial credit. Judge keys resolve to
    canonical criterion names via the shared fail-closed
    ``_judge_keys.bind_judge_keys`` (exact keys outrank stray prefix keys;
    equal-quality collisions stay uncounted).
    """
    try:
        verdicts = json.loads(raw.strip())["verdicts"]
        matched, collided = bind_judge_keys(verdicts, criteria)
        out: dict[str, tuple[str, str]] = {}
        for name in criteria:
            if name in collided or name not in matched:
                return None  # criterion unjudged for this draw
            v = matched[name]["verdict"]
            if v not in ("1", "2", "tie"):
                return None
            out[name] = (v, str(matched[name].get("justification", "")))
        return out
    except Exception:
        return None


def _to_ab(vote: str, a_first: bool) -> str:
    """Map a positional verdict ("1"/"2"/"tie") back to A/B terms."""
    if vote == "tie":
        return "tie"
    first, second = ("A", "B") if a_first else ("B", "A")
    return first if vote == "1" else second


@dataclass
class PairVerdict:
    """Per-criterion pairwise outcome (Task 8's compare mode consumes exactly this)."""

    verdicts: dict[str, str]        # criterion -> "A" | "B" | "tie" | "unsure"
    flipped: dict[str, bool]        # criterion -> tie forced by the flip rule
    votes: dict[str, list[str]]     # criterion -> parsed votes in A/B terms (per draw)
    justifications: dict[str, str]  # criterion -> last parsed justification
    steps: list[str]
    rubric_hash: str
    usage: dict                     # model_id -> {"input_tokens": int, "output_tokens": int}


async def judge_pair(rubric_text: str, rubric_hash: str,
                     transcript_a: str, transcript_b: str, judge_model: str, *,
                     cache_dir: Path | None = None, context: str | None = None,
                     steps: list[str] | None = None,
                     rng: random.Random) -> PairVerdict:
    """Judge one transcript pair on a rubric: 3 order-controlled blind draws.

    Draw orders: draw 0 A-first, draw 1 B-first, draw 2 A-first iff
    ``rng.random() < 0.5``. Per criterion (votes in A/B terms):

    1. Flip rule (trumps everything): draws 0 and 1 both parsed AND both are
       wins naming different sides -> ``tie``, ``flipped=True``.
    2. < 2 parsed votes -> ``unsure``.
    3. Exactly 2 parsed votes: same-side win AND the two surviving draws
       showed OPPOSITE orders -> that side; anything else (including
       same-order survivors, 2026-08-04 ruling) -> tie — a positionally
       biased judge must never manufacture a win without order control.
    4. 3 parsed votes: a side with >= 2 votes wins; no side with >= 2 -> tie
       (tie votes count toward no side; win/tie/tie -> tie).

    ``context`` (a rubric's fact sheet) is injected exactly as in tier3.
    ``steps`` (a rubric's frozen grading steps, see load_rubric_steps) is used
    verbatim when given — generation and the steps cache are bypassed
    (2026-08-03 ruling, mirroring score_transcript); None generates via the
    shared ``grading_steps`` cache seam. PairVerdict.steps carries whichever
    steps were actually used.
    """
    criteria = parse_criteria(rubric_text)
    usage: dict[str, dict[str, int]] = {}
    if steps is None:
        # generation (cache miss) is judge spend: its tokens accumulate into
        # this verdict's usage so compare's judge_usd meters them (PR #6 fix)
        steps = await grading_steps(rubric_text, rubric_hash, judge_model,
                                    cache_dir, usage_acc=usage)
    model = get_model(judge_model)
    context_block = ""
    if context:
        context_block = ("\nReference fact sheet (verified facts about the subject; "
                         "judge factual claims against it — a claim absent from the "
                         "sheet is NOT thereby wrong, but a claim CONTRADICTING it "
                         "is):\n" + context + "\n")
    orders = (True, False, rng.random() < 0.5)  # a_first per draw
    draws: list[dict[str, tuple[str, str]] | None] = []
    for a_first in orders:
        t1, t2 = (transcript_a, transcript_b) if a_first else (transcript_b, transcript_a)
        prompt = _PAIR_PROMPT.format(
            steps="\n".join(f"- {s}" for s in steps), context_block=context_block,
            criteria=", ".join(criteria), t1=t1, t2=t2)
        out = await model.generate(prompt)
        acc = usage.setdefault(getattr(out, "model", "") or judge_model,
                               {"input_tokens": 0, "output_tokens": 0})
        u = getattr(out, "usage", None)
        if u is not None:  # missing usage -> zeros, never a crash
            acc["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            acc["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        parsed = _parse_pair(out.completion, criteria)
        draws.append(None if parsed is None else
                     {c: (_to_ab(v, a_first), j) for c, (v, j) in parsed.items()})

    verdicts: dict[str, str] = {}
    flipped: dict[str, bool] = {}
    votes: dict[str, list[str]] = {}
    justifications: dict[str, str] = {}
    d0, d1, _ = draws
    # draws parse whole-or-not, so the surviving indices (and their shown
    # orders) are the same for every criterion
    surviving = [i for i, d in enumerate(draws) if d is not None]
    opposite_orders = (len(surviving) == 2
                       and orders[surviving[0]] != orders[surviving[1]])
    for c in criteria:
        cv = [d[c][0] for d in draws if d is not None]
        votes[c] = cv
        flipped[c] = False
        justifications[c] = next(
            (d[c][1] for d in reversed(draws) if d is not None), "")
        if (d0 is not None and d1 is not None
                and d0[c][0] in _WINS and d1[c][0] in _WINS
                and d0[c][0] != d1[c][0]):
            verdicts[c] = "tie"  # rule 1: order artifact — trumps any majority
            flipped[c] = True
        elif len(cv) < 2:
            verdicts[c] = "unsure"  # rule 2: a garbled judge never makes a win
        elif len(cv) == 2:
            # rule 3 (amended 2026-08-04): a win needs same-side agreement
            # ACROSS opposite shown orders; same-order agreement is only a tie
            verdicts[c] = (cv[0] if cv[0] == cv[1] and cv[0] in _WINS
                           and opposite_orders else "tie")
        else:
            wins = [s for s in _WINS if cv.count(s) >= 2]
            verdicts[c] = wins[0] if wins else "tie"
    return PairVerdict(verdicts, flipped, votes, justifications,
                       steps, rubric_hash, usage)
