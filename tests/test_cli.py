from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalyn.cli import app
from evalyn.engine.baseline import save_baseline
from evalyn.engine.gate import evaluate_gate
from evalyn.engine.run import ProbeResult, RunArtifact
from tests.cli_runner import CliRunner

runner = CliRunner()

REPO = Path(__file__).resolve().parent.parent
PACK = str(REPO / "packs" / "example")


def _probe(pid: str, *, safety: bool = False, kind: str = "regression",
           pass_k: float = 1.0, mean: float = 1.0) -> ProbeResult:
    return ProbeResult(
        id=pid, category="cat", kind=kind, safety_critical=safety, samples=3,
        trials=3, pass_at_k=1.0 if mean > 0 else 0.0, pass_k=pass_k,
        mean_score=mean)


def _artifact(probes: list[ProbeResult], pack_hash: str = "a" * 64) -> RunArtifact:
    return RunArtifact(
        pack_name="example", pack_hash=pack_hash, judge_model="mockllm/model",
        created_at="2026-07-23T00:00:00+00:00", probes=probes, log_path="runs/logs")


def _fake_run_gate(art: RunArtifact):
    def fake(pack, judge_model="mockllm/model", **kwargs):
        return art
    return fake


# ---------------------------------------------------------------- validate-pack

def test_validate_pack_command_clean(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    result = runner.invoke(app, ["validate-pack", PACK])
    assert result.exit_code == 0
    assert "OK" in result.stdout or "passed" in result.stdout.lower()


def test_validate_pack_warning_still_exit_0(tmp_path, monkeypatch):
    # warnings never flip the exit code (here: capability + safety_critical)
    pack_dir = tmp_path / "warnpack"
    (pack_dir / "probes").mkdir(parents=True)
    (pack_dir / "target.yaml").write_text(
        "name: w\nsessions:\n  open: {method: POST, path: /s}\n"
        "  message: {method: POST, path: /c}\nauth: {kind: none}\n"
        "env: {base_url: http://localhost:8899}\nallowlist: [http://localhost:8899]\n")
    (pack_dir / "probes" / "p.yaml").write_text(
        "- {id: a, category: c, kind: capability, safety_critical: true, turns: [hi],"
        " checks: [{type: invariant, ref: non-empty, required: true}]}\n")
    result = runner.invoke(app, ["validate-pack", str(pack_dir)])
    assert result.exit_code == 0
    assert "warning:" in result.stdout


def test_validate_pack_example_has_no_interim_multi_turn_warning(monkeypatch):
    # Task 9 retired the interim guard: transcript scoring covers earlier turns now
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    result = runner.invoke(app, ["validate-pack", PACK])
    assert result.exit_code == 0
    assert "only the final assistant reply is scored" not in result.stdout


def test_validate_pack_exits_1_on_bad_pack(tmp_path):
    # a structurally valid pack whose probe references an unknown invariant
    pack_dir = tmp_path / "badpack"
    (pack_dir / "probes").mkdir(parents=True)
    (pack_dir / "target.yaml").write_text(
        "name: bad\n"
        "sessions:\n"
        "  open: { method: POST, path: /session }\n"
        "env: { base_url: http://localhost:8899 }\n"
        "allowlist: [http://localhost:8899]\n")
    (pack_dir / "probes" / "p.yaml").write_text(
        "- id: p1\n"
        "  category: c\n"
        "  turns: [hi]\n"
        "  checks:\n"
        "    - { type: invariant, ref: no-such-invariant, required: true }\n")
    result = runner.invoke(app, ["validate-pack", str(pack_dir)])
    assert result.exit_code == 1


def test_validate_pack_exits_1_on_unloadable_pack(tmp_path):
    result = runner.invoke(app, ["validate-pack", str(tmp_path / "nowhere")])
    assert result.exit_code == 1


# ------------------------------------------------------------------ gate: infra

def test_gate_exit_code_2_on_bad_allowlist(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://evil.example.com")
    result = runner.invoke(app, ["gate", "--target", PACK])
    assert result.exit_code == 2


def test_gate_exit_code_2_on_pack_error(tmp_path):
    result = runner.invoke(app, ["gate", "--target", str(tmp_path / "nowhere")])
    assert result.exit_code == 2


def test_gate_exit_code_2_on_run_error(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")

    def boom(pack, judge_model="mockllm/model", **kwargs):
        raise ConnectionError("target unreachable")

    monkeypatch.setattr("evalyn.engine.run.run_gate", boom)
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == 2
    assert "run error" in result.stderr  # not a usage error


def test_gate_exit_2_with_budget_message_on_budget_exceeded(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")

    def over_budget(pack, judge_model="mockllm/model", **kwargs):
        from evalyn.engine.budget import BudgetExceeded
        raise BudgetExceeded("judge spend $7.5000 exceeded max_usd_per_run $5.00 "
                             "(partial artifact written)")

    monkeypatch.setattr("evalyn.engine.run.run_gate", over_budget)
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == 2
    assert "budget" in result.stderr.lower()
    assert "max_usd_per_run" in result.stderr


def test_gate_dry_run_makes_no_calls(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")

    def must_not_run(pack, judge_model="mockllm/model", **kwargs):
        raise AssertionError("run_gate must not be called under --dry-run")

    monkeypatch.setattr("evalyn.engine.run.run_gate", must_not_run)
    result = runner.invoke(app, ["gate", "--target", PACK, "--dry-run"])
    assert result.exit_code == 0
    assert "dry-run" in result.stdout


# -------------------------------------------- gate: validate-pack fail-closed


def test_gate_exit_2_on_dangling_invariant_ref(minimal_pack):
    # A required invariant check with a dangling ref silently no-ops at scoring
    # time — the gate must fail closed (exit 2) before evaluating, incl. dry-run.
    pack_dir = str(minimal_pack(
        "- id: p1\n  category: c\n  turns: [hi]\n  checks:\n"
        "    - { type: invariant, ref: no-such-invariant, required: true }\n"))
    result = runner.invoke(app, ["gate", "--target", pack_dir, "--dry-run"])
    assert result.exit_code == 2
    assert "no-such-invariant" in result.stderr
    assert "setup error" in result.stderr


def test_gate_exit_2_on_contains_check_missing_value(minimal_pack):
    pack_dir = str(minimal_pack(
        "- id: p1\n  category: c\n  turns: [hi]\n  checks:\n"
        "    - { type: contains, required: true }\n"))
    result = runner.invoke(app, ["gate", "--target", pack_dir, "--dry-run"])
    assert result.exit_code == 2
    assert "value" in result.stderr
    assert "setup error" in result.stderr


#: A pack whose one probe is attack-only, which is the cheapest thing that makes
#: `validate_pack` warn. Shared by the three commands the cockpit launches.
_WARNING_PROBE = (
    "- id: atk\n  category: injection\n  safety_critical: true\n  turns: [hi]\n"
    "  checks:\n    - { type: invariant, ref: non-empty, required: true }\n")


def test_gate_validation_warnings_do_not_abort_and_reach_the_cockpit(minimal_pack):
    """Warnings print, never abort — and print where an operator can read them.

    `spawn_child` gives the child `stdout=subprocess.DEVNULL`, so on the cockpit
    path stdout is `/dev/null` and `stderr.log` (`GET /api/runs/{id}/stderr`) is
    the operator's only channel. A warning on stdout is a warning nobody
    receives; measured on the demo pack, the single warning `validate-pack`
    emits is the one saying how many sessions the run will cost.
    """
    pack_dir = str(minimal_pack(_WARNING_PROBE))
    result = runner.invoke(app, ["gate", "--target", pack_dir, "--dry-run"])
    assert result.exit_code == 0
    assert "warning:" in result.stderr
    assert "warning:" not in result.stdout, "stdout is /dev/null on the cockpit path"


def test_compare_validation_warnings_reach_the_cockpit(minimal_pack, tmp_path):
    """The sibling of the gate case, and left behind by the fix wave that moved
    the *baseline* warnings. Half a defect class fixed is a trap for the next
    reader, who cannot tell the remaining half from a deliberate exclusion."""
    pack_dir = str(minimal_pack(_WARNING_PROBE))
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", str(tmp_path / "no-a.json"),
                                 "--b", str(tmp_path / "no-b.json")])
    assert "warning:" in result.stderr
    assert "warning:" not in result.stdout, "stdout is /dev/null on the cockpit path"


def test_discover_validation_warnings_reach_the_cockpit(minimal_pack, monkeypatch):
    """Third of three. `--dry-run` so nothing is planned and nothing is spent."""
    async def must_not_run(pack, cfg, **kw):
        raise AssertionError("run_discovery must not be called under --dry-run")

    monkeypatch.setattr("evalyn.discovery.run.run_discovery", must_not_run)
    pack_dir = str(minimal_pack(_WARNING_PROBE))
    result = runner.invoke(app, ["discover", "--target", pack_dir, "--dry-run"])
    assert "warning:" in result.stderr
    assert "warning:" not in result.stdout, "stdout is /dev/null on the cockpit path"


# ------------------------------------------------- gate: mock-judge warning

def test_gate_warns_when_mock_judge_meets_classifier_checks(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    result = runner.invoke(app, ["gate", "--target", PACK, "--dry-run"])
    assert result.exit_code == 0  # verdict-neutral: warning must not change the exit code
    assert "warning:" in result.stderr
    assert "mockllm" in result.stderr


def test_gate_no_mock_judge_warning_with_real_judge(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    result = runner.invoke(app, ["gate", "--target", PACK, "--dry-run",
                                 "--judge-model", "openai/gpt-4o-mini"])
    assert result.exit_code == 0
    # Named for the mock-judge warning, so it asserts on that warning rather
    # than on the *stream being silent*. A bare `"warning:" not in stderr` was
    # only ever equivalent to this by accident: `validate_pack`'s warnings used
    # to go to stdout, and once they joined stderr (R4-76, where they belong —
    # the cockpit's child has no stdout) the broad form started failing on a
    # warning this test was never about. Mirrors its `in` twin above.
    assert "judge model is mockllm" not in result.stderr
    assert "mockllm" not in result.stderr


def test_gate_no_mock_judge_warning_without_classifier_checks(monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    minipack = str(REPO / "tests" / "fixtures" / "minipack")
    result = runner.invoke(app, ["gate", "--target", minipack, "--dry-run"])
    assert result.exit_code == 0
    assert "warning:" not in result.stderr


# --------------------------------------------------- gate: exit-code mapping
# Amendment A2: derive the expected exit code from the gate policy applied to
# the artifact the CLI actually evaluated — never accept a set of codes.

def test_gate_exit_0_when_policy_passes(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("ok-probe", safety=True, pass_k=1.0)])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    expected = evaluate_gate(art, None)
    assert expected.exit_code == 0  # sanity: this synthetic artifact must pass
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == expected.exit_code
    assert "PASS" in result.stdout


def test_gate_exit_1_when_safety_probe_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("leaky", safety=True, pass_k=0.0, mean=0.5)])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    expected = evaluate_gate(art, None)
    assert expected.exit_code == 1  # sanity: this synthetic artifact must fail
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == expected.exit_code
    assert "FAIL" in result.stdout


def test_gate_live_exit_code_matches_gate_policy(toy_target, monkeypatch, tmp_path,
                                                 live_pack_dir):
    # Amendment A2 strengthening of the brief's flaky-safety test: instead of
    # accepting exit_code in (0, 1), read the artifact this very run produced,
    # apply the gate policy to it, and require the CLI's exit code to be EQUAL.
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    live_pack = str(live_pack_dir(PACK))  # allowlist must name the live port
    monkeypatch.chdir(tmp_path)  # run_gate writes runs/ relative to cwd
    # the default mockllm judge is priced at zero (free local stub), so real
    # post-hoc metering runs silently — no unknown-model warning to capture.
    result = runner.invoke(app, ["gate", "--target", live_pack,
                                 "--baseline", str(tmp_path / "none.json")])
    artifacts = sorted((tmp_path / "runs").glob("*-example.json"))
    assert artifacts, "gate run wrote no artifact"
    art = RunArtifact.from_dict(json.loads(artifacts[-1].read_text()))
    expected = evaluate_gate(art, None)
    assert result.exit_code == expected.exit_code
    assert "gate" in result.stdout.lower()
    assert ("FAIL" if expected.exit_code else "PASS") in result.stdout


# ------------------------------------------------------------- gate: baseline

def test_gate_update_baseline_writes_and_exits_0(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("ok-probe")])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    baseline_path = tmp_path / "baseline.json"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path),
                                 "--update-baseline"])
    assert result.exit_code == 0
    saved = RunArtifact.from_dict(json.loads(baseline_path.read_text()))
    assert saved == art


# Carry-note 1: warn (not fail) when baseline pack hash differs from current.
# On **stderr**, and that is load-bearing rather than cosmetic: a cockpit-launched
# gate has its stdout sent to `/dev/null` (`ui/launcher.py`, `spawn_child`), so a
# staleness warning printed to stdout is not merely unread from the browser, it is
# unreachable. `stderr.log`, served at `GET /api/runs/{id}/stderr`, is the only
# channel the operator can see mid-demo.
def test_gate_warns_on_pack_hash_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    baseline_art = _artifact([_probe("ok-probe")], pack_hash="b" * 64)
    baseline_path = tmp_path / "baseline.json"
    save_baseline(baseline_art, str(baseline_path))
    current = _artifact([_probe("ok-probe")], pack_hash="a" * 64)
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(current))
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path)])
    expected = evaluate_gate(current, baseline_art)
    assert result.exit_code == expected.exit_code  # a warning, never a failure
    assert "warning:" in result.stderr
    assert "pack hash" in result.stderr
    assert "pack hash" not in result.stdout, "stdout is /dev/null on the cockpit path"


# Carry-note 2: warn about probes present in baseline but absent from current
# (they are invisible to the gate diff).
def test_gate_warns_on_probes_missing_from_current(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    baseline_art = _artifact([_probe("kept-probe"), _probe("dropped-probe")])
    baseline_path = tmp_path / "baseline.json"
    save_baseline(baseline_art, str(baseline_path))
    current = _artifact([_probe("kept-probe")])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(current))
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path)])
    expected = evaluate_gate(current, baseline_art)
    assert result.exit_code == expected.exit_code  # a warning, never a failure
    assert "warning:" in result.stderr
    warning_line = next(ln for ln in result.stderr.splitlines() if "dropped-probe" in ln)
    assert warning_line.startswith("warning:")
    assert "kept-probe" not in warning_line
    assert "dropped-probe" not in result.stdout, \
        "stdout is /dev/null on the cockpit path"


# ------------------------------------------------- calibrate + fail-closed gate

TONE_RUBRIC = "# Tone\nCalm and professional.\n"


def _write_rubric_pack(tmp_path: Path, *, anchors: bool = True) -> str:
    """Pack with one required rubric check (and optionally one labeled anchor)."""
    pack_dir = tmp_path / "rpack"
    (pack_dir / "probes").mkdir(parents=True)
    (pack_dir / "rubrics").mkdir()
    (pack_dir / "target.yaml").write_text(
        "name: rp\n"
        "sessions:\n"
        "  open: { method: POST, path: /session }\n"
        "  message: { method: POST, path: /chat }\n"
        "env: { base_url: http://localhost:8899 }\n"
        "allowlist: [http://localhost:8899]\n")
    (pack_dir / "rubrics" / "tone.md").write_text(TONE_RUBRIC)
    (pack_dir / "probes" / "p.yaml").write_text(
        "- id: p1\n  category: c\n  turns: [hi]\n  checks:\n"
        "    - { type: rubric, rubric: tone, required: true }\n")
    if anchors:
        (pack_dir / "anchors").mkdir()
        (pack_dir / "anchors" / "a1.yaml").write_text(
            "rubric: tone\ntranscript: |\n  User: hi\n  Assistant: hello\n"
            "scores:\n  Tone: 4\n")
    return str(pack_dir)


def _stub_calibration(monkeypatch, overall: float, unmatched: dict | None = None,
                      per_criterion: dict | None = None,
                      per_criterion_counts: dict | None = None,
                      per_anchor: dict | None = None):
    from evalyn.engine.calibrate import CalibrationResult

    async def fake(pack, judge_model, cache_dir, k=3):
        return CalibrationResult(overall=overall,
                                 per_criterion=per_criterion or {"tone:Tone": overall},
                                 anchors=1, unmatched=unmatched or {},
                                 per_criterion_counts=per_criterion_counts or {},
                                 per_anchor=per_anchor or {})

    monkeypatch.setattr("evalyn.engine.calibrate.run_calibration", fake)


def test_calibrate_exit_0_and_record_written_when_agreement_passes(monkeypatch, tmp_path):
    pack_dir = _write_rubric_pack(tmp_path)
    _stub_calibration(monkeypatch, 1.0)
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert result.exit_code == 0
    assert "tone:Tone: 100%" in result.stdout
    assert "overall agreement: 100%" in result.stdout
    rec = json.loads((Path(pack_dir) / "calibration.json").read_text())
    assert rec["agreement"] == 1.0
    assert "tone" in rec["rubric_hashes"]


def test_calibrate_exit_0_at_exact_threshold(monkeypatch, tmp_path):
    # boundary lock: agreement == 0.85 exactly is a PASS (>= threshold)
    pack_dir = _write_rubric_pack(tmp_path)
    _stub_calibration(monkeypatch, 0.85)
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert result.exit_code == 0


def test_calibrate_warns_about_unmatched_criterion_labels(monkeypatch, tmp_path):
    # a human label matching no rubric criterion must be surfaced, never
    # silently excluded from the agreement denominator
    pack_dir = _write_rubric_pack(tmp_path)
    _stub_calibration(monkeypatch, 1.0, unmatched={"a1": ["Warmth", "ghost"]})
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert result.exit_code == 0
    assert "warning:" in result.stderr and "a1" in result.stderr
    assert "Warmth" in result.stderr and "ghost" in result.stderr


def test_calibrate_prints_per_anchor_agreement_lines(monkeypatch, tmp_path):
    # 2026-07-30 failure: the CLI printed only aggregates, so a failing run
    # could not say WHICH anchors disagreed or why one was unsure — one line
    # per anchor with judge-vs-human per criterion (always printed)
    pack_dir = _write_rubric_pack(tmp_path)
    _stub_calibration(monkeypatch, 0.5, per_anchor={
        "a1": {"rubric": "tone", "unsure_reason": None,
               "criteria": {"Tone": {"judge": 2, "human": 4, "within": False}}},
        "a2": {"rubric": "tone", "unsure_reason": "2/3 samples unparseable",
               "criteria": {"Tone": {"judge": None, "human": 4, "within": False}}},
    })
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert "per-anchor agreement:" in result.stdout
    a1_line = next(ln for ln in result.stdout.splitlines() if "a1" in ln)
    assert "tone" in a1_line and "judge=2" in a1_line
    assert "human=4" in a1_line and "MISS" in a1_line
    a2_line = next(ln for ln in result.stdout.splitlines() if "a2" in ln)
    assert "UNSURE" in a2_line and "2/3 samples unparseable" in a2_line


def test_calibrate_per_anchor_line_shows_clean_sibling_beside_torn_criterion(
        monkeypatch, tmp_path):
    # per-criterion unsure accounting (2026-07-31): a torn criterion renders
    # as an unsure-miss with its spread reason while the clean sibling on the
    # SAME anchor line shows its judge median and ok/MISS normally
    pack_dir = _write_rubric_pack(tmp_path)
    _stub_calibration(monkeypatch, 0.5, per_anchor={
        "a1": {"rubric": "tone",
               "unsure_reason": "judge disagreement (spread >= 2) on ['Firm']",
               "criteria": {
                   "Tone": {"judge": 4, "human": 4, "within": True},
                   "Firm": {"judge": None, "human": 4, "within": False,
                            "unsure_reason": "spread 3 >= 2"}}},
    })
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    a1_line = next(ln for ln in result.stdout.splitlines() if "a1" in ln)
    assert "Tone judge=4 human=4 ok" in a1_line
    assert "Firm judge=- (spread 3 >= 2) human=4 MISS" in a1_line


def test_calibrate_exit_1_below_threshold_still_writes_record(monkeypatch, tmp_path):
    # record-on-failure is safe ONLY because is_stale rejects sub-threshold
    # agreement (pinned in tests/engine/test_calibrate.py)
    pack_dir = _write_rubric_pack(tmp_path)
    _stub_calibration(monkeypatch, 0.5)
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert result.exit_code == 1
    assert (Path(pack_dir) / "calibration.json").exists()


def test_calibrate_fails_when_a_rubric_is_weak_despite_strong_overall(monkeypatch, tmp_path):
    # PR #4 fix #4 follow-up: calibrate's verdict must apply the SAME per-rubric
    # rule as is_stale — otherwise calibrate prints PASS while the gate refuses
    # the very record it just wrote. tone pools to (1.0 + 0.6)/2 = 0.8 < 0.85.
    pack_dir = _write_rubric_pack(tmp_path)
    _stub_calibration(monkeypatch, 0.9,
                      per_criterion={"tone:Calm": 1.0, "tone:Firm": 0.6})
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert result.exit_code == 1
    assert "PASS" not in result.stdout
    assert "'tone'" in result.stderr and "80%" in result.stderr  # weak rubric named
    assert "overall agreement: 90%" in result.stdout             # overall still shown
    # record-written-on-failure is pinned by-design behavior (is_stale rejects it)
    assert (Path(pack_dir) / "calibration.json").exists()


def test_calibrate_verdict_uses_pooled_counts_when_available(monkeypatch, tmp_path):
    # round-2 N8: with divergent pair counts the mean-of-fractions rubric value
    # (0.9) clears the bar but the pooled truth (9/11 = 82%) does not — the
    # verdict must FAIL and the record must carry the pooled value
    pack_dir = _write_rubric_pack(tmp_path)
    _stub_calibration(monkeypatch, 0.9,
                      per_criterion={"tone:Calm": 1.0, "tone:Firm": 0.8},
                      per_criterion_counts={"tone:Calm": (1, 1),
                                            "tone:Firm": (8, 10)})
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert result.exit_code == 1
    assert "'tone'" in result.stderr and "82%" in result.stderr
    rec = json.loads((Path(pack_dir) / "calibration.json").read_text())
    assert rec["per_rubric_agreement"] == {"tone": 9 / 11}


def test_calibrate_exit_2_when_pack_has_no_anchors(monkeypatch, tmp_path):
    pack_dir = _write_rubric_pack(tmp_path, anchors=False)

    async def must_not_run(*a, **k):
        raise AssertionError("run_calibration must not be called without anchors")

    monkeypatch.setattr("evalyn.engine.calibrate.run_calibration", must_not_run)
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert result.exit_code == 2
    assert "setup error" in result.stderr and "anchor" in result.stderr


def test_calibrate_exit_2_on_unloadable_pack(tmp_path):
    result = runner.invoke(app, ["calibrate", "--target", str(tmp_path / "nowhere")])
    assert result.exit_code == 2


def test_gate_refuses_rubric_checks_without_calibration(monkeypatch, tmp_path):
    # fail-closed: missing/stale calibration record is a SETUP error (exit 2)
    pack_dir = _write_rubric_pack(tmp_path)

    def must_not_run(pack, judge_model="mockllm/model", **kwargs):
        raise AssertionError("run_gate must not run with uncalibrated rubric checks")

    monkeypatch.setattr("evalyn.engine.run.run_gate", must_not_run)
    result = runner.invoke(app, ["gate", "--target", pack_dir,
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == 2
    assert "setup error" in result.stderr
    assert "evalyn calibrate" in result.stderr
    assert "--allow-uncalibrated" in result.stderr


def test_gate_allow_uncalibrated_warns_loudly_and_marks_artifact(monkeypatch, tmp_path):
    pack_dir = _write_rubric_pack(tmp_path)
    art = _artifact([_probe("p1")])
    seen = {}

    def fake_run(pack, judge_model="mockllm/model", **kwargs):
        seen.update(kwargs)
        return art

    monkeypatch.setattr("evalyn.engine.run.run_gate", fake_run)
    result = runner.invoke(app, ["gate", "--target", pack_dir,
                                 "--allow-uncalibrated",
                                 "--rubric-judge-model", "openai/gpt-4o",
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == evaluate_gate(art, None).exit_code
    assert "UNCALIBRATED" in result.stderr  # loud, on stderr
    assert seen["rubric_scores_untrusted"] is True
    assert seen["rubric_judge_model"] == "openai/gpt-4o"


def test_gate_runs_rubric_checks_with_fresh_calibration_record(monkeypatch, tmp_path):
    from evalyn.engine.calibrate import write_record
    from evalyn.targets.loader import load_pack

    pack_dir = _write_rubric_pack(tmp_path)
    pack = load_pack(pack_dir)
    write_record(pack, 0.9, {"tone:Tone": 0.9}, pack.spec.judge.rubric_model)
    art = _artifact([_probe("p1")])
    seen = {}

    def fake_run(pack, judge_model="mockllm/model", **kwargs):
        seen.update(kwargs)
        return art

    monkeypatch.setattr("evalyn.engine.run.run_gate", fake_run)
    result = runner.invoke(app, ["gate", "--target", pack_dir,
                                 "--baseline", str(tmp_path / "none.json")])
    assert result.exit_code == evaluate_gate(art, None).exit_code
    assert "UNCALIBRATED" not in result.stderr
    assert seen["rubric_scores_untrusted"] is False


def test_gate_dry_run_skips_calibration_check(tmp_path):
    pack_dir = _write_rubric_pack(tmp_path)
    result = runner.invoke(app, ["gate", "--target", pack_dir, "--dry-run"])
    assert result.exit_code == 0


# ------------------------------- Task 12: exit-2 mappings, --debug, --out-dir

def test_gate_exit_2_on_old_schema_baseline(monkeypatch, tmp_path):
    # a pre-Plan-#2a baseline must be a clean exit-2 message, not a traceback
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    monkeypatch.setattr("evalyn.engine.run.run_gate",
                        _fake_run_gate(_artifact([_probe("ok-probe")])))
    old_baseline = tmp_path / "old.json"
    old_baseline.write_text(json.dumps({
        "pack_name": "example", "pack_hash": "a" * 64, "judge_model": "m",
        "created_at": "2026-01-01T00:00:00+00:00", "log_path": "runs/logs",
        "probes": [{"id": "p", "passed": True}],  # Plan #1 shape
    }))
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(old_baseline)])
    assert result.exit_code == 2
    assert "predates" in result.stderr and "baseline" in result.stderr


def test_gate_exit_2_on_baseline_with_unknown_top_level_field(monkeypatch, tmp_path):
    # PR #4 fix #9: an unknown top-level baseline key must be a clean setup
    # error (exit 2), never a TypeError traceback that reads as exit-1 gate FAIL
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    monkeypatch.setattr("evalyn.engine.run.run_gate",
                        _fake_run_gate(_artifact([_probe("ok-probe")])))
    future = _artifact([_probe("ok-probe")]).to_dict()
    future["future_field"] = "from-a-newer-evalyn"
    baseline = tmp_path / "future.json"
    baseline.write_text(json.dumps(future))
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline)])
    assert result.exit_code == 2
    assert result.exception is None or not isinstance(result.exception, TypeError)
    assert "baseline error" in result.stderr


def test_gate_debug_reraises_run_error(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")

    def boom(pack, judge_model="mockllm/model", **kwargs):
        raise ConnectionError("target unreachable")

    monkeypatch.setattr("evalyn.engine.run.run_gate", boom)
    result = runner.invoke(app, ["gate", "--target", PACK, "--debug",
                                 "--baseline", str(tmp_path / "none.json")])
    assert isinstance(result.exception, ConnectionError)


def test_calibrate_exit_2_on_malformed_anchor(monkeypatch, tmp_path):
    # an anchor missing `rubric`/`transcript` keys is a clean setup error,
    # never a raw KeyError traceback
    pack_dir = _write_rubric_pack(tmp_path)
    (Path(pack_dir) / "anchors" / "a1.yaml").write_text("scores:\n  Tone: 4\n")
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert result.exit_code == 2
    assert "setup error" in result.stderr
    assert "a1.yaml" in result.stderr and "rubric" in result.stderr


def test_calibrate_exit_2_on_missing_rubric_file(monkeypatch, tmp_path):
    # anchor references a rubric whose file is gone -> clean exit 2, no traceback
    pack_dir = _write_rubric_pack(tmp_path)
    (Path(pack_dir) / "rubrics" / "tone.md").unlink()
    result = runner.invoke(app, ["calibrate", "--target", pack_dir])
    assert result.exit_code == 2
    assert "setup error" in result.stderr and "tone" in result.stderr


def test_calibrate_debug_reraises_missing_rubric_file(monkeypatch, tmp_path):
    pack_dir = _write_rubric_pack(tmp_path)
    (Path(pack_dir) / "rubrics" / "tone.md").unlink()
    result = runner.invoke(app, ["calibrate", "--target", pack_dir, "--debug"])
    assert isinstance(result.exception, FileNotFoundError)


def test_calibrate_exit_2_on_unparseable_steps_generation(tmp_path):
    # fix round 1 (2026-07-31): steps generation now fails loudly (RuntimeError)
    # — calibrate must surface it as a clean exit-2 message, never a raw
    # traceback. mockllm's default reply is unparseable steps JSON, so the
    # real pre-warm path raises with zero monkeypatching and zero spend.
    pack_dir = _write_rubric_pack(tmp_path)
    result = runner.invoke(app, ["calibrate", "--target", pack_dir,
                                 "--rubric-judge-model", "mockllm/model"])
    assert result.exit_code == 2
    assert "setup error" in result.stderr and "grading steps" in result.stderr
    assert "Traceback" not in result.stderr


def test_calibrate_exit_2_on_malformed_committed_steps_file(tmp_path):
    # a malformed committed rubrics/<rid>.steps.json raises ValueError in
    # run_calibration (calibrate runs no validate_pack) — same clean contract
    pack_dir = _write_rubric_pack(tmp_path)
    (Path(pack_dir) / "rubrics" / "tone.steps.json").write_text("not json at all")
    result = runner.invoke(app, ["calibrate", "--target", pack_dir,
                                 "--rubric-judge-model", "mockllm/model"])
    assert result.exit_code == 2
    assert "setup error" in result.stderr and "tone.steps.json" in result.stderr
    assert "Traceback" not in result.stderr


def test_calibrate_debug_reraises_unparseable_steps_generation(tmp_path):
    pack_dir = _write_rubric_pack(tmp_path)
    result = runner.invoke(app, ["calibrate", "--target", pack_dir, "--debug",
                                 "--rubric-judge-model", "mockllm/model"])
    assert isinstance(result.exception, RuntimeError)


def test_gate_update_baseline_echoes_pass_verdict(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("ok-probe", safety=True, pass_k=1.0)])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "b.json"),
                                 "--update-baseline"])
    assert result.exit_code == 0
    assert "PASS" in result.stdout  # the verdict being blessed is echoed


def test_gate_update_baseline_echoes_fail_verdict_but_still_saves(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("leaky", safety=True, pass_k=0.0, mean=0.5)])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    baseline_path = tmp_path / "b.json"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path),
                                 "--update-baseline"])
    assert result.exit_code == 0  # blessing is explicit; verdict never blocks it
    assert "FAIL" in result.stdout
    assert baseline_path.exists()


# ---------------- round-2 N4: --update-baseline must not bless bad artifacts

def test_update_baseline_refuses_untrusted_rubric_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("ok-probe")])
    art.rubric_scores_untrusted = True
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    baseline_path = tmp_path / "b.json"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path),
                                 "--update-baseline"])
    assert result.exit_code == 2
    assert "UNTRUSTED" in result.stderr or "untrusted" in result.stderr.lower()
    assert "--force-baseline" in result.stderr
    assert not baseline_path.exists()


def test_update_baseline_refuses_artifact_with_zero_trial_probe(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    dead = _probe("dead-probe")
    dead.trials = 0
    art = _artifact([_probe("ok-probe"), dead])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    baseline_path = tmp_path / "b.json"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path),
                                 "--update-baseline"])
    assert result.exit_code == 2
    assert "dead-probe" in result.stderr
    assert not baseline_path.exists()


def test_update_baseline_force_blesses_anyway_with_loud_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("ok-probe")])
    art.rubric_scores_untrusted = True
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    baseline_path = tmp_path / "b.json"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path),
                                 "--update-baseline", "--force-baseline"])
    assert result.exit_code == 0
    assert "warning" in result.stderr.lower()
    assert baseline_path.exists()
    saved = RunArtifact.from_dict(json.loads(baseline_path.read_text()))
    assert saved == art


def test_update_baseline_refuses_artifact_with_incomplete_probe(monkeypatch, tmp_path):
    # #2b Task 10: 0 < trials < expected_trials is INCOMPLETE — same refusal
    # class as zero-trial probes (natural tightening of the N4 guard)
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    partial = _probe("partial-probe")
    partial.trials = 2
    partial.expected_trials = 3
    art = _artifact([_probe("ok-probe"), partial])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    baseline_path = tmp_path / "b.json"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path),
                                 "--update-baseline"])
    assert result.exit_code == 2
    assert "INCOMPLETE" in result.stderr
    assert "partial-probe" in result.stderr
    assert not baseline_path.exists()


def test_update_baseline_force_blesses_incomplete_anyway_with_loud_warning(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    partial = _probe("partial-probe")
    partial.trials = 2
    partial.expected_trials = 3
    art = _artifact([partial])
    monkeypatch.setattr("evalyn.engine.run.run_gate", _fake_run_gate(art))
    baseline_path = tmp_path / "b.json"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path),
                                 "--update-baseline", "--force-baseline"])
    assert result.exit_code == 0
    assert "warning" in result.stderr.lower()
    assert "INCOMPLETE" in result.stderr
    assert baseline_path.exists()


def test_gate_report_banners_untrusted_baseline(monkeypatch, tmp_path):
    # N4c end-to-end: gating against a --force-baseline'd untrusted baseline
    # must banner the BASELINE side in the report
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    baseline_art = _artifact([_probe("ok-probe")])
    baseline_art.rubric_scores_untrusted = True
    baseline_path = tmp_path / "b.json"
    save_baseline(baseline_art, str(baseline_path))
    monkeypatch.setattr("evalyn.engine.run.run_gate",
                        _fake_run_gate(_artifact([_probe("ok-probe")])))
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline_path)])
    assert "BASELINE" in result.stdout and "UNTRUSTED" in result.stdout


# ------- round-2 N7: baseline artifact missing the `probes` key entirely

def test_gate_exit_2_on_baseline_without_probes_key(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    monkeypatch.setattr("evalyn.engine.run.run_gate",
                        _fake_run_gate(_artifact([_probe("ok-probe")])))
    d = _artifact([_probe("ok-probe")]).to_dict()
    del d["probes"]
    baseline = tmp_path / "noprobes.json"
    baseline.write_text(json.dumps(d))
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(baseline)])
    assert result.exit_code == 2
    assert result.exception is None or not isinstance(result.exception, KeyError)
    assert "baseline error" in result.stderr


# ------- round-2 N6: fully-dead target is a setup error (exit 2), not exit 1

def test_gate_exit_2_when_no_probe_scored_any_trial(monkeypatch, tmp_path):
    # fail_on_error=False + dead target => log.status "success" with zero
    # scored trials everywhere; that must surface as a run error (exit 2),
    # never an all-MISSING gate FAIL (exit 1)
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")

    class _EmptyLog:
        status = "success"
        samples = []
        location = None

    monkeypatch.setattr("evalyn.engine.run.inspect_eval",
                        lambda *a, **k: [_EmptyLog()])
    monkeypatch.setattr("evalyn.engine.run._judge_usd", lambda log: 0.0)
    out = tmp_path / "runs"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json"),
                                 "--out-dir", str(out)])
    assert result.exit_code == 2
    assert "run error" in result.stderr and "no probe" in result.stderr
    # write-before-raise house pattern: the artifact is on disk for inspection
    assert list(out.glob("*.json"))


def test_gate_out_dir_threads_to_run_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    art = _artifact([_probe("ok-probe")])
    seen = {}

    def fake_run(pack, judge_model="mockllm/model", **kwargs):
        seen.update(kwargs)
        return art

    monkeypatch.setattr("evalyn.engine.run.run_gate", fake_run)
    out = tmp_path / "artifacts"
    result = runner.invoke(app, ["gate", "--target", PACK,
                                 "--baseline", str(tmp_path / "none.json"),
                                 "--out-dir", str(out)])
    assert result.exit_code == 0
    assert seen["out_dir"] == str(out)


# ------------------------------------------------------- Task 8: compare command

def _compare_pack(tmp_path: Path, *, generator_family: str | None = None) -> str:
    """Pack with one rubric-checked probe (compare needs no live target)."""
    pack_dir = tmp_path / "cmp-pack"
    (pack_dir / "probes").mkdir(parents=True)
    (pack_dir / "rubrics").mkdir()
    target = ("name: cmp\nsessions:\n  open: {method: POST, path: /session}\n"
              "  message: {method: POST, path: /chat}\n"
              "env: {base_url: http://localhost:8899}\n"
              "allowlist: [http://localhost:8899]\n")
    if generator_family:
        target += f"judge: {{generator_family: {generator_family}}}\n"
    (pack_dir / "target.yaml").write_text(target)
    (pack_dir / "rubrics" / "tone.md").write_text("# Tone\n## Calm\nCalm.\n")
    (pack_dir / "probes" / "p.yaml").write_text(
        "- id: p1\n  category: chat\n  turns: [hi]\n  checks:\n"
        "    - { type: rubric, rubric: tone, required: true }\n")
    return str(pack_dir)


def _compare_artifact_files(pack_dir: str, tmp_path: Path) -> tuple[str, str]:
    """Two on-disk gate artifacts matching the pack's fingerprint."""
    from evalyn.engine.run import pack_fingerprint
    from evalyn.targets.loader import load_pack

    pack = load_pack(pack_dir)

    def _write(name: str, created: str) -> str:
        art = RunArtifact(
            pack_name="cmp", pack_hash=pack_fingerprint(pack),
            judge_model="mockllm/model", created_at=created,
            probes=[ProbeResult(
                id="p1", category="chat", kind="regression",
                safety_critical=False, samples=1, trials=1,
                trial_records=[{"epoch": 0,
                                "transcript": "User: hi\nAssistant: hey",
                                "session_seconds": 1.0,
                                "invariant_failures": 0}])],
            log_path="runs/logs")
        p = tmp_path / name
        p.write_text(json.dumps(art.to_dict()))
        return str(p)

    return (_write("run-a.json", "2026-08-01T00:00:00+00:00"),
            _write("run-b.json", "2026-08-02T00:00:00+00:00"))


def _stub_judge_pair(monkeypatch, verdict: str = "A"):
    """Offline scripted judge_pair — zero judge tokens, no network."""
    from evalyn.scoring.pairwise import PairVerdict

    async def fake(rubric_text, rubric_hash, transcript_a, transcript_b,
                   judge_model, *, cache_dir=None, context=None, steps=None, rng):
        return PairVerdict(
            verdicts={"Calm": verdict}, flipped={"Calm": False},
            votes={"Calm": []}, justifications={"Calm": "j"},
            steps=steps or ["s"], rubric_hash=rubric_hash,
            usage={"openai/gpt-4o": {"input_tokens": 100, "output_tokens": 100}})

    monkeypatch.setattr("evalyn.engine.compare.judge_pair", fake)


def _fresh_calibration(pack_dir: str, model: str | None = None):
    from evalyn.engine.calibrate import write_record
    from evalyn.targets.loader import load_pack

    pack = load_pack(pack_dir)
    write_record(pack, 0.9, {"tone:Calm": 0.9},
                 model or pack.spec.judge.rubric_model)


def test_compare_refuses_stale_calibration_without_flag(monkeypatch, tmp_path):
    # fail-closed BEFORE artifacts are even loaded (briefed flow order): the
    # artifact paths here do not exist, yet the message is about calibration
    pack_dir = _compare_pack(tmp_path)

    async def must_not_run(*a, **k):
        raise AssertionError("run_compare must not run uncalibrated")

    monkeypatch.setattr("evalyn.engine.compare.run_compare", must_not_run)
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", str(tmp_path / "no-a.json"),
                                 "--b", str(tmp_path / "no-b.json")])
    assert result.exit_code == 2
    assert "setup error" in result.stderr
    assert "calibration" in result.stderr
    assert "--allow-uncalibrated" in result.stderr


def test_compare_allow_uncalibrated_warns_and_marks_artifact(monkeypatch, tmp_path):
    pack_dir = _compare_pack(tmp_path)
    a, b = _compare_artifact_files(pack_dir, tmp_path)
    _stub_judge_pair(monkeypatch)
    out = tmp_path / "out"
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", a, "--b", b, "--allow-uncalibrated",
                                 "--out-dir", str(out)])
    assert result.exit_code == 0
    assert "UNCALIBRATED" in result.stderr  # loud, on stderr
    written = list(out.glob("*-compare.json"))
    assert written
    assert json.loads(written[0].read_text())["rubric_scores_untrusted"] is True
    assert "UNTRUSTED" in result.stdout  # report banner


def test_compare_happy_path_exit_0_prints_overview_table(monkeypatch, tmp_path):
    pack_dir = _compare_pack(tmp_path)
    _fresh_calibration(pack_dir)
    a, b = _compare_artifact_files(pack_dir, tmp_path)
    _stub_judge_pair(monkeypatch)
    out = tmp_path / "out"
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", a, "--b", b, "--out-dir", str(out)])
    assert result.exit_code == 0  # advisory: no exit-1 path exists
    assert "# Evalyn compare — cmp: A vs B" in result.stdout
    assert "| category | A wins | B wins | ties | unsure | flip rate |" in result.stdout
    assert "| chat | 1 | 0 | 0 | 0 |" in result.stdout
    assert "no combined winner is computed" in result.stdout
    assert "UNCALIBRATED" not in result.stderr
    written = list(out.glob("*-compare.json"))
    assert written, "compare must write its artifact"
    saved = json.loads(written[0].read_text())
    assert saved["source_a"] == a and saved["source_b"] == b
    assert saved["rubric_scores_untrusted"] is False


def test_compare_labels_thread_into_report_and_artifact(monkeypatch, tmp_path):
    pack_dir = _compare_pack(tmp_path)
    _fresh_calibration(pack_dir)
    a, b = _compare_artifact_files(pack_dir, tmp_path)
    _stub_judge_pair(monkeypatch)
    out = tmp_path / "out"
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", a, "--b", b,
                                 "--label-a", "main", "--label-b", "candidate",
                                 "--out-dir", str(out)])
    assert result.exit_code == 0
    assert "cmp: main vs candidate" in result.stdout
    saved = json.loads(next(iter(out.glob("*-compare.json"))).read_text())
    assert saved["label_a"] == "main" and saved["label_b"] == "candidate"


def test_compare_exit_2_on_corrupt_artifact_json(monkeypatch, tmp_path):
    pack_dir = _compare_pack(tmp_path)
    _fresh_calibration(pack_dir)
    _, b = _compare_artifact_files(pack_dir, tmp_path)
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json at all")
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", str(corrupt), "--b", b])
    assert result.exit_code == 2
    assert "artifact A" in result.stderr  # message names the side
    assert "Traceback" not in result.stderr


def test_compare_exit_2_on_old_schema_artifact_names_side_b(monkeypatch, tmp_path):
    pack_dir = _compare_pack(tmp_path)
    _fresh_calibration(pack_dir)
    a, _ = _compare_artifact_files(pack_dir, tmp_path)
    old = tmp_path / "old.json"
    old.write_text(json.dumps({
        "pack_name": "cmp", "pack_hash": "a" * 64, "judge_model": "m",
        "created_at": "2026-01-01T00:00:00+00:00", "log_path": "runs/logs",
        "probes": [{"id": "p", "passed": True}],  # Plan #1 shape
    }))
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", a, "--b", str(old)])
    assert result.exit_code == 2
    assert "artifact B" in result.stderr
    assert "predates" in result.stderr


def test_compare_warns_on_judge_generator_family_match(monkeypatch, tmp_path):
    # compare never calls build_task, so it must mirror its self-preference
    # warning for the resolved rubric judge (spec §2.1)
    pack_dir = _compare_pack(tmp_path, generator_family="openai")
    _fresh_calibration(pack_dir, model="openai/gpt-4o")
    a, b = _compare_artifact_files(pack_dir, tmp_path)
    _stub_judge_pair(monkeypatch)
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", a, "--b", b,
                                 "--rubric-judge-model", "openai/gpt-4o",
                                 "--out-dir", str(tmp_path / "out")])
    assert result.exit_code == 0  # a warning, never an error
    assert "self-preference" in result.stderr


def test_compare_exit_2_on_budget_exceeded(monkeypatch, tmp_path):
    pack_dir = _compare_pack(tmp_path)
    _fresh_calibration(pack_dir)
    a, b = _compare_artifact_files(pack_dir, tmp_path)

    async def over_budget(*args, **kwargs):
        from evalyn.engine.budget import BudgetExceeded
        raise BudgetExceeded("judge spend $7.5000 exceeded max_usd_per_run $5.00")

    monkeypatch.setattr("evalyn.engine.compare.run_compare", over_budget)
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", a, "--b", b])
    assert result.exit_code == 2
    assert "budget" in result.stderr.lower()


def test_compare_exit_2_on_artifact_write_failure(monkeypatch, tmp_path):
    # the post-run_compare write must not escape as an uncaught traceback
    # (exit 1) — compare's contract is exit 0/2 only
    pack_dir = _compare_pack(tmp_path)
    _fresh_calibration(pack_dir)
    a, b = _compare_artifact_files(pack_dir, tmp_path)
    _stub_judge_pair(monkeypatch)

    def cannot_write(art, out_dir="runs"):
        raise OSError("disk full")

    monkeypatch.setattr("evalyn.engine.compare.write_compare_artifact",
                        cannot_write)
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", a, "--b", b,
                                 "--out-dir", str(tmp_path / "out")])
    assert result.exit_code == 2
    assert "run error" in result.stderr
    assert "Traceback" not in result.stderr


def test_compare_debug_reraises(monkeypatch, tmp_path):
    pack_dir = _compare_pack(tmp_path)
    _fresh_calibration(pack_dir)
    a, b = _compare_artifact_files(pack_dir, tmp_path)

    async def boom(*args, **kwargs):
        raise ConnectionError("judge unreachable")

    monkeypatch.setattr("evalyn.engine.compare.run_compare", boom)
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", a, "--b", b, "--debug"])
    assert isinstance(result.exception, ConnectionError)


# -------------------------------------------------------- discover: smoke tests
# Full preflight/exit-code coverage lives in tests/discovery/test_cli_discover.py;
# these are the top-level registration + dry-run smoke checks.

def test_discover_help_registered():
    result = runner.invoke(app, ["discover", "--help"])
    assert result.exit_code == 0
    assert "--target" in result.stdout
    assert "--objective" in result.stdout


def test_discover_dry_run_smoke(monkeypatch):
    async def must_not_run(pack, cfg, **kw):
        raise AssertionError("run_discovery must not be called under --dry-run")

    monkeypatch.setattr("evalyn.discovery.run.run_discovery", must_not_run)
    result = runner.invoke(app, ["discover", "--target", PACK, "--dry-run"])
    assert result.exit_code == 0
    assert "dry-run" in result.stdout


# ------------------------------------------- Plan #4 Task 2: EVALYN_RUN_ID
# The cockpit launches these commands as subprocesses with EVALYN_RUN_ID set, so
# the server knows the artifact path before the run starts. The CLI is the ONLY
# layer that reads that env var — everything below it takes a parameter.

RID = "20260807T101112000000-deadbeef-example"


def _capture_gate(monkeypatch):
    seen = {}

    def fake_run(pack, judge_model="mockllm/model", **kwargs):
        seen.update(kwargs)
        return _artifact([_probe("ok-probe")])

    monkeypatch.setattr("evalyn.engine.run.run_gate", fake_run)
    return seen


def _invoke_gate(tmp_path):
    return runner.invoke(app, ["gate", "--target", PACK,
                               "--baseline", str(tmp_path / "none.json"),
                               "--out-dir", str(tmp_path / "artifacts")])


def test_gate_threads_evalyn_run_id_to_the_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    monkeypatch.setenv("EVALYN_RUN_ID", RID)
    seen = _capture_gate(monkeypatch)
    assert _invoke_gate(tmp_path).exit_code == 0
    assert seen["run_id"] == RID


def test_gate_without_the_env_var_passes_none_and_mints_as_always(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    monkeypatch.delenv("EVALYN_RUN_ID", raising=False)
    seen = _capture_gate(monkeypatch)
    assert _invoke_gate(tmp_path).exit_code == 0
    assert seen["run_id"] is None


@pytest.mark.parametrize("bad", ["not-a-run-id", "../escape", RID + ".json", " "])
def test_an_invalid_evalyn_run_id_is_ignored_never_fatal(monkeypatch, tmp_path, bad):
    """A stale export in someone's shell must not be able to abort a run."""
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    monkeypatch.setenv("EVALYN_RUN_ID", bad)
    seen = _capture_gate(monkeypatch)
    result = _invoke_gate(tmp_path)
    assert result.exit_code == 0          # the run still happens
    assert seen["run_id"] is None         # ...with a freshly minted name
    assert "EVALYN_RUN_ID" in result.stderr and "ignoring" in result.stderr


def test_gate_run_id_reaches_the_artifact_filename_end_to_end(monkeypatch, tmp_path):
    """The whole point: the server can predict the path before the run starts."""
    from evalyn.engine import run as run_mod

    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    monkeypatch.setenv("EVALYN_RUN_ID", RID)
    out = tmp_path / "artifacts"

    def fake_run(pack, judge_model="mockllm/model", *, run_id=None, out_dir="runs",
                 **kwargs):
        art = _artifact([_probe("ok-probe")])
        run_mod.atomic_write_artifact(art.to_dict(), "example", out_dir,
                                      suffix="", run_id=run_id)
        return art

    monkeypatch.setattr("evalyn.engine.run.run_gate", fake_run)
    assert _invoke_gate(tmp_path).exit_code == 0
    assert [p.name for p in out.glob("*.json")] == [f"{RID}.json"]


def test_compare_threads_evalyn_run_id_to_run_and_write(monkeypatch, tmp_path):
    pack_dir = _compare_pack(tmp_path)
    a, b = _compare_artifact_files(pack_dir, tmp_path)
    _stub_judge_pair(monkeypatch)
    _fresh_calibration(pack_dir)
    monkeypatch.setenv("EVALYN_RUN_ID", RID)
    out = tmp_path / "out"
    result = runner.invoke(app, ["compare", "--target", pack_dir,
                                 "--a", a, "--b", b, "--out-dir", str(out)])
    assert result.exit_code == 0
    assert [p.name for p in out.glob("*.json")] == [f"{RID}-compare.json"]


def test_discover_threads_evalyn_run_id_to_run_discovery(monkeypatch):
    seen = {}

    async def fake(pack, cfg, **kw):
        seen.update(kw)
        raise ConnectionError("stop here — the seam is what is under test")

    monkeypatch.setattr("evalyn.discovery.run.run_discovery", fake)
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    monkeypatch.setenv("EVALYN_RUN_ID", RID)
    result = runner.invoke(app, ["discover", "--target", PACK,
                                 "--objective", "prompt-injection-bypass"])
    assert result.exit_code == 3          # ran, then failed: the seam was reached
    assert seen["run_id"] == RID


def test_the_env_var_is_read_in_the_cli_and_nowhere_below_it(monkeypatch):
    """Env is how a subprocess is TOLD; the parameter is how the id flows."""
    import inspect

    from evalyn.discovery import run as discovery_run
    from evalyn.engine import compare as cmp_mod
    from evalyn.engine import run as run_mod

    for mod in (run_mod, cmp_mod, discovery_run):
        src = inspect.getsource(mod)
        assert "os.environ" not in src and "getenv" not in src, mod.__name__
