from pathlib import Path

from inspect_ai import eval as inspect_eval

from evalyn.engine.task_builder import build_task
from evalyn.targets.loader import load_pack

MINIPACK = Path(__file__).parent.parent / "fixtures" / "minipack"


def test_build_task_runs_and_records_reducers(toy_target, monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(MINIPACK)
    task = build_task(pack, judge_model="mockllm/model")
    meta = task.dataset[0].metadata
    assert {"id", "category", "kind", "safety_critical", "turns", "checks", "samples"} <= meta.keys()
    assert all(isinstance(c, dict) for c in meta["checks"])
    logs = inspect_eval(task, model="mockllm/model", display="none")
    reducers = {s.reducer for s in logs[0].results.scores}
    # Amendment A2: assert specific reducer keys (the brief's `or "mean"` branch
    # was unfalsifiable). minipack probe has samples=1 -> k=1.
    assert "pass_at_1" in reducers
    assert "pass_k_1" in reducers
    assert "mean" in reducers
    assert logs[0].status == "success"
