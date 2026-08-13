"""Reusable target-session driver, extracted from engine/solver.py (Plan #3
Task 0). Gate's ``session_solver`` and discover's red-team agent drive the
target product through this ONE open/send/SSE-parse path — never a second
hand-rolled HTTP client.

Containment: :meth:`TargetSession.open` forms its base_url exclusively through
``resolve_base_url(pack)``, so the pack allowlist is enforced on every session
regardless of which mode opened it. The Inspect ``concurrency()`` gate is the
CALLER's job, wrapped around ``open`` — it does not live here.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageUser

from evalyn.targets.auth import auth_headers
from evalyn.targets.loader import Pack, resolve_base_url
from evalyn.targets.streams import parse_stream


class TurnCapExceeded(RuntimeError):
    """A send() would exceed the pack's budget.max_turns_per_session."""


class TargetSession:
    """One open conversation with the target. Construct via :meth:`open`."""

    def __init__(self, pack: Pack, client: httpx.AsyncClient, base_url: str,
                 session_id: str, started: float) -> None:
        self._pack = pack
        self._client = client
        self._base_url = base_url
        self._session_id = session_id
        self._started = started
        self._elapsed: float | None = None
        self._turns_used = 0
        self._messages: list[ChatMessage] = []

    @classmethod
    @asynccontextmanager
    async def open(cls, pack: Pack, *,
                   timeout: float = 30.0) -> AsyncIterator[TargetSession]:
        base_url = resolve_base_url(pack)          # allowlist enforced here
        open_ep = pack.spec.sessions["open"]
        headers = auth_headers(pack.spec.auth)
        # Clock covers open + every turn + client teardown: target session
        # time only. The caller keeps its concurrency gate OUTSIDE open() so
        # scheduler queue wait is never counted (user ruling 2026-08-03).
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            r = await client.request(open_ep.method, f"{base_url}{open_ep.path}",
                                     json=open_ep.open_body or {})
            r.raise_for_status()
            data = r.json()
            field = open_ep.session_id_field
            if field not in data:
                raise RuntimeError(
                    f"target open response from {open_ep.path} has no {field!r} key")
            session = cls(pack, client, base_url, data[field], started)
            yield session
        session._elapsed = time.monotonic() - started

    async def send(self, message: str) -> str:
        max_turns = self._pack.spec.budget.max_turns_per_session
        if self._turns_used >= max_turns:
            raise TurnCapExceeded(
                f"turn {self._turns_used + 1} would exceed "
                f"max_turns_per_session={max_turns}")
        msg_ep = self._pack.spec.sessions["message"]
        payload = {msg_ep.message_field: message,
                   msg_ep.session_field: self._session_id}
        # User message recorded BEFORE the HTTP call: when a turn fails, the
        # partial transcript still shows what was sent (review fix, Task 0).
        self._messages.append(ChatMessageUser(content=message))
        if msg_ep.stream == "sse":
            async with self._client.stream(msg_ep.method,
                                           f"{self._base_url}{msg_ep.path}",
                                           json=payload) as resp:
                resp.raise_for_status()
                lines = [line async for line in resp.aiter_lines()]
            reply = parse_stream(msg_ep.event_format, lines,
                                 event=msg_ep.event_name,
                                 field=msg_ep.content_field)
        else:
            r = await self._client.request(msg_ep.method,
                                           f"{self._base_url}{msg_ep.path}",
                                           json=payload)
            r.raise_for_status()
            reply = parse_stream(msg_ep.event_format, r.text.splitlines(),
                                 event=msg_ep.event_name,
                                 field=msg_ep.content_field)
        self._turns_used += 1
        self._messages.append(ChatMessageAssistant(content=reply))
        return reply

    @property
    def turns_used(self) -> int:
        return self._turns_used

    @property
    def elapsed_seconds(self) -> float:
        if self._elapsed is not None:
            return self._elapsed
        return time.monotonic() - self._started

    @property
    def messages(self) -> list[ChatMessage]:
        # Copy: callers must not be able to corrupt session state by mutating
        # the returned list (review minor, Task 0).
        return list(self._messages)
