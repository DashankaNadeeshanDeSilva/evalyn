from __future__ import annotations
import httpx
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import concurrency

from evalyn.targets.auth import auth_headers
from evalyn.targets.loader import Pack, resolve_base_url
from evalyn.targets.streams import parse_stream


@solver
def session_solver(pack: Pack) -> Solver:
    base_url = resolve_base_url(pack)          # allowlist enforced here
    open_ep = pack.spec.sessions["open"]
    msg_ep = pack.spec.sessions["message"]
    headers = auth_headers(pack.spec.auth)
    max_turns = pack.spec.budget.max_turns_per_session

    async def _open(client: httpx.AsyncClient) -> str:
        r = await client.request(open_ep.method, f"{base_url}{open_ep.path}",
                                 json=open_ep.open_body or {})
        r.raise_for_status()
        data = r.json()
        field = open_ep.session_id_field
        if field not in data:
            raise RuntimeError(
                f"target open response from {open_ep.path} has no {field!r} key")
        return data[field]

    async def _send(client: httpx.AsyncClient, session_id: str, message: str) -> str:
        payload = {msg_ep.message_field: message, msg_ep.session_field: session_id}
        if msg_ep.stream == "sse":
            async with client.stream(msg_ep.method, f"{base_url}{msg_ep.path}",
                                     json=payload) as resp:
                resp.raise_for_status()
                lines = [line async for line in resp.aiter_lines()]
            return parse_stream(msg_ep.event_format, lines,
                                event=msg_ep.event_name, field=msg_ep.content_field)
        r = await client.request(msg_ep.method, f"{base_url}{msg_ep.path}", json=payload)
        r.raise_for_status()
        return parse_stream(msg_ep.event_format, r.text.splitlines(),
                            event=msg_ep.event_name, field=msg_ep.content_field)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        turns = state.metadata["turns"]
        if len(turns) > max_turns:
            raise RuntimeError(
                f"probe has {len(turns)} turns > max_turns_per_session={max_turns}")
        last = ""
        async with concurrency("evalyn-target-http", pack.spec.concurrency):
            async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                session_id = await _open(client)
                for turn in turns:
                    state.messages.append(ChatMessageUser(content=turn))
                    last = await _send(client, session_id, turn)
                    state.messages.append(ChatMessageAssistant(content=last))
        state.output = ModelOutput.from_content(model="evalyn-target", content=last)
        return state

    return solve
