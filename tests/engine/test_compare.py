"""Task 8: compare engine — blind pairwise A/B over two gate artifacts.

Fully offline: `judge_pair` is monkeypatched with scripted stubs (zero judge
tokens, zero target sessions). The locked semantics pinned here: preconditions
before any judge call, epoch-zip pairing with exclusions, one tally per
pair x criterion, hard metrics ONLY from trial_records (exact p95 formula),
write-artifact-then-raise BudgetExceeded, SimpleNamespace usage metering.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from evalyn.engine.budget import BudgetExceeded
from evalyn.engine.compare import (
    CompareArtifact,
    render_compare_report,
    run_compare,
    write_compare_artifact,
)
from evalyn.engine.run import ProbeResult, RunArtifact, pack_fingerprint
from evalyn.scoring.pairwise import PairVerdict
from evalyn.scoring.rubrics import parse_criteria
from evalyn.targets.loader import load_pack

TONE_RUBRIC = "# Tone rubric\n## Calm\nStays calm.\n## Clear\nIs clear.\n"


def _write_pack(tmp_path: Path, *, budget_usd: float | None = None,
                steps: list[str] | None = None, facts: str | None = None,
                extra_probe: bool = True):
    """On-disk pack: one rubric-checked probe `r1` (+ a checks-only `h1`)."""
    d = tmp_path / "cpack"
    (d / "probes").mkdir(parents=True)
    (d / "rubrics").mkdir()
    target = ("name: cmp\n"
              "sessions:\n"
              "  open: {method: POST, path: /session}\n"
              "  message: {method: POST, path: /chat}\n"
              "env: {base_url: http://localhost:8899}\n"
              "allowlist: [http://localhost:8899]\n")
    if budget_usd is not None:
        target += f"budget: {{max_usd_per_run: {budget_usd}}}\n"
    (d / "target.yaml").write_text(target)
    (d / "rubrics" / "tone.md").write_text(TONE_RUBRIC)
    if steps is not None:
        (d / "rubrics" / "tone.steps.json").write_text(json.dumps(steps))
    if facts is not None:
        (d / "rubrics" / "tone.facts.md").write_text(facts)
    probes = ("- id: r1\n  category: chat\n  turns: [hi]\n  checks:\n"
              "    - { type: rubric, rubric: tone, required: true }\n")
    if extra_probe:
        probes += ("- id: h1\n  category: ops\n  turns: [hi]\n  checks:\n"
                   "    - { type: contains, value: hi }\n")
    (d / "probes" / "p.yaml").write_text(probes)
    return load_pack(str(d))


def _rec(epoch: int, transcript: str = "User: hi\nAssistant: hello",
         secs: float | None = 1.0, inv: int = 0) -> dict:
    return {"epoch": epoch, "transcript": transcript,
            "session_seconds": secs, "invariant_failures": inv}


def _probe(pid: str, cat: str, records: list[dict]) -> ProbeResult:
    return ProbeResult(id=pid, category=cat, kind="regression",
                       safety_critical=False, samples=max(len(records), 1),
                       trials=len(records), trial_records=records)


def _art(pack, probes: list[ProbeResult], *, pack_hash: str | None = None,
         created_at: str = "2026-08-01T00:00:00+00:00") -> RunArtifact:
    return RunArtifact(
        pack_name="cmp", pack_hash=pack_hash or pack_fingerprint(pack),
        judge_model="mockllm/model", created_at=created_at,
        probes=probes, log_path="runs/logs")


def _two_sided(pack, n_a: int = 2, n_b: int = 2):
    """Artifacts with `r1` (rubric) and `h1` (no rubric) on both sides."""
    art_a = _art(pack, [
        _probe("r1", "chat", [_rec(i) for i in range(n_a)]),
        _probe("h1", "ops", [_rec(0, secs=2.0)]),
    ])
    art_b = _art(pack, [
        _probe("r1", "chat", [_rec(i) for i in range(n_b)]),
        _probe("h1", "ops", [_rec(0, secs=4.0)]),
    ], created_at="2026-08-02T00:00:00+00:00")
    return art_a, art_b


class StubJudge:
    """Scripted judge_pair: same verdict for every criterion, recorded calls."""

    def __init__(self, verdict: str = "A", flipped: bool = False,
                 usage: dict | None = None):
        self.verdict, self.flipped = verdict, flipped
        self.usage = usage if usage is not None else {
            "openai/gpt-4o": {"input_tokens": 1000, "output_tokens": 1000}}
        self.calls: list[dict] = []

    async def __call__(self, rubric_text, rubric_hash, transcript_a,
                       transcript_b, judge_model, *, cache_dir=None,
                       context=None, steps=None, rng):
        self.calls.append({"rubric_hash": rubric_hash, "a": transcript_a,
                           "b": transcript_b, "context": context,
                           "steps": steps, "cache_dir": cache_dir})
        crits = parse_criteria(rubric_text)
        return PairVerdict(
            verdicts={c: self.verdict for c in crits},
            flipped={c: self.flipped for c in crits},
            votes={c: [] for c in crits},
            justifications={c: "because" for c in crits},
            steps=steps or ["generated"], rubric_hash=rubric_hash,
            usage={m: dict(u) for m, u in self.usage.items()})


def _run(pack, art_a, art_b, **kw):
    return asyncio.run(run_compare(pack, art_a, art_b, "openai/gpt-4o", **kw))


# --------------------------------------------------- preconditions (fail first)

def test_pack_hash_mismatch_side_a_raises_before_any_judging(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    _, art_b = _two_sided(pack)
    art_a = _art(pack, [_probe("r1", "chat", [_rec(0)])], pack_hash="f" * 64)
    with pytest.raises(ValueError, match="A"):
        _run(pack, art_a, art_b)
    assert stub.calls == []  # precondition fired BEFORE any judge call


def test_pack_hash_mismatch_side_b_named_in_message(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, _ = _two_sided(pack)
    art_b = _art(pack, [_probe("r1", "chat", [_rec(0)])], pack_hash="e" * 64)
    with pytest.raises(ValueError, match="B"):
        _run(pack, art_a, art_b)
    assert stub.calls == []


def test_missing_transcripts_raises_predates_capture(tmp_path, monkeypatch):
    # a pre-#2b artifact loads with trial_records=[] — compare must refuse it
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a = _art(pack, [_probe("r1", "chat", []), _probe("h1", "ops", [])])
    _, art_b = _two_sided(pack)
    with pytest.raises(ValueError, match="predates transcript capture"):
        _run(pack, art_a, art_b)
    assert stub.calls == []


def test_empty_transcript_string_also_predates_capture(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a = _art(pack, [_probe("r1", "chat", [_rec(0, transcript="")]),
                        _probe("h1", "ops", [])])
    _, art_b = _two_sided(pack)
    with pytest.raises(ValueError, match="predates transcript capture"):
        _run(pack, art_a, art_b)
    assert stub.calls == []


# ------------------------------------------------------------------- tallying

def test_a_wins_everywhere_tallies_all_wins_a(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge(verdict="A")
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack)  # r1: 2 pairs x 2 criteria (Calm, Clear)
    art = _run(pack, art_a, art_b)
    assert len(stub.calls) == 2  # one judge call per (pair x rubric)
    chat = art.categories["chat"]
    assert chat == {"wins_a": 4, "wins_b": 0, "ties": 0, "unsure": 0,
                    "flips": 0, "criteria_judged": 4, "flip_rate": 0.0}
    r1 = next(p for p in art.probes if p["id"] == "r1")
    assert r1["pairs_judged"] == 2 and r1["excluded_trials"] == 0
    assert [e["epoch"] for e in r1["rubrics"]["tone"]] == [0, 1]
    assert r1["rubrics"]["tone"][0]["verdicts"] == {"Calm": "A", "Clear": "A"}
    assert r1["rubrics"]["tone"][0]["justifications"]["Calm"] == "because"
    # h1 has no rubric checks: hard metrics only, nothing judged
    h1 = next(p for p in art.probes if p["id"] == "h1")
    assert h1["pairs_judged"] == 0 and h1["rubrics"] == {}
    assert "ops" not in art.categories


def test_flipped_verdict_counts_tie_and_flip_rate(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge(verdict="tie", flipped=True)
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack, n_a=1, n_b=1)
    art = _run(pack, art_a, art_b)
    chat = art.categories["chat"]
    assert chat["ties"] == 2 and chat["flips"] == 2
    assert chat["wins_a"] == 0 and chat["wins_b"] == 0
    assert chat["flip_rate"] == pytest.approx(1.0)
    r1 = next(p for p in art.probes if p["id"] == "r1")
    assert r1["rubrics"]["tone"][0]["flipped"] == {"Calm": True, "Clear": True}


def test_unsure_excluded_from_wlt_but_counted(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge(verdict="unsure")
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack, n_a=1, n_b=1)
    art = _run(pack, art_a, art_b)
    chat = art.categories["chat"]
    assert chat["unsure"] == 2
    assert chat["wins_a"] == 0 and chat["wins_b"] == 0 and chat["ties"] == 0
    assert chat["criteria_judged"] == 2  # unsure still counts toward the denominator
    assert chat["flip_rate"] == 0.0


def test_unequal_trial_counts_zip_and_count_exclusions(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack, n_a=3, n_b=1)
    art = _run(pack, art_a, art_b)
    assert len(stub.calls) == 1  # only the zipped pair is judged
    r1 = next(p for p in art.probes if p["id"] == "r1")
    assert r1["pairs_judged"] == 1 and r1["excluded_trials"] == 2
    assert art.excluded_pairs == 2


def test_pairing_sorts_trial_records_by_epoch(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a = _art(pack, [
        _probe("r1", "chat", [_rec(1, transcript="A-late"),
                              _rec(0, transcript="A-early")]),
        _probe("h1", "ops", [])])
    art_b = _art(pack, [
        _probe("r1", "chat", [_rec(0, transcript="B-early"),
                              _rec(1, transcript="B-late")]),
        _probe("h1", "ops", [])])
    _run(pack, art_a, art_b)
    assert [(c["a"], c["b"]) for c in stub.calls] == [
        ("A-early", "B-early"), ("A-late", "B-late")]


# --------------------------------------- frozen steps / context threading

def test_frozen_steps_and_facts_passed_through_to_judge_pair(tmp_path, monkeypatch):
    # USER RULING 2026-08-03: frozen pack steps + fact sheet reach judge_pair as-is
    pack = _write_pack(tmp_path, steps=["step one", "step two"],
                       facts="The sky is blue.")
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack, n_a=1, n_b=1)
    _run(pack, art_a, art_b, cache_dir=tmp_path / "cache")
    call = stub.calls[0]
    assert call["steps"] == ["step one", "step two"]
    assert call["context"] == "The sky is blue."
    assert call["cache_dir"] == tmp_path / "cache"


def test_absent_steps_and_facts_pass_none(tmp_path, monkeypatch):
    # None -> judge_pair generates via its own seam (with cache_dir)
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack, n_a=1, n_b=1)
    _run(pack, art_a, art_b)
    call = stub.calls[0]
    assert call["steps"] is None and call["context"] is None
    assert call["cache_dir"] is None


# ------------------------------------------------------------- hard metrics

def test_hard_metrics_exact_mean_p95_from_trial_records(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path, extra_probe=False)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a = _art(pack, [_probe("r1", "chat", [
        _rec(0, secs=1.0), _rec(1, secs=2.0), _rec(2, secs=3.0),
        _rec(3, secs=None, inv=2)])])   # None latency excluded, trial counted
    art_b = _art(pack, [_probe("r1", "chat", [
        _rec(0, secs=4.0, inv=1), _rec(1, secs=8.0)])])
    art = _run(pack, art_a, art_b)
    m = art.hard_metrics["chat"]
    assert m["latency_mean_a"] == pytest.approx(2.0)
    # p95 = sorted(vals)[max(0, ceil(0.95*len(vals)) - 1)]: [1,2,3] -> idx 2
    assert m["latency_p95_a"] == pytest.approx(3.0)
    assert m["latency_mean_b"] == pytest.approx(6.0)
    assert m["latency_p95_b"] == pytest.approx(8.0)
    assert m["invariant_failures_a"] == 2 and m["invariant_failures_b"] == 1
    assert m["trials_a"] == 4 and m["trials_b"] == 2


def test_hard_metrics_cover_probes_without_rubric_checks(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack)
    art = _run(pack, art_a, art_b)
    ops = art.hard_metrics["ops"]  # h1 has no rubric checks — metrics only
    assert ops["latency_mean_a"] == pytest.approx(2.0)
    assert ops["latency_mean_b"] == pytest.approx(4.0)
    assert ops["trials_a"] == 1 and ops["trials_b"] == 1


def test_hard_metrics_none_when_no_latency_signal(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path, extra_probe=False)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a = _art(pack, [_probe("r1", "chat", [_rec(0, secs=None)])])
    art_b = _art(pack, [_probe("r1", "chat", [_rec(0, secs=None)])])
    art = _run(pack, art_a, art_b)
    m = art.hard_metrics["chat"]
    assert m["latency_mean_a"] is None and m["latency_p95_a"] is None
    assert m["trials_a"] == 1  # the trial itself still counts


# ------------------------------------------------- metering + budget ordering

def test_judge_usd_nonzero_from_scripted_usage(tmp_path, monkeypatch):
    # the metering-shape gotcha: PairVerdict.usage carries plain dicts;
    # estimate_cost reads ATTRIBUTES — a raw dict would silently meter $0.00
    pack = _write_pack(tmp_path)
    stub = StubJudge()  # 1000 in + 1000 out on gpt-4o per call
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack)  # 2 judged pairs
    art = _run(pack, art_a, art_b)
    # gpt-4o: (0.0025 + 0.010) per 1k+1k tokens, per call
    assert art.judge_usd == pytest.approx(2 * 0.0125)
    assert art.judge_usd > 0.0


def test_budget_breach_writes_artifact_then_raises(tmp_path, monkeypatch):
    # house write-before-raise: the artifact must be on disk AFTER the raise
    pack = _write_pack(tmp_path, budget_usd=0.001)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    monkeypatch.chdir(tmp_path)  # write_compare_artifact defaults to runs/
    art_a, art_b = _two_sided(pack)
    with pytest.raises(BudgetExceeded, match="max_usd_per_run"):
        _run(pack, art_a, art_b)
    written = list((tmp_path / "runs").glob("*-compare.json"))
    assert written, "budget breach must write the compare artifact FIRST"
    saved = CompareArtifact.from_dict(json.loads(written[0].read_text()))
    assert saved.judge_usd == pytest.approx(2 * 0.0125)  # nonzero, metered
    assert saved.categories["chat"]["wins_a"] == 4  # verdicts survived


def test_budget_breach_write_honors_out_dir_and_real_labels(tmp_path, monkeypatch):
    # Fix ruling 2026-08-03 (additive kwargs): the breach artifact lands in the
    # caller's out_dir and carries the real labels/sources from construction —
    # never placeholder "A"/"B" + empty sources patched post-hoc by the CLI.
    pack = _write_pack(tmp_path, budget_usd=0.001)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack)
    out = tmp_path / "elsewhere"
    with pytest.raises(BudgetExceeded, match="max_usd_per_run"):
        asyncio.run(run_compare(
            pack, art_a, art_b, "openai/gpt-4o", out_dir=str(out),
            label_a="main", label_b="candidate",
            source_a="a.json", source_b="b.json"))
    written = list(out.glob("*-compare.json"))
    assert written, "breach artifact must land in the caller's out_dir"
    saved = CompareArtifact.from_dict(json.loads(written[0].read_text()))
    assert saved.label_a == "main" and saved.label_b == "candidate"
    assert saved.source_a == "a.json" and saved.source_b == "b.json"


def test_budget_zero_disables_check(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path, budget_usd=0)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack)
    art = _run(pack, art_a, art_b)  # no raise
    assert art.judge_usd > 0.0


# ------------------------------------------------------- artifact + rendering

def test_to_dict_from_dict_round_trip(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack)
    art = _run(pack, art_a, art_b, rubric_scores_untrusted=True)
    art.label_a, art.label_b = "main", "candidate"
    art.source_a, art.source_b = "a.json", "b.json"
    restored = CompareArtifact.from_dict(json.loads(json.dumps(art.to_dict())))
    assert restored == art
    assert restored.rubric_scores_untrusted is True
    assert restored.created_at_a == "2026-08-01T00:00:00+00:00"
    assert restored.created_at_b == "2026-08-02T00:00:00+00:00"


def test_from_dict_unknown_field_is_clean_value_error():
    with pytest.raises(ValueError, match="CompareArtifact"):
        CompareArtifact.from_dict({"pack_name": "x", "future_field": 1})


def test_write_compare_artifact_atomic_named(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack)
    art = _run(pack, art_a, art_b)
    out = tmp_path / "outdir"
    p = write_compare_artifact(art, out_dir=str(out))
    assert p.parent == out and p.name.endswith("-compare.json")
    assert "cmp" in p.name  # slugified pack name
    assert CompareArtifact.from_dict(json.loads(p.read_text())) == art
    assert not list(out.glob("*.tmp"))  # no torn temp files left behind


def test_render_report_advisory_no_combined_winner(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack)
    art = _run(pack, art_a, art_b)
    art.label_a, art.label_b = "main", "candidate"
    md = render_compare_report(art)
    assert md.startswith("# Evalyn compare — cmp: main vs candidate")
    assert "| category | main wins | candidate wins | ties | unsure | flip rate |" in md
    assert "| chat | 4 | 0 | 0 | 0 |" in md
    assert "latency mean main/candidate" in md
    assert "no combined winner is computed" in md
    assert "UNTRUSTED" not in md


def test_render_report_untrusted_banner(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path)
    stub = StubJudge()
    monkeypatch.setattr("evalyn.engine.compare.judge_pair", stub)
    art_a, art_b = _two_sided(pack)
    art = _run(pack, art_a, art_b, rubric_scores_untrusted=True)
    md = render_compare_report(art)
    assert "UNTRUSTED" in md and "--allow-uncalibrated" in md
