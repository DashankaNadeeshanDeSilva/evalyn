import pytest
from inspect_ai import Task, eval as inspect_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import scorer, accuracy, Score, CORRECT, Target
from inspect_ai.solver import TaskState
from evalyn.engine.solver import session_solver
from evalyn.targets.loader import load_pack
from pathlib import Path

MINIPACK = Path(__file__).parent.parent / "fixtures" / "minipack"


@scorer(metrics=[accuracy()])
def _capture():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=CORRECT, answer=state.output.completion)
    return score


def test_solver_drives_toy_target(toy_target, monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(MINIPACK)
    ds = MemoryDataset([Sample(input="work", target="x",
                               metadata={"turns": ["Where did you work?"]})])
    task = Task(dataset=ds, solver=session_solver(pack), scorer=_capture())
    logs = inspect_eval(task, model="mockllm/model", display="none")
    reply = logs[0].samples[0].scores["_capture"].answer
    assert "Acme" in reply
