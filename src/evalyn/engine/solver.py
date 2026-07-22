from __future__ import annotations
import httpx
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import concurrency

from evalyn.targets.loader import Pack, resolve_base_url
from evalyn.targets.streams import parse_stream


@solver
def session_solver(pack: Pack) -> Solver:
    base_url = resolve_base_url(pack)          # allowlist enforced here
    open_ep = pack.spec.sessions["open"]
    msg_ep = pack.spec.sessions["message"]

    async def _open(client: httpx.AsyncClient) -> str:
        r = await client.request(open_ep.method, f"{base_url}{open_ep.path}", json={})
        r.raise_for_status()
        return r.json().get("session_id", "")

    async def _send(client: httpx.AsyncClient, session_id: str, message: str) -> str:
        payload = {"session_id": session_id, "message": message}
        if msg_ep.stream == "sse":
            async with client.stream(msg_ep.method, f"{base_url}{msg_ep.path}",
                                     json=payload) as resp:
                resp.raise_for_status()
                lines = [line async for line in resp.aiter_lines()]
            return parse_stream(msg_ep.event_format, lines)
        r = await client.request(msg_ep.method, f"{base_url}{msg_ep.path}", json=payload)
        r.raise_for_status()
        return parse_stream(msg_ep.event_format, r.text.splitlines())

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        turns = state.metadata["turns"]
        last = ""
        async with concurrency("evalyn-target-http", pack.spec.concurrency):
            async with httpx.AsyncClient(timeout=30) as client:
                session_id = await _open(client)
                for turn in turns:
                    state.messages.append(ChatMessageUser(content=turn))
                    last = await _send(client, session_id, turn)
                    state.messages.append(ChatMessageAssistant(content=last))
        state.output = ModelOutput.from_content(model="evalyn-target", content=last)
        return state

    return solve
