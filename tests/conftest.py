import shutil
import threading
import time
from pathlib import Path

import httpx
import pytest
from examples.toy_target import Handler
from http.server import ThreadingHTTPServer

from evalyn.targets.loader import Pack
from evalyn.targets.schema import Probe, TargetSpec

# The port these test packs name when no live server is involved. Nothing binds
# it: it is an inert string in packs whose base_url is never dialled. Tests that
# DO need a live server take the `toy_target` fixture, which binds an ephemeral
# port and hands back the URL — see `retarget_yaml` below.
INERT_BASE_URL = "http://localhost:8899"


def minimal_target_yaml(base_url: str = INERT_BASE_URL, *,
                        invariants: str = "[]") -> str:
    """The shared minimal target.yaml (Task 12), for one `base_url`.

    `base_url` lands in both `env.base_url` and the allowlist, so a pack built
    this way is loadable — the allowlist check in `resolve_base_url` is an exact
    string match, and a mismatch there surfaces as an `AllowlistError`, not as a
    connection error.
    """
    return (
        "name: t\nsessions:\n  open: {method: POST, path: /session}\n"
        "  message: {method: POST, path: /chat}\nauth: {kind: none}\n"
        f"env: {{base_url: {base_url}}}\nallowlist: [{base_url}]\n"
        f"invariants: {invariants}\n"
    )


def retarget_yaml(text: str, base_url: str) -> str:
    """Re-point a fixed-port pack's target.yaml at a live `toy_target` URL.

    Only the port moves. **Both host spellings are kept distinct**: several
    packs list `http://localhost:8899` *and* `http://127.0.0.1:8899` in one
    allowlist while resolving `base_url` to the 127.0.0.1 spelling, so mapping
    both onto the fixture's URL would duplicate an allowlist entry and stop
    mirroring the shape of the shipped packs. (Reaching a 127.0.0.1-only server
    via the `localhost` spelling was measured to work here — httpx falls back
    past `::1` — so that is not the reason.)

    The rewrite must bite: a text with no `:8899` in it would sail through
    unchanged and leave the pack pointed at a port nothing is listening on, so
    the no-op is an error rather than a silent pass-through.
    """
    port = httpx.URL(base_url).port
    out = (text.replace("http://127.0.0.1:8899", f"http://127.0.0.1:{port}")
               .replace("http://localhost:8899", f"http://localhost:{port}"))
    assert out != text, ("retarget_yaml found no :8899 to move — "
                         "pack is not pointed at the live target")
    return out


@pytest.fixture
def minimal_pack(tmp_path):
    """Factory: write a minimal on-disk pack and return its directory Path.

    ``probes_yaml=None`` writes no probes file (an empty pack). ``base_url``
    defaults to the inert literal; pass the ``toy_target`` fixture's URL to make
    the pack point at a live server.
    """
    def _make(probes_yaml: str | None, *, invariants: str = "[]",
              base_url: str = INERT_BASE_URL) -> Path:
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        (pack_dir / "target.yaml").write_text(
            minimal_target_yaml(base_url, invariants=invariants))
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
    """The toy target on an **ephemeral** port; yields its base URL.

    Port 0 lets the OS pick a free port, so two `pytest` processes on this
    machine can run at the same time. A fixed port cannot: it is machine-level,
    so git worktrees do not help and `SO_REUSEADDR` does not either (it permits
    rebinding a socket in TIME_WAIT, not one a live process is listening on).

    The yielded URL is the single source of truth for the port — never hardcode
    one. Packs that must reach this server take their base_url and allowlist
    from it (see `retarget_yaml`).
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    # wait until it answers
    for _ in range(50):
        try:
            httpx.post(f"{base_url}/session", json={}, timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    yield base_url
    server.shutdown()


@pytest.fixture
def retarget_to_toy(toy_target):
    """`retarget_yaml` bound to this session's live target — for packs whose
    target.yaml is a literal in the test file rather than a directory on disk.
    """
    def _retarget(text: str) -> str:
        return retarget_yaml(text, toy_target)
    return _retarget


@pytest.fixture
def live_pack_dir(tmp_path, toy_target):
    """Factory: copy an on-disk pack into tmp and point it at `toy_target`.

    The repo's own packs (`packs/example`, `tests/fixtures/minipack`) hardcode
    port 8899 in their allowlists; they are shipped artifacts, not test
    scaffolding, so tests take a retargeted copy rather than editing them.
    """
    def _make(src: Path | str, *, name: str = "live-pack") -> Path:
        root = tmp_path / name
        shutil.copytree(src, root)
        target = root / "target.yaml"
        target.write_text(retarget_yaml(target.read_text(), toy_target))
        return root
    return _make
