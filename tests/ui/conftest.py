"""Shared fixtures for the cockpit's server tests (Plan #4, Task 6).

Two rules constrain everything in here.

**No fixture may bind a fixed port (R4-8).** The session-scoped `toy_target`
fixture already owns one, and concurrent binds to a hard-coded port cost this
repository ~46 `EADDRINUSE` failures in a single afternoon. The server tests
therefore never start a server at all: `httpx.ASGITransport` speaks ASGI to the
app object in-process, so there is no socket, no port, and nothing to race. A
future fixture that genuinely needs a listening socket must bind port 0 and read
the assigned port back off the socket.

**Never `fastapi.testclient`.** It emits a `StarletteDeprecationWarning` — a
`UserWarning` subclass — at *import*, and this suite is required to be
warning-clean. `asgi_client` below is the whole replacement.
"""
from __future__ import annotations

import contextlib
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The four artifacts `tests/ui/test_index.py` already curates: one gate, one
#: legacy-id gate, one compare, one discover. Copied rather than served from
#: their home so a test may corrupt one without touching the fixtures.
UI_RUN_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "ui_runs"

#: A real, loadable pack — the one `evalyn gate` self-tests against in CI.
EXAMPLE_PACK = _REPO_ROOT / "packs" / "example"


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    """A `runs/` directory holding the curated artifacts, and nothing else."""
    dest = tmp_path / "runs"
    dest.mkdir()
    for src in sorted(UI_RUN_FIXTURES.glob("*.json")):
        dest.joinpath(src.name).write_bytes(src.read_bytes())
    return dest


@pytest.fixture
def asgi_client():
    """`async with asgi_client(app) as client: ...` — an in-process HTTP client.

    `raise_app_exceptions=False` by default because the thing under test is
    precisely what the *browser* receives when a handler explodes: re-raising
    into the test would skip the exception handlers that render it.
    """

    @contextlib.asynccontextmanager
    async def _client(app, *, raise_app_exceptions: bool = False):
        transport = httpx.ASGITransport(app=app,
                                        raise_app_exceptions=raise_app_exceptions)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://ui") as client:
            yield client

    return _client
