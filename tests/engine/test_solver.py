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


@pytest.mark.asyncio
async def test_open_response_without_session_id_raises(monkeypatch):
    """A session-open reply missing 'session_id' must fail loudly, never proceed with ''."""
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(MINIPACK)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"unexpected": "shape"}  # no session_id key

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, *args, **kwargs):
            return FakeResponse()

        def stream(self, *args, **kwargs):
            raise AssertionError(
                "solver proceeded to send a message despite a bad open response")

    monkeypatch.setattr("evalyn.engine.solver.httpx.AsyncClient", FakeClient)
    solve = session_solver(pack)
    state = TaskState(model="m", sample_id="1", epoch=1, input="x", messages=[])
    state.metadata = {"turns": ["hi"]}
    with pytest.raises(RuntimeError, match="session_id"):
        await solve(state, None)


def test_solver_drives_toy_target(toy_target, monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(MINIPACK)
    ds = MemoryDataset([Sample(input="work", target="x",
                               metadata={"turns": ["Where did you work?"]})])
    task = Task(dataset=ds, solver=session_solver(pack), scorer=_capture())
    logs = inspect_eval(task, model="mockllm/model", display="none")
    reply = logs[0].samples[0].scores["_capture"].answer
    assert "Acme" in reply
