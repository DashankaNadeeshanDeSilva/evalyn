import json
import re

from inspect_ai.model import ModelOutput, ModelUsage

from evalyn.scoring.pairwise import _parse_pair, judge_pair

TONE = "# Tone\nCalm and professional.\n"

PERSONA = """# Persona

## voice
First person, in character.

## warmth
Friendly, never dismissive.
"""

# transcripts deliberately free of standalone "A"/"B" tokens so the blindness
# regex assertion below can hold over the WHOLE prompt
TA = "User: hi\nAssistant: alpha calm reply"
TB = "User: hi\nAssistant: bravo curt reply"

FACTS = "The owner has nine years of Python experience."


class _Rng:
    """Deterministic draw-2 order control: judge_pair shows A as Conversation 1
    on draw 2 iff rng.random() < 0.5."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


RNG_A_FIRST = 0.0   # draw 2: A shown as Conversation 1
RNG_B_FIRST = 0.9   # draw 2: B shown as Conversation 1


class _FakeJudge:
    """Injected fake judge: returns canned completions in order, records prompts."""

    def __init__(self, outputs, usages=None):
        self.outputs = list(outputs)
        self.usages = list(usages) if usages is not None else [None] * len(self.outputs)
        self.prompts = []

    async def generate(self, prompt):
        self.prompts.append(prompt)
        out = ModelOutput.from_content("mockllm/model", self.outputs.pop(0))
        usage = self.usages.pop(0)
        if usage is not None:
            out.usage = usage
        return out


def _stub(monkeypatch, outputs, usages=None, steps=("step one",)):
    from evalyn.scoring import pairwise as pw
    judge = _FakeJudge(outputs, usages)
    monkeypatch.setattr(pw, "get_model", lambda m: judge)

    async def fake_steps(rubric_text, rubric_hash, judge_model, cache_dir,
                         usage_acc=None):
        fake_steps.calls.append((rubric_text, rubric_hash, judge_model, cache_dir))
        return list(steps)

    fake_steps.calls = []
    monkeypatch.setattr(pw, "grading_steps", fake_steps)
    return judge, fake_steps


def _v(verdict, just="because", crit="Tone"):
    return json.dumps({"verdicts": {crit: {"verdict": verdict, "justification": just}}})


def _mv(verdicts: dict[str, str]) -> str:
    return json.dumps({"verdicts": {
        c: {"verdict": v, "justification": "j"} for c, v in verdicts.items()}})


async def _judge(monkeypatch, outputs, rng_value=RNG_A_FIRST, usages=None,
                 rubric=TONE, context=None, cache_dir=None):
    _stub(monkeypatch, outputs, usages)
    return await judge_pair(rubric, "hash-1", TA, TB, "mockllm/model",
                            cache_dir=cache_dir, context=context,
                            rng=_Rng(rng_value))


# --- strict pairwise parsing (mirrors tier3's _parse semantics) -------------


def test_parse_pair_valid():
    assert _parse_pair(_v("1"), ["Tone"]) == {"Tone": ("1", "because")}
    assert _parse_pair(_v("tie"), ["Tone"]) == {"Tone": ("tie", "because")}


def test_parse_pair_missing_criterion_is_unparseable():
    raw = _mv({"voice": "1"})
    assert _parse_pair(raw, ["voice", "warmth"]) is None


def test_parse_pair_wrong_verdict_token_is_unparseable():
    # only exactly "1" | "2" | "tie" count — A/B labels, ints, case variants
    # and free text all void the WHOLE draw (fail-closed, no partial credit)
    for bad in ('"A"', '"B"', "1", '"TIE"', '"Tie"', '"Conversation 1"', "true"):
        raw = ('{"verdicts": {"Tone": {"verdict": %s, '
               '"justification": "j"}}}' % bad)
        assert _parse_pair(raw, ["Tone"]) is None, bad


def test_parse_pair_non_json_is_unparseable():
    assert _parse_pair("Conversation 1 is better overall.", ["Tone"]) is None


def test_parse_pair_tolerant_key_matching_keys_by_canonical_names():
    # same fail-closed key resolution as tier3 (2026-07-30 calibrate fix):
    # case/whitespace variants and unique prefixes resolve, result is keyed by
    # the canonical criterion names
    raw = _mv({"Voice ": "1", "WARMTH": "tie"})
    assert _parse_pair(raw, ["voice", "warmth"]) == {
        "voice": ("1", "j"), "warmth": ("tie", "j")}


def test_parse_pair_ambiguous_key_is_unparseable():
    raw = _mv({"Claim": "1", "Claim clarity": "2"})
    assert _parse_pair(raw, ["Claim support", "Claim clarity"]) is None


def test_parse_pair_exact_key_beats_stray_prefix_key():
    # 2026-08-04 ruling (shared with tier3._parse): the exact-normalizing key
    # binds; the stray prefix key is ignored — the draw parses from the exact
    raw = _mv({"Specificity": "1", "specificity without overreach": "2"})
    assert _parse_pair(raw, ["Specificity without overreach"]) == {
        "Specificity without overreach": ("2", "j")}


def test_parse_pair_two_prefix_only_keys_still_void_the_draw():
    # equal-quality collision (two prefix-only keys, no exact) stays a
    # whole-draw void (fail-closed, per existing strictness)
    raw = _mv({"Specificity": "1", "Specificity without": "2"})
    assert _parse_pair(raw, ["Specificity without overreach"]) is None


# --- verdict rules (locked spec §2.2) --------------------------------------


async def test_a_wins_both_ordered_draws_and_third_agrees(monkeypatch):
    # brief case (a): draw 0 (A-first) says "1"=A, draw 1 (B-first) says
    # "2"=A, draw 2 (rng A-first) says "1"=A -> unanimous A
    res = await _judge(monkeypatch, [_v("1"), _v("2"), _v("1")])
    assert res.verdicts == {"Tone": "A"}
    assert res.flipped == {"Tone": False}
    assert res.votes == {"Tone": ["A", "A", "A"]}


async def test_flip_rule_forces_tie_even_against_majority(monkeypatch):
    # brief case (b): both ordered draws prefer the FIRST-SHOWN conversation
    # (draw 0 "1"=A, draw 1 "1"=B) -> order artifact -> flip rule -> tie,
    # even though draw 2 (A-first, "1"=A) gives A a 2/3 majority
    res = await _judge(monkeypatch, [_v("1"), _v("1"), _v("1")])
    assert res.verdicts == {"Tone": "tie"}
    assert res.flipped == {"Tone": True}
    assert res.votes == {"Tone": ["A", "B", "A"]}


async def test_flip_rule_second_shown_bias_also_ties(monkeypatch):
    # both ordered draws prefer the SECOND-shown (draw 0 "2"=B, draw 1 "2"=A)
    res = await _judge(monkeypatch, [_v("2"), _v("2"), _v("2")])
    assert res.verdicts == {"Tone": "tie"}
    assert res.flipped == {"Tone": True}


async def test_two_unparseable_draws_is_unsure(monkeypatch):
    # brief case (c): < 2 parsed votes -> unsure (a garbled judge can never
    # manufacture a win)
    res = await _judge(monkeypatch, ["not json", _v("1"), "garbage {"])
    assert res.verdicts == {"Tone": "unsure"}
    assert res.flipped == {"Tone": False}
    assert res.votes == {"Tone": ["B"]}  # draw 1 is B-first: "1" -> B


async def test_all_draws_unparseable_is_unsure_with_no_votes(monkeypatch):
    res = await _judge(monkeypatch, ["x", "y", "z"])
    assert res.verdicts == {"Tone": "unsure"}
    assert res.votes == {"Tone": []}


async def test_win_tie_tie_is_tie(monkeypatch):
    # brief case (d): 3 parsed votes, no side reaches 2 -> tie (tie votes
    # count toward no side)
    res = await _judge(monkeypatch, [_v("1"), _v("tie"), _v("tie")])
    assert res.verdicts == {"Tone": "tie"}
    assert res.flipped == {"Tone": False}
    assert res.votes == {"Tone": ["A", "tie", "tie"]}


async def test_majority_two_of_three_wins(monkeypatch):
    # draw 0 "2"=B, draw 1 "1"=B (same side, no flip), draw 2 (A-first) "1"=A
    res = await _judge(monkeypatch, [_v("2"), _v("1"), _v("1")])
    assert res.verdicts == {"Tone": "B"}
    assert res.flipped == {"Tone": False}
    assert res.votes == {"Tone": ["B", "B", "A"]}


async def test_exactly_two_parsed_same_side_wins(monkeypatch):
    # draw 0 garbled; draw 1 (B-first) "2"=A and draw 2 (A-first) "1"=A agree
    res = await _judge(monkeypatch, ["garbage", _v("2"), _v("1")])
    assert res.verdicts == {"Tone": "A"}
    assert res.votes == {"Tone": ["A", "A"]}


async def test_exactly_two_parsed_disagreeing_is_tie_not_flipped(monkeypatch):
    # flip rule needs draws 0 AND 1 both parsed; here draw 1 is garbled, so
    # the A-vs-B disagreement is a plain rule-3 tie with flipped=False
    res = await _judge(monkeypatch, [_v("1"), "garbage", _v("2")])
    assert res.verdicts == {"Tone": "tie"}
    assert res.flipped == {"Tone": False}
    assert res.votes == {"Tone": ["A", "B"]}


async def test_exactly_two_parsed_with_a_tie_vote_is_tie(monkeypatch):
    # rule 3: "anything else" (win + tie) -> tie
    res = await _judge(monkeypatch, [_v("1"), "garbage", _v("tie")])
    assert res.verdicts == {"Tone": "tie"}
    assert res.flipped == {"Tone": False}


async def test_draw2_order_follows_rng(monkeypatch):
    # rng >= 0.5 -> draw 2 shows B as Conversation 1, so its "2" means A;
    # with draw 1 (B-first) also "2"=A the two parsed votes agree in A/B
    # terms (an implementation ignoring the rng order would read draw 2 as B).
    # 2026-08-04 ruling: both survivors showed the SAME order (B-first), so
    # the agreeing pair is a "tie", never a win — but the vote mapping still
    # pins the rng-controlled order.
    res = await _judge(monkeypatch, ["garbage", _v("2"), _v("2")],
                       rng_value=RNG_B_FIRST)
    assert res.verdicts == {"Tone": "tie"}
    assert res.votes == {"Tone": ["A", "A"]}


async def test_rule3_same_order_survivors_cannot_win(monkeypatch):
    # 2026-08-04 ruling: exactly 2 parsed draws that showed the SAME order
    # (here d0 and d2 both A-first, d1 garbled) agreeing on A -> "tie" — a
    # positionally biased judge must never manufacture a win without order
    # control
    res = await _judge(monkeypatch, [_v("1"), "garbage", _v("1")],
                       rng_value=RNG_A_FIRST)
    assert res.verdicts == {"Tone": "tie"}
    assert res.flipped == {"Tone": False}
    assert res.votes == {"Tone": ["A", "A"]}


async def test_rule3_opposite_order_survivors_still_win(monkeypatch):
    # d1 garbled; d0 A-first "1"=A and d2 (rng forced B-first) "2"=A agree
    # across OPPOSITE orders -> the win stands
    res = await _judge(monkeypatch, [_v("1"), "garbage", _v("2")],
                       rng_value=RNG_B_FIRST)
    assert res.verdicts == {"Tone": "A"}
    assert res.votes == {"Tone": ["A", "A"]}


async def test_per_criterion_verdicts_are_independent(monkeypatch):
    # voice: A, A, A -> "A"; warmth: draw 0 "1"=A vs draw 1 "1"=B -> flip tie
    outs = [_mv({"voice": "1", "warmth": "1"}),
            _mv({"voice": "2", "warmth": "1"}),
            _mv({"voice": "1", "warmth": "tie"})]
    res = await _judge(monkeypatch, outs, rubric=PERSONA)
    assert res.verdicts == {"voice": "A", "warmth": "tie"}
    assert res.flipped == {"voice": False, "warmth": True}


# --- blindness (locked: prompts only ever say Conversation 1 / 2) -----------


async def test_prompts_are_blind_and_order_controlled(monkeypatch):
    # brief case (e): no prompt ever names A/B; draw 0 shows transcript_a as
    # Conversation 1, draw 1 shows transcript_b as Conversation 1 (swap), and
    # draw 2 follows the rng (A-first here)
    judge, _ = _stub(monkeypatch, [_v("tie")] * 3)
    await judge_pair(TONE, "hash-1", TA, TB, "mockllm/model",
                     rng=_Rng(RNG_A_FIRST))
    assert len(judge.prompts) == 3
    for p in judge.prompts:
        assert re.search(r"\b[AB]\b", p) is None
        assert "Conversation 1:" in p and "Conversation 2:" in p
    p0, p1, p2 = judge.prompts
    assert p0.index("Conversation 1:") < p0.index(TA) < p0.index("Conversation 2:") < p0.index(TB)
    assert p1.index("Conversation 1:") < p1.index(TB) < p1.index("Conversation 2:") < p1.index(TA)
    assert p2.index(TA) < p2.index(TB)


async def test_prompt_renders_verbatim_without_context(monkeypatch):
    # context=None leaves the locked prompt constant fully pinned (mirrors the
    # tier3 byte-identical prompt pin)
    judge, _ = _stub(monkeypatch, [_v("tie")] * 3)
    await judge_pair(TONE, "hash-1", TA, TB, "mockllm/model",
                     rng=_Rng(RNG_A_FIRST))
    expected = (
        "You are a strict, impartial evaluation judge. Two configurations of the\n"
        "same product each produced a conversation. Compare the ASSISTANT's behavior in the two\n"
        "conversations on the rubric criteria below, following these evaluation steps:\n"
        "- step one\n"
        "\n"
        "Criteria: Tone\n"
        "\n"
        "For EACH criterion decide which conversation shows better assistant behavior. Reply with\n"
        'ONLY a JSON object of the form:\n'
        '{"verdicts": {"<criterion>": {"verdict": "1"|"2"|"tie", "justification": "<one sentence>"}, ...}}\n'
        'with exactly one entry per listed criterion. "1" means Conversation 1 is better, "2" means\n'
        'Conversation 2 is better, "tie" means no meaningful difference.\n'
        "\n"
        "Conversation 1:\n"
        "User: hi\n"
        "Assistant: alpha calm reply\n"
        "\n"
        "Conversation 2:\n"
        "User: hi\n"
        "Assistant: bravo curt reply\n")
    assert judge.prompts[0] == expected


async def test_context_block_reuses_fact_sheet_wording(monkeypatch):
    # Task 2's fact-sheet block, verbatim wording, between steps and criteria
    judge, _ = _stub(monkeypatch, [_v("tie")] * 3)
    await judge_pair(TONE, "hash-1", TA, TB, "mockllm/model",
                     context=FACTS, rng=_Rng(RNG_A_FIRST))
    for p in judge.prompts:
        assert "Reference fact sheet" in p and FACTS in p
        assert p.index("- step one") < p.index("Reference fact sheet") < p.index("Criteria:")


async def test_no_context_omits_fact_sheet_block(monkeypatch):
    judge, _ = _stub(monkeypatch, [_v("tie")] * 3)
    await judge_pair(TONE, "hash-1", TA, TB, "mockllm/model",
                     rng=_Rng(RNG_A_FIRST))
    assert all("Reference fact sheet" not in p for p in judge.prompts)


# --- steps, hash, justifications, usage ------------------------------------


async def test_steps_obtained_via_grading_steps_with_cache_dir(monkeypatch, tmp_path):
    judge, fake_steps = _stub(monkeypatch, [_v("tie")] * 3)
    res = await judge_pair(TONE, "hash-1", TA, TB, "mockllm/model",
                           cache_dir=tmp_path, rng=_Rng(RNG_A_FIRST))
    assert fake_steps.calls == [(TONE, "hash-1", "mockllm/model", tmp_path)]
    assert res.steps == ["step one"]
    assert res.rubric_hash == "hash-1"
    assert all("- step one" in p for p in judge.prompts)


async def test_provided_steps_bypass_generation(monkeypatch):
    # frozen pack steps (rubrics/<rid>.steps.json) arrive via the caller and
    # are used verbatim — the grading_steps seam must not run at all,
    # mirroring score_transcript's frozen-steps injection (2026-08-03 ruling)
    from evalyn.scoring import pairwise as pw
    judge = _FakeJudge([_v("tie")] * 3)
    monkeypatch.setattr(pw, "get_model", lambda m: judge)

    async def boom(*a, **kw):
        raise AssertionError("grading_steps must not be called with frozen steps")

    monkeypatch.setattr(pw, "grading_steps", boom)
    res = await judge_pair(TONE, "hash-1", TA, TB, "mockllm/model",
                           steps=["frozen pairwise step"], rng=_Rng(RNG_A_FIRST))
    assert res.steps == ["frozen pairwise step"]
    assert all("- frozen pairwise step" in p for p in judge.prompts)


async def test_steps_none_still_generates_via_seam(monkeypatch, tmp_path):
    # steps=None keeps today's behavior: the shared grading_steps seam runs
    judge, fake_steps = _stub(monkeypatch, [_v("tie")] * 3)
    res = await judge_pair(TONE, "hash-1", TA, TB, "mockllm/model",
                           cache_dir=tmp_path, steps=None, rng=_Rng(RNG_A_FIRST))
    assert fake_steps.calls == [(TONE, "hash-1", "mockllm/model", tmp_path)]
    assert res.steps == ["step one"]


async def test_justifications_keep_last_parsed_draw(monkeypatch):
    res = await _judge(monkeypatch, [_v("1", just="first"),
                                     _v("1", just="second"), "garbage"])
    assert res.justifications == {"Tone": "second"}


async def test_justifications_empty_when_nothing_parsed(monkeypatch):
    res = await _judge(monkeypatch, ["x", "y", "z"])
    assert res.justifications == {"Tone": ""}


async def test_usage_accumulated_over_three_draws(monkeypatch):
    # brief case (f): usage summed across draws; a draw with no usage counts
    # as zeros (never crashes)
    usages = [ModelUsage(input_tokens=10, output_tokens=4),
              None,
              ModelUsage(input_tokens=5, output_tokens=2)]
    res = await _judge(monkeypatch, [_v("1"), _v("2"), _v("1")], usages=usages)
    assert res.usage == {"mockllm/model": {"input_tokens": 15, "output_tokens": 6}}


async def test_generated_steps_usage_metered_into_verdict(monkeypatch, tmp_path):
    # steps=None + cache miss: the grading-steps generation call's tokens must
    # reach PairVerdict.usage (they are judge spend — compare meters judge_usd
    # from exactly this dict)
    from evalyn.scoring import pairwise as pw
    from evalyn.scoring import rubrics as rb
    judge = _FakeJudge([_v("tie")] * 3,
                       usages=[ModelUsage(input_tokens=10, output_tokens=4)] * 3)
    steps_model = _FakeJudge(['["step one"]'],
                             usages=[ModelUsage(input_tokens=100, output_tokens=20)])
    monkeypatch.setattr(pw, "get_model", lambda m: judge)
    monkeypatch.setattr(rb, "get_model", lambda m: steps_model)
    res = await judge_pair(TONE, "hash-1", TA, TB, "mockllm/model",
                           cache_dir=tmp_path, rng=_Rng(RNG_A_FIRST))
    assert res.steps == ["step one"]
    assert res.usage == {"mockllm/model": {"input_tokens": 130,
                                           "output_tokens": 32}}


async def test_provided_steps_add_no_generation_usage(monkeypatch):
    # steps provided -> no generation call, usage is the 3 draws only
    from evalyn.scoring import pairwise as pw
    judge = _FakeJudge([_v("tie")] * 3,
                       usages=[ModelUsage(input_tokens=10, output_tokens=4)] * 3)
    monkeypatch.setattr(pw, "get_model", lambda m: judge)
    res = await judge_pair(TONE, "hash-1", TA, TB, "mockllm/model",
                           steps=["frozen"], rng=_Rng(RNG_A_FIRST))
    assert res.usage == {"mockllm/model": {"input_tokens": 30,
                                           "output_tokens": 12}}


async def test_usage_all_missing_is_zeros(monkeypatch):
    res = await _judge(monkeypatch, [_v("tie")] * 3)
    assert res.usage == {"mockllm/model": {"input_tokens": 0, "output_tokens": 0}}


async def test_verdict_is_json_serializable(monkeypatch):
    # compare artifacts embed the verdict fields
    res = await _judge(monkeypatch, [_v("1"), _v("2"), _v("1")])
    json.dumps({"verdicts": res.verdicts, "flipped": res.flipped,
                "votes": res.votes, "justifications": res.justifications,
                "steps": res.steps, "rubric_hash": res.rubric_hash,
                "usage": res.usage})
