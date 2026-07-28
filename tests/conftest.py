import threading
import time
from pathlib import Path

import httpx
import pytest
from examples.toy_target import Handler
from http.server import ThreadingHTTPServer

from evalyn.targets.loader import Pack
from evalyn.targets.schema import Probe, TargetSpec

# Shared minimal target.yaml (Task 12): the single source for the pack-writing
# helpers previously duplicated across tests/test_cli.py and
# tests/engine/test_validate.py.
MINIMAL_TARGET_YAML = (
    "name: t\nsessions:\n  open: {method: POST, path: /session}\n"
    "  message: {method: POST, path: /chat}\nauth: {kind: none}\n"
    "env: {base_url: http://localhost:8899}\nallowlist: [http://localhost:8899]\n"
    "invariants: __INVARIANTS__\n"
)


@pytest.fixture
def minimal_pack(tmp_path):
    """Factory: write a minimal on-disk pack and return its directory Path.

    ``probes_yaml=None`` writes no probes file (an empty pack).
    """
    def _make(probes_yaml: str | None, *, invariants: str = "[]") -> Path:
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        (pack_dir / "target.yaml").write_text(
            MINIMAL_TARGET_YAML.replace("__INVARIANTS__", invariants))
        if probes_yaml is not None:
            (pack_dir / "probes").mkdir()
            (pack_dir / "probes" / "p.yaml").write_text(probes_yaml)
        return pack_dir
    return _make


@pytest.fixture
def minimal_pack_with_probe():
    """Factory: in-memory Pack with one probe (reducer-style tests, Task 3)."""
    def _make(pid="p", *, safety_critical=False, kind="regression", samples=2,
              checks=None) -> Pack:
        spec = TargetSpec(
            name="mini",
            sessions={"chat": {"method": "POST", "path": "/chat"}},
            allowlist=["http://localhost:1"])
        probe = Probe(id=pid, category="misc", kind=kind,
                      safety_critical=safety_critical, turns=["hi"],
                      checks=checks or [{"type": "contains", "value": "x"}],
                      samples=samples)
        return Pack(spec=spec, probes=[probe], root=Path("."))
    return _make


@pytest.fixture(scope="session")
def toy_target():
    server = ThreadingHTTPServer(("127.0.0.1", 8899), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    # wait until it answers
    for _ in range(50):
        try:
            httpx.post("http://127.0.0.1:8899/session", json={}, timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    yield "http://127.0.0.1:8899"
    server.shutdown()
