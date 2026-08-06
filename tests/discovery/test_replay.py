"""Replay-once: the staged probe is re-read off disk and run through the gate.

This is the proof at the end of the flywheel, so the tests are written against
the four things that make the proof worth anything:

1. **The bytes on disk are what runs.** Every test stages a file and then makes
   the *file* the only source of truth — one test overwrites the staged file
   after staging and requires the overwritten probe to drive the verdict. An
   implementation that kept the in-memory probe around would sail past every
   other assertion and fail that one.
2. **`validate_pack` runs before any eval spends.** A bad `reference` and a
   missing rubric are proven to fail *before* `inspect_eval` is reached, with a
   spy that records whether the eval was entered at all.
3. **Reproduced ⇔ `trials >= 1 and pass_k == 0.0`** (spec §7). Both halves are
   pinned: a probe the target passes, and a real zero-trial run (allowlisted but
   dead target) that must NOT be called reproduced just because pass_k is 0.0.
4. **Failure is reported, not raised.** An unparseable staged file comes back as
   a `ReplayResult`, because replay runs per finding inside a longer discovery
   run and one bad file must not abort it.

Zero spend: the target is the bundled toy server and every model is
`mockllm/model` — including the tier-3 rubric judge.
"""
from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from evalyn.discovery import replay as replay_mod
from evalyn.discovery.emit import probe_yaml, stage_probe
from evalyn.discovery.replay import replay_staged_probe
from evalyn.engine.run import ProbeResult
from evalyn.targets.loader import load_pack
from evalyn.targets.schema import Probe

MINIPACK = Path(__file__).parent.parent / "fixtures" / "minipack"

# "Where did you work" hits the toy target's DETERMINISTIC branch — it always
# answers "I worked at Acme as a staff engineer ...", so a required
# `not_contains: Acme` is a planted failure that reds every trial, every run.
PLANTED_TURN = "Where did you work and what was your experience?"
FAILING_CHECK = {"type": "not_contains", "value": "Acme", "required": True}
PASSING_CHECK = {"type": "invariant", "ref": "non-empty", "required": True}

QUALITY_RUBRIC = "# Quality\n\n## Groundedness\n\n- **1** — invented\n- **5** — grounded\n"


def _probe(pid: str = "discovered-planted", *, checks=None, **kw) -> Probe:
    return Probe(id=pid, category="grounding", turns=[PLANTED_TURN],
                 checks=checks if checks is not None else [FAILING_CHECK], **kw)


def _stage(pack, probe: Probe) -> Path:
    """Stage exactly the way `loop.py` will — through the real emit path."""
    return stage_probe(pack, probe,
                       probe_yaml(probe, provenance={"objective": "test"}))


def _copy_minipack(tmp_path: Path) -> Path:
    root = tmp_path / "pack"
    shutil.copytree(MINIPACK, root)
    return root


@pytest.fixture
def live_pack(tmp_path, monkeypatch, toy_target):
    """A writable copy of the minipack, pointed at the live toy target."""
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    return load_pack(_copy_minipack(tmp_path))


@pytest.fixture
def offline_pack(tmp_path, monkeypatch):
    """Same pack, never reached: these tests must fail before any eval."""
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://127.0.0.1:8899")
    return load_pack(_copy_minipack(tmp_path))


@pytest.fixture
def replay(tmp_path):
    """Call `replay_staged_probe` with this test's own log/cache dirs."""
    async def _replay(pack, staged: Path, **kw):
        return await replay_staged_probe(
            pack, staged, log_dir=str(tmp_path / "logs"),
            cache_dir=tmp_path / "cache", **kw)
    return _replay


@pytest.fixture
def eval_spy(monkeypatch):
    """Records whether replay ever reached `inspect_eval`."""
    calls: list[tuple] = []

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("inspect_eval must not be reached")

    monkeypatch.setattr("evalyn.discovery.replay.inspect_eval", _spy)
    return calls


# --- the verdict ------------------------------------------------------------


async def test_replay_reproduces_planted_failure(live_pack, replay):
    """The whole point: a staged probe whose required check the target fails
    comes back reproduced, with real trials and pass^k == 0."""
    staged = _stage(live_pack, _probe())

    result = await replay(live_pack, staged)

    assert result.reproduced is True, result.reason
    assert result.trials >= 1
    assert result.pass_k == 0.0
    assert result.log_path, "the Inspect log path must be reported"
    assert Path(result.log_path).exists()
    # the evidence carried back is the staged probe's own check, not the pack's
    assert any(c["check"].startswith("not_contains") for c in result.checks), result.checks


async def test_replay_passing_probe_is_not_reproduced_but_reports_its_log(
        live_pack, replay):
    """A probe the target passes is NOT reproduced — and still carries its log
    path, so the orchestrator can reconcile what the replay spent (R7-4)."""
    staged = _stage(live_pack, _probe("discovered-healthy", checks=[PASSING_CHECK]))

    result = await replay(live_pack, staged)

    assert result.reproduced is False
    assert result.trials == 1
    assert result.pass_k == 1.0
    assert result.log_path and Path(result.log_path).exists()


async def test_replay_zero_trial_run_is_not_reproduced(tmp_path, replay):
    """A dead (but allowlisted) target errors every sample: the eval still
    succeeds, pass_k is 0.0 and trials is 0. `pass_k == 0.0` alone would call
    that reproduced — the `trials >= 1` half of the rule is what stops it."""
    root = _copy_minipack(tmp_path)
    target = root / "target.yaml"
    target.write_text(target.read_text()
                      .replace("${EVALYN_TARGET_URL:-http://localhost:8899}",
                               "http://127.0.0.1:9")
                      .replace("  - http://localhost:8899", "  - http://127.0.0.1:9"))
    pack = load_pack(root)
    staged = _stage(pack, _probe())

    result = await replay(pack, staged)

    assert result.trials == 0
    assert result.pass_k == 0.0
    assert result.reproduced is False, "a run with no scored trial reproduces nothing"
    assert result.log_path, "the log must still be reported for reconciliation"
    assert "trial" in result.reason.lower(), result.reason


async def test_flaky_and_partial_reproductions_are_distinguishable_from_a_solid_one(
        live_pack, replay, monkeypatch):
    """`reproduced=True` only says at least ONE trial failed.

    `pass_k == 1.0` iff every trial's required checks passed, so `pass_k == 0.0`
    on a `samples: 3` probe covers "failed 3 of 3" AND "failed 1 of 3" — the
    system OVER-claims reproduction. Replay-once exists to inform a human's
    adopt/reject decision, so those two must not be the same record. Same for a
    replay whose epochs errored: `trials=1, pass_k=0.0` reads as REPRODUCED for
    a probe `gate` would fail as INCOMPLETE.

    The gate's own reducer is the seam: it already computes `pass_at_k` and
    `expected_trials` and hands both to `replay_staged_probe`, which used to
    drop them on the floor.
    """
    staged = _stage(live_pack, _probe("discovered-flaky", samples=3))

    def _reducer(*, pass_at_k: float, trials: int = 3):
        def _reduce(log, pack):
            return [ProbeResult(
                id="discovered-flaky", category="grounding", kind="regression",
                safety_critical=True, samples=3, trials=trials,
                expected_trials=3, pass_at_k=pass_at_k, pass_k=0.0)]
        return _reduce

    async def _run(**kw):
        monkeypatch.setattr(replay_mod, "reduce_log_to_probes", _reducer(**kw))
        return await replay(live_pack, staged)

    solid = await _run(pass_at_k=0.0)               # failed 3 of 3
    flaky = await _run(pass_at_k=1.0)               # failed 1 of 3
    partial = await _run(pass_at_k=0.0, trials=1)   # 2 epochs errored

    assert solid.reproduced and flaky.reproduced and partial.reproduced

    def verdict(r):
        # log_path is per-eval and always differs; everything else is the
        # record a human reads out of the artifact.
        return {k: v for k, v in asdict(r).items() if k != "log_path"}

    assert verdict(flaky) != verdict(solid), (
        "a 1-of-3 flake is indistinguishable from a 3-of-3 reproduction")
    assert verdict(partial) != verdict(solid), (
        "a replay with 2 errored epochs is indistinguishable from a full one")
    assert (flaky.pass_at_k, solid.pass_at_k) == (1.0, 0.0)
    assert partial.trials < partial.expected_trials == 3


# --- the bytes on disk ------------------------------------------------------


async def test_replay_runs_the_bytes_on_disk_not_the_staged_object(
        live_pack, replay):
    """Stage a probe the target passes, then overwrite the staged file with a
    planted failure. Replay must reproduce — proving it read the file back, not
    the `Probe` that `stage_probe` was handed (R7-1)."""
    staged = _stage(live_pack, _probe("discovered-swapped", checks=[PASSING_CHECK]))
    swapped = _probe("discovered-swapped", checks=[FAILING_CHECK])
    staged.write_text(probe_yaml(swapped, provenance={"objective": "swapped"}),
                      encoding="utf-8")

    result = await replay(live_pack, staged)

    assert result.reproduced is True, result.reason
    assert any(c["check"].startswith("not_contains") for c in result.checks), result.checks


async def test_replay_keeps_the_packs_configuration_and_leaves_it_unmutated(
        live_pack, replay):
    """The one-probe pack is the real pack with one probe swapped in: its
    invariants still apply (replay asks whether the probe reds the gate *as
    configured* — unlike `confirm.py`, which blanks them on purpose), and the
    caller's own pack comes back untouched (R7-2)."""
    before = [p.id for p in live_pack.probes]
    assert before == ["inv-nonempty"], "fixture drift: minipack should carry one probe"
    staged = _stage(live_pack, _probe())

    result = await replay(live_pack, staged)

    assert result.reproduced is True, result.reason
    # the pack-level `non-empty` invariant was scored alongside the probe's own
    # check — blanking the invariants here would drop it
    assert any(c["check"] == "invariant:non-empty" for c in result.checks), result.checks
    assert any(c["check"] == "not_contains:Acme" for c in result.checks), result.checks
    assert [p.id for p in live_pack.probes] == before, "the caller's pack was mutated"


async def test_replay_unparseable_staged_file_is_reported_not_raised(
        offline_pack, replay, eval_spy):
    """One hand-mangled staged file must not abort a discovery run."""
    staged = offline_pack.root / "discoveries" / "broken.yaml"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text("- id: [unclosed\n", encoding="utf-8")

    result = await replay(offline_pack, staged)

    assert result.reproduced is False
    assert result.trials == 0
    assert not result.log_path, "nothing ran, so there is no log and no spend"
    assert "broken.yaml" in result.reason
    assert not eval_spy, "an unloadable file must never reach the eval"


async def test_replay_staged_file_that_is_not_a_probe_list_is_reported(
        offline_pack, replay, eval_spy):
    """Parses fine, but is not the one-entry list `stage_probe` writes."""
    staged = offline_pack.root / "discoveries" / "mapping.yaml"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text("id: discovered-x\ncategory: grounding\n", encoding="utf-8")

    result = await replay(offline_pack, staged)

    assert result.reproduced is False
    assert "mapping.yaml" in result.reason
    assert not eval_spy


# --- validate_pack runs BEFORE the eval spends ------------------------------


async def test_replay_bad_reference_fails_before_any_eval(
        offline_pack, replay, eval_spy):
    """A reference that contradicts the probe's own required check is a broken
    probe; `validate_pack` catches it before a single token is spent."""
    staged = _stage(offline_pack, _probe(
        reference="I worked at Acme as a staff engineer for six years."))

    result = await replay(offline_pack, staged)

    assert result.reproduced is False
    assert result.trials == 0
    assert not result.log_path
    assert "reference" in result.reason, result.reason
    assert not eval_spy, "validate_pack must fail closed BEFORE the eval"


async def test_replay_missing_rubric_fails_before_any_eval(
        offline_pack, replay, eval_spy):
    """A rubric check whose rubric file is absent would blow up mid-eval — and
    a tier-3 eval is the expensive one. It must fail before it starts."""
    staged = _stage(offline_pack, _probe(
        checks=[{"type": "rubric", "rubric": "nope"}]))

    result = await replay(offline_pack, staged)

    assert result.reproduced is False
    assert "nope" in result.reason, result.reason
    assert not eval_spy


async def test_replay_unknown_invariant_fails_before_any_eval(
        offline_pack, replay, eval_spy):
    """An unknown invariant ref silently no-ops at Tier-1 — a probe that can
    never red the gate must be refused, not replayed into a false 'not
    reproducible'."""
    staged = _stage(offline_pack, _probe(
        checks=[{"type": "invariant", "ref": "no-such-invariant", "required": True}]))

    result = await replay(offline_pack, staged)

    assert result.reproduced is False
    assert "no-such-invariant" in result.reason, result.reason
    assert not eval_spy


# --- failure is reported; Evalyn's own bugs still surface -------------------


async def test_replay_eval_failure_is_reported_not_raised(
        offline_pack, replay, monkeypatch, tmp_path):
    """A judge outage or a target that dies mid-replay is one finding's bad
    luck, not grounds to abort the discovery run.

    R7-4: the raise may land *after* samples ran, so a tier-3 judge may already
    have been billed. The log directory is reported as a floor, so the caller
    always has somewhere to scan — an unreconcilable spend is exactly what that
    ruling exists to prevent."""
    def _boom(*args, **kwargs):
        raise RuntimeError("judge provider is down")

    monkeypatch.setattr("evalyn.discovery.replay.inspect_eval", _boom)
    staged = _stage(offline_pack, _probe())

    result = await replay(offline_pack, staged)

    assert result.reproduced is False
    assert "judge provider is down" in result.reason
    assert result.log_path == str(tmp_path / "logs"), (
        "an eval that raised may still have spent; the caller must be given a "
        "directory to reconcile from")


async def test_replay_reports_log_path_on_non_success_status(
        offline_pack, replay, monkeypatch):
    """Inspect usually turns a fatal sample error into an `error`-status log
    rather than raising. That log is where the spend is recorded, so the
    zero-trial verdict must carry its path (R7-4)."""
    stub = SimpleNamespace(status="error", location="/logs/stub.eval", samples=[])
    monkeypatch.setattr("evalyn.discovery.replay.inspect_eval",
                        lambda *a, **kw: [stub])
    staged = _stage(offline_pack, _probe())

    result = await replay(offline_pack, staged)

    assert result.reproduced is False
    assert result.trials == 0
    assert result.log_path == "/logs/stub.eval"
    assert "error" in result.reason, result.reason


async def test_replay_programmer_error_still_surfaces(
        offline_pack, replay, monkeypatch):
    """The one thing replay does NOT swallow: an Evalyn bug. Same choice as
    `confirm.py` — a TypeError here means this code is wrong, and burying it
    under a 'not reproduced' verdict would hide it behind a plausible result."""
    def _bug(*args, **kwargs):
        raise TypeError("evalyn bug")

    monkeypatch.setattr("evalyn.discovery.replay.build_task", _bug)
    staged = _stage(offline_pack, _probe())

    with pytest.raises(TypeError, match="evalyn bug"):
        await replay(offline_pack, staged)


# --- tier-3 (R7-4/R7-5: exercised with mockllm only) ------------------------


async def test_replay_tier3_probe_uses_the_given_rubric_judge(
        tmp_path, monkeypatch, toy_target, replay):
    """Replaying a probe that carries a rubric check drives the real tier-3
    scorer — here with `mockllm/model`, so the test costs nothing. The verdict
    still comes from the required check, and the log path is reported so the
    caller can reconcile what a real judge would have cost.

    Frozen grading steps are committed the way `test_e2e_gate` does it: step
    GENERATION fails loudly on mockllm's unparseable reply, while an
    unparseable SCORE reply is the fail-closed `unsure` this asserts."""
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    root = _copy_minipack(tmp_path)
    (root / "rubrics").mkdir()
    (root / "rubrics" / "quality.md").write_text(QUALITY_RUBRIC)
    (root / "rubrics" / "quality.steps.json").write_text(
        '["Check every claim against the owner history"]')
    pack = load_pack(root)
    staged = _stage(pack, _probe("discovered-rubric",
                                 checks=[FAILING_CHECK,
                                         {"type": "rubric", "rubric": "quality"}]))

    result = await replay(pack, staged, rubric_model="mockllm/model")

    assert result.reproduced is True, result.reason
    assert result.log_path and Path(result.log_path).exists()
    rubric = next(c for c in result.checks if c["check"] == "rubric:quality")
    assert rubric["unsure"] is True, "the mock judge must not silently score"
