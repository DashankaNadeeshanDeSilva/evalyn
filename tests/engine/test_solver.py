import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from inspect_ai import Task, eval as inspect_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import scorer, accuracy, Score, CORRECT, Target
from inspect_ai.solver import TaskState
from evalyn.engine.solver import session_solver
from evalyn.targets.loader import Pack, load_pack
from evalyn.targets.schema import TargetSpec

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


@pytest.mark.asyncio
async def test_solver_drops_seeded_input_message_from_transcript(toy_target, monkeypatch):
    """PR #4 fix #5: Inspect seeds state.messages with Sample.input (the probe
    id). That fabricated 'user turn' must never reach the judged transcript —
    after solve, the messages are EXACTLY the real session turns."""
    from inspect_ai.model import ChatMessageUser
    from evalyn.scoring.transcript import assistant_turns, labeled_transcript

    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(MINIPACK)
    state = TaskState(model="m", sample_id="inv-nonempty", epoch=1,
                      input="inv-nonempty",
                      messages=[ChatMessageUser(content="inv-nonempty")])
    state.metadata = {"turns": ["Where did you work?"]}
    state = await session_solver(pack)(state, None)
    transcript = labeled_transcript(state)
    assert "inv-nonempty" not in transcript          # no probe-id label leakage
    assert transcript.startswith("User: Where did you work?")
    assert [m.role for m in state.messages] == ["user", "assistant"]
    # tier1 turn scanning sees the same assistant turns as before
    assert assistant_turns(state) == [state.output.completion]


def test_solver_drives_toy_target(toy_target, monkeypatch):
    monkeypatch.setenv("EVALYN_TARGET_URL", toy_target)
    pack = load_pack(MINIPACK)
    ds = MemoryDataset([Sample(input="work", target="x",
                               metadata={"turns": ["Where did you work?"]})])
    task = Task(dataset=ds, solver=session_solver(pack), scorer=_capture())
    logs = inspect_eval(task, model="mockllm/model", display="none")
    reply = logs[0].samples[0].scores["_capture"].answer
    assert "Acme" in reply


# --- Task 6: session flow, auth, max_turns, named-sse -------------------------


class _BaseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _send(self, body: bytes, content_type: str = "application/json"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def _serve(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _pack(url: str, sessions: dict, auth: dict | None = None) -> Pack:
    spec = TargetSpec.model_validate({
        "name": "t", "sessions": sessions,
        "auth": auth or {"kind": "none"},
        "env": {"base_url": url},
        "allowlist": [url],
    })
    return Pack(spec=spec, probes=[], root=Path("."))


def _state(turns: list[str]) -> TaskState:
    state = TaskState(model="m", sample_id="1", epoch=1, input="x", messages=[])
    state.metadata = {"turns": turns}
    return state


@pytest.mark.asyncio
async def test_max_turns_breach_raises_naming_the_cap(monkeypatch):
    """Exceeding max_turns_per_session is a loud transport error, never a silent
    empty reply. Raised before any HTTP happens."""
    monkeypatch.setenv("EVALYN_TARGET_URL", "http://localhost:8899")
    pack = load_pack(MINIPACK)  # Budget default: max_turns_per_session=12
    solve = session_solver(pack)
    with pytest.raises(RuntimeError, match="max_turns_per_session=12"):
        await solve(_state(["hi"] * 13), None)


class _NamedSSEHandler(_BaseHandler):
    def do_POST(self):
        if self.path == "/open":
            self._send(json.dumps({"session_id": "s-1"}).encode())
        elif self.path == "/msg":
            frames = ('event: token\ndata: {"type":"token","content":"Hello "}\n\n'
                      'event: token\ndata: {"type":"token","content":"world"}\n\n'
                      'event: done\ndata: {"type":"done"}\n\n')
            self._send(frames.encode(), content_type="text/event-stream")
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.mark.asyncio
async def test_solver_parses_named_sse_stream():
    with _serve(_NamedSSEHandler) as url:
        pack = _pack(url, {
            "open": {"method": "POST", "path": "/open"},
            "message": {"method": "POST", "path": "/msg", "stream": "sse",
                        "event_format": "named-sse", "event_name": "token",
                        "content_field": "content"},
        })
        state = await session_solver(pack)(_state(["hi"]), None)
    assert state.output.completion == "Hello world"
    assert [m.role for m in state.messages] == ["user", "assistant"]
    assert state.messages[1].text == "Hello world"


_custom_flow_seen: dict = {}


class _CustomFlowHandler(_BaseHandler):
    def do_POST(self):
        body = self._body()
        if self.path == "/begin":
            _custom_flow_seen["open_body"] = body
            self._send(json.dumps({"sid": "s-42"}).encode())
        elif self.path == "/talk":
            _custom_flow_seen["msg_body"] = body
            _custom_flow_seen["auth"] = self.headers.get("Authorization")
            reply = {"delta": f"echo:{body.get('text')}:{body.get('conversation')}"}
            self._send(json.dumps(reply).encode())
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.mark.asyncio
async def test_solver_honors_custom_flow_fields_and_auth():
    """open_body, session_id_field, message_field, session_field and bearer auth
    all flow through to the wire."""
    _custom_flow_seen.clear()
    with _serve(_CustomFlowHandler) as url:
        pack = _pack(url, {
            "open": {"method": "POST", "path": "/begin",
                     "open_body": {"mode": "eval"}, "session_id_field": "sid"},
            "message": {"method": "POST", "path": "/talk", "event_format": "json",
                        "message_field": "text", "session_field": "conversation"},
        }, auth={"kind": "bearer", "token": "sekrit"})
        state = await session_solver(pack)(_state(["hi"]), None)
    assert state.output.completion == "echo:hi:s-42"
    assert _custom_flow_seen["open_body"] == {"mode": "eval"}
    assert _custom_flow_seen["msg_body"] == {"text": "hi", "conversation": "s-42"}
    assert _custom_flow_seen["auth"] == "Bearer sekrit"


# --- Task 0 review fix: partial transcript survives a mid-send failure -------


_fail_second = {"calls": 0}


class _FailSecondSendHandler(_BaseHandler):
    def do_POST(self):
        if self.path == "/open":
            self._send(json.dumps({"session_id": "s-1"}).encode())
        elif self.path == "/msg":
            _fail_second["calls"] += 1
            if _fail_second["calls"] == 1:
                self._send(json.dumps({"delta": "first"}).encode())
            else:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.mark.asyncio
async def test_mid_send_failure_preserves_partial_transcript():
    """When turn N's HTTP fails, state.messages must keep every completed
    user/assistant pair PLUS the dangling user message of the failed turn —
    the errored sample's log transcript shows everything up to the failure."""
    import httpx

    _fail_second["calls"] = 0
    with _serve(_FailSecondSendHandler) as url:
        pack = _pack(url, {
            "open": {"method": "POST", "path": "/open"},
            "message": {"method": "POST", "path": "/msg", "event_format": "json"},
        })
        state = _state(["one", "two"])
        with pytest.raises(httpx.HTTPStatusError):
            await session_solver(pack)(state, None)
    assert [m.role for m in state.messages] == ["user", "assistant", "user"]
    assert state.messages[0].text == "one"
    assert state.messages[1].text == "first"
    assert state.messages[2].text == "two"
