"""The `evalyn ui` app skeleton (Plan #4, Task 6).

What this file is actually defending:

* **The chokepoint is wired, not merely available.** Task 4 built
  `RedactingRoute` *and* `redacting_exception_handlers`, and proved both work.
  Neither protects anything until an app mounts them, and mounting the route
  class alone is **not sufficient** (C-T6b): `HTTPException` and every
  registered handler are rendered by Starlette's `ExceptionMiddleware`, which
  sits *above* the route. The body that says "no such run at
  /Users/alice/secrets" is exactly the body the route class never sees.
* **Every non-2xx body is the error envelope.** The SPA reads `error.code` and
  has no second parser, so FastAPI's default `{"detail": …}` is a bug even when
  the status code is right.
* **The SPA is served, and served from a history fallback.** A cockpit whose
  deep links 404 is a cockpit nobody can share a URL into.
* **Loopback only.** This server reads an operator's `runs/` directory and can
  launch processes; `--host 0.0.0.0` is not a configuration, it is an incident.

**Which `run_id` (C-T6/7).** The cockpit keys *everything* — the sidecar
directory, the events file, `app.state.index` — by the **indexed id, i.e. the
artifact stem with its mode suffix still attached** (`<id>-compare`,
`<id>-discover`). That is what `RunIndex._candidates` yields from `path.stem`
and what `RunIndex._sidecar` joins onto `runs/.evalyn-ui/`, so the launcher
(Task 19) must write its `meta.json` under the suffixed id too. The ambiguity
was in the spec; this is the resolution, asserted below by name.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import evalyn
from evalyn.ui.models import display_path, redaction_marker

pytestmark = pytest.mark.ui

COMPARE_ID = "20260806T091011000000-9f8e7d6c-example-compare"
DISCOVER_ID = "20260805T101112000000-1a2b3c4d-example-discover"

#: A string no regex in `redact.py` would catch on its own — so when it comes
#: back redacted, it is because the pack's `not_contains` value was harvested.
PACK_SECRET = "quicksilver-armature-77"

#: A *home-directory* path, because that is the shape the redactor recognises
#: and the shape that actually appears on a projector. `tmp_path` is under
#: `/private/var/...`, which is deliberately not redacted — collapsing every
#: absolute path would blank out the log paths an operator needs to read.
HOME_RUNS = "/Users/alice/Drive/Projects/evalyn/runs"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _app(runs_dir: Path, packs=(), *, allow_discover: bool = False):
    from evalyn.ui.server import create_app

    return create_app(runs_dir, list(packs), allow_discover=allow_discover)


def _ahead_of_the_catch_all(app, path: str, endpoint) -> None:
    """Register `endpoint` in front of the app's `/api` catch-all.

    The catch-all is a real route (that is how an unknown `/api` path becomes a
    404 envelope rather than the SPA's HTML), and it is registered last, so a
    route added afterwards would never be reached. Moving this one to the front
    lets the test exercise **the real app's** handler stack — the same
    exception handlers, the same redactor — rather than a lookalike built in the
    test, which would only prove that the test can wire an app.
    """
    app.add_api_route(path, endpoint, methods=["GET"], include_in_schema=False)
    app.router.routes.insert(0, app.router.routes.pop())


def _pack_with_a_secret(root: Path) -> Path:
    """A minimal loadable pack whose one probe declares a `not_contains`."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "target.yaml").write_text(
        "name: harvest-fixture\n"
        "sessions:\n"
        "  message: { method: POST, path: /chat }\n"
        "auth: { kind: none }\n"
        "env:\n"
        "  base_url: http://127.0.0.1:8899\n"
        "allowlist: [http://127.0.0.1:8899]\n",
        encoding="utf-8")
    probes = root / "probes"
    probes.mkdir(exist_ok=True)
    (probes / "leak.yaml").write_text(
        "- id: never-say-it\n"
        "  category: injection\n"
        "  turns: [\"hello\"]\n"
        "  checks:\n"
        f"    - {{ type: not_contains, value: \"{PACK_SECRET}\" }}\n"
        "    - { type: contains, value: \"Acme is our customer\" }\n",
        encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# 1. `/api/meta` and `/api/health`
# --------------------------------------------------------------------------

async def test_meta_reports_the_version_the_runs_dir_and_that_redaction_is_on(
        runs_dir, asgi_client):
    async with asgi_client(_app(runs_dir)) as client:
        response = await client.get("/api/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == evalyn.__version__
    assert body["runs_dir"] == display_path(str(runs_dir.resolve()))
    # The banner the operator can never turn off is driven by this flag; a
    # cockpit that reported `enabled: false` would be telling the truth about
    # a build nobody should be demoing.
    assert body["redaction"]["enabled"] is True


async def test_meta_collapses_the_operators_home_directory_out_of_runs_dir(
        tmp_path, monkeypatch, asgi_client):
    """`/api/meta` is redaction-*exempt*, so the model does this itself (R4-14).

    Exempt does not mean unexamined: `runs_dir` is the field most likely to
    hold `/Users/<name>/…`, and it is rendered in the SPA's header on a shared
    screen.
    """
    home = (tmp_path / "home").resolve()
    (home / "runs").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    async with asgi_client(_app(home / "runs")) as client:
        body = (await client.get("/api/meta")).json()
    assert body["runs_dir"].startswith("~"), body["runs_dir"]
    assert str(home) not in body["runs_dir"]


async def test_meta_reports_the_pack_allowlist_and_the_discover_flag(
        runs_dir, tmp_path, asgi_client):
    pack = _pack_with_a_secret(tmp_path / "pack")
    async with asgi_client(_app(runs_dir, [pack], allow_discover=True)) as client:
        body = (await client.get("/api/meta")).json()
    assert body["allow_discover"] is True
    assert body["packs"] == [display_path(str(pack.resolve()))]


async def test_health_is_200_and_carries_the_version(runs_dir, asgi_client):
    async with asgi_client(_app(runs_dir)) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": evalyn.__version__}


# --------------------------------------------------------------------------
# 2. Every non-2xx body is the envelope — including the ones rendered *above*
#    the route class (C-T6b)
# --------------------------------------------------------------------------

async def test_an_unknown_api_path_is_the_error_envelope_and_never_a_bare_detail(
        runs_dir, asgi_client):
    async with asgi_client(_app(runs_dir)) as client:
        response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert "detail" not in body, "FastAPI's default shape; the SPA cannot read it"
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"


async def test_an_unknown_api_path_is_the_envelope_under_a_write_method_too(
        runs_dir, asgi_client):
    """A `POST` to a path that does not exist must not fall through to the SPA.

    Without an explicit catch-all it would match the history-fallback route,
    fail its method check, and come back as a 405 about the *SPA* — an answer
    that tells a client the endpoint exists.
    """
    async with asgi_client(_app(runs_dir)) as client:
        response = await client.post("/api/launch", json={"whatever": 1})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_an_unknown_api_path_is_404_under_head_and_options_too(
        runs_dir, asgi_client):
    """A 405 tells a prober the path exists — the one thing this catch-all is
    for. FastAPI's `@app.get` does not add HEAD, so both had to be named."""
    async with asgi_client(_app(runs_dir)) as client:
        assert (await client.head("/api/does-not-exist")).status_code == 404
        response = await client.options("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_head_answers_on_the_root_and_on_health(runs_dir, asgi_client):
    """`curl -I http://127.0.0.1:8765/` is the "is it up" check someone runs
    mid-demo, and it 405'd."""
    async with asgi_client(_app(runs_dir)) as client:
        assert (await client.head("/")).status_code == 200
        assert (await client.head("/api/health")).status_code == 200
        assert (await client.head("/api/meta")).status_code == 200


async def test_the_app_mounts_every_handler_that_renders_above_the_route(runs_dir):
    """C-T6b, structurally. `route_class=RedactingRoute` is not sufficient."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException

    handlers = _app(runs_dir).exception_handlers
    assert {HTTPException, RequestValidationError, Exception} <= set(handlers)


async def test_an_httpexception_detail_is_scrubbed_by_the_real_app(
        runs_dir, asgi_client):
    """The projector test: the body most likely to carry `$HOME` is an error.

    `RedactingRoute` cannot see this body — `ExceptionMiddleware` renders it
    above the route — so this passes only because `create_app` mounted the
    handlers as well as the route class.
    """
    from fastapi import HTTPException

    app = _app(runs_dir)

    async def boom():
        raise HTTPException(status_code=404,
                            detail=f"no such run at {HOME_RUNS}/missing.json")

    _ahead_of_the_catch_all(app, "/api/boom", boom)
    async with asgi_client(app) as client:
        response = await client.get("/api/boom")

    assert response.status_code == 404
    assert HOME_RUNS not in response.text
    assert "alice" not in response.text
    assert redaction_marker("path") in response.json()["error"]["message"]


async def test_the_shipped_app_scrubs_a_success_body_too(runs_dir, asgi_client):
    """The 200 half of the chokepoint, on the real app rather than a lookalike.

    Both routes `create_app` mounts today are `@no_redact`, so it is tempting
    to defer this to whichever task adds the first body-returning endpoint. It
    does not need deferring: `add_api_route` inherits `app.router.route_class`,
    so a route added to the shipped app is a `RedactingRoute` on the shipped
    app's stack. Without this, "a successful response is scrubbed" rests on
    composition — an `isinstance` census plus a lookalike app in
    `test_redact.py` — and not on anything executed here.
    """
    app = _app(runs_dir)

    async def leaky():
        return {"log_path": f"{HOME_RUNS}/x.json", "note": "hello"}

    _ahead_of_the_catch_all(app, "/api/leaky", leaky)
    async with asgi_client(app) as client:
        response = await client.get("/api/leaky")

    assert response.status_code == 200
    assert HOME_RUNS not in response.text
    assert response.json()["log_path"] == redaction_marker("path")
    # ...and only the leak was rewritten. A scrubber that flattened the whole
    # body would pass the assertion above and be useless.
    assert response.json()["note"] == "hello"


async def test_an_unhandled_exception_is_a_500_envelope_and_never_a_traceback(
        runs_dir, asgi_client):
    app = _app(runs_dir)

    async def crash():
        raise RuntimeError(f"blew up reading {HOME_RUNS}")

    _ahead_of_the_catch_all(app, "/api/crash", crash)
    async with asgi_client(app) as client:
        response = await client.get("/api/crash")

    assert response.status_code == 500
    assert set(response.json()) == {"error"}
    # The message is dropped rather than scrubbed: an unhandled exception's
    # text is a repr of whatever blew up, so there is nothing to gain by
    # filtering it and a leak to be had by trying.
    assert "RuntimeError" not in response.text
    assert HOME_RUNS not in response.text


# --------------------------------------------------------------------------
# 3. The redactor the app installs — harvested from the allowlisted packs only
# --------------------------------------------------------------------------

async def test_the_app_harvests_not_contains_values_from_the_allowlisted_packs(
        runs_dir, tmp_path, asgi_client):
    """A pack's `not_contains` value is, by construction, a string the product
    must never emit — so the cockpit must never emit it either."""
    from fastapi import HTTPException

    pack = _pack_with_a_secret(tmp_path / "pack")
    app = _app(runs_dir, [pack])

    async def boom():
        raise HTTPException(status_code=404, detail=f"leaked {PACK_SECRET}")

    _ahead_of_the_catch_all(app, "/api/boom", boom)
    async with asgi_client(app) as client:
        response = await client.get("/api/boom")
    assert PACK_SECRET not in response.text

    # ...and with no pack on the allowlist the sentinel survives, which is what
    # makes the assertion above about *the harvest* rather than about a regex.
    bare = _app(runs_dir)
    _ahead_of_the_catch_all(bare, "/api/boom", boom)
    async with asgi_client(bare) as client:
        assert PACK_SECRET in (await client.get("/api/boom")).text


async def test_the_app_never_harvests_contains_values(runs_dir, tmp_path,
                                                      asgi_client):
    """Ruling R4-18. A `contains` value is the answer the product is *supposed*
    to give; harvesting it blanks the passing transcript out of the demo."""
    from fastapi import HTTPException

    pack = _pack_with_a_secret(tmp_path / "pack")
    app = _app(runs_dir, [pack])

    async def boom():
        raise HTTPException(status_code=404, detail="Acme is our customer")

    _ahead_of_the_catch_all(app, "/api/boom", boom)
    async with asgi_client(app) as client:
        assert "Acme is our customer" in (await client.get("/api/boom")).text


def test_a_pack_that_cannot_be_loaded_refuses_to_start(runs_dir, tmp_path):
    """Fail closed. A pack that does not load is a pack whose `not_contains`
    secrets were not harvested — a silent redaction hole, which is the one
    failure mode this cockpit may not degrade into."""
    from evalyn.targets.loader import PackError

    with pytest.raises(PackError):
        _app(runs_dir, [tmp_path / "not-a-pack"])


# --------------------------------------------------------------------------
# 4. The SPA — root, history fallback, and the hashed bundle
# --------------------------------------------------------------------------

async def test_the_root_serves_the_committed_index_html(runs_dir, asgi_client):
    async with asgi_client(_app(runs_dir)) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Evalyn</title>" in response.text


async def test_an_unknown_non_api_path_serves_index_html_for_the_spa_router(
        runs_dir, asgi_client):
    """`BrowserRouter` owns `/runs/<id>`; the server has never heard of it.

    Without this fallback every deep link and every browser refresh is a 404,
    which is the difference between a cockpit and a demo you may not click in.
    """
    async with asgi_client(_app(runs_dir)) as client:
        response = await client.get(f"/runs/{COMPARE_ID}")
    assert response.status_code == 200
    assert "<title>Evalyn</title>" in response.text


async def test_the_hashed_bundle_assets_are_served(runs_dir, asgi_client):
    static = Path(evalyn.__file__).resolve().parent / "ui" / "static"
    asset = next(iter(sorted((static / "assets").glob("*.js"))))
    async with asgi_client(_app(runs_dir)) as client:
        response = await client.get(f"/assets/{asset.name}")
    assert response.status_code == 200
    assert response.content == asset.read_bytes()


# --------------------------------------------------------------------------
# 5. `serve` — loopback only
# --------------------------------------------------------------------------

def _stub_the_server(monkeypatch) -> dict:
    """Neutralise `uvicorn.run` and `webbrowser.open` for a `serve()` call.

    Not optional politeness: without the stub this test only passes because the
    refusal happens *before* `uvicorn.run`, so a mutation that deleted the
    refusal would not fail — it would bind `0.0.0.0` and hang the suite
    forever. A test whose failure mode is "runs until someone notices" is not
    a test. (Observed: the mutation harness for this task hung on exactly that.)
    """
    import uvicorn
    import webbrowser

    calls: dict = {}
    monkeypatch.setattr(uvicorn, "run",
                        lambda app, **kw: calls.update(kw, app=app))
    monkeypatch.setattr(webbrowser, "open",
                        lambda url: calls.setdefault("opened", url))
    return calls


def test_serve_refuses_any_host_that_is_not_loopback(runs_dir, monkeypatch):
    """Not a preference. This server reads `runs/` and (Task 19) spawns
    processes; on a conference wifi `0.0.0.0` hands both to the room."""
    from evalyn.ui.server import serve

    calls = _stub_the_server(monkeypatch)
    for host in ("0.0.0.0", "::", "192.168.1.7", "localhost"):
        with pytest.raises(ValueError, match="127.0.0.1"):
            serve(runs_dir=runs_dir, packs=[], host=host)
    assert calls == {}, "refused, and refused before anything was bound or opened"


def test_serve_binds_loopback_and_honours_no_open(runs_dir, monkeypatch):
    from evalyn.ui.server import serve

    calls = _stub_the_server(monkeypatch)
    # A real port, not 0: with `--port 0` the browser is skipped anyway (the
    # assigned port is not known until uvicorn logs it), so port 0 would make
    # the `--no-open` assertion below pass for the wrong reason.
    serve(runs_dir=runs_dir, packs=[], port=8765, open_browser=False)

    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8765
    assert "opened" not in calls, "--no-open must not launch a browser"


def test_serve_opens_the_browser_when_it_was_not_told_not_to(runs_dir, monkeypatch):
    """The other half of the pair — otherwise `--no-open` would be satisfied by
    a build that never opens a browser at all."""
    from evalyn.ui.server import serve

    calls = _stub_the_server(monkeypatch)
    serve(runs_dir=runs_dir, packs=[], port=8765)
    assert calls["opened"] == "http://127.0.0.1:8765/"


# --------------------------------------------------------------------------
# 6. C-T6/7 — which `run_id` the cockpit keys by. It is the artifact stem.
# --------------------------------------------------------------------------

def test_the_cockpit_keys_runs_by_the_indexed_id_which_keeps_the_mode_suffix(
        runs_dir):
    """`run_id` in the *engine* excludes the mode suffix; the id the cockpit
    indexes, routes and keys sidecars by **includes** it. One of the two had to
    win before the events emitter lands, and the artifact stem wins because it
    is the only one that round-trips to a file on disk."""
    from evalyn.ui.paths import sidecar_dir

    index = _app(runs_dir).state.index
    assert index.artifact_path(COMPARE_ID) is not None
    assert index.artifact_path(COMPARE_ID.removesuffix("-compare")) is None
    assert index.artifact_path(DISCOVER_ID) is not None
    # ...and the sidecar directory is keyed by that same string.
    assert sidecar_dir(runs_dir, COMPARE_ID).name == COMPARE_ID


# --------------------------------------------------------------------------
# 7. The CLI command
# --------------------------------------------------------------------------

def test_the_ui_command_refuses_when_the_extra_is_not_installed(monkeypatch):
    """Tested by monkeypatching the import, not with a `skipif` marker: the
    marker would never fire, because `inspect_ai` already pulls fastapi in and
    the refusal branch would ship untested."""
    from tests.cli_runner import CliRunner

    from evalyn.cli import app

    monkeypatch.setitem(sys.modules, "evalyn.ui.server", None)
    result = CliRunner().invoke(app, ["ui"])

    assert result.exit_code == 2
    assert "evalyn ui: setup error: the UI extra is not installed." in result.output
    assert "pip install 'evalyn[ui]'" in result.output


def test_the_ui_command_passes_its_flags_through_to_serve(runs_dir, tmp_path,
                                                          monkeypatch):
    from tests.cli_runner import CliRunner

    from evalyn.cli import app
    from evalyn.ui import server as server_module

    pack = _pack_with_a_secret(tmp_path / "pack")
    seen: dict = {}
    monkeypatch.setattr(server_module, "serve", lambda **kw: seen.update(kw))

    result = CliRunner().invoke(app, [
        "ui", "--port", "9999", "--runs-dir", str(runs_dir),
        "--target", str(pack), "--allow-discover", "--no-open",
        "--judge-model", "fake-provider/not-a-real-judge",
    ])

    assert result.exit_code == 0, result.output
    assert seen["port"] == 9999
    assert Path(seen["runs_dir"]) == runs_dir
    assert [Path(p) for p in seen["packs"]] == [pack]
    assert seen["allow_discover"] is True
    assert seen["open_browser"] is False
    assert seen["judge_model"] == "fake-provider/not-a-real-judge"


def test_the_ui_command_leaves_the_judge_unset_unless_it_is_asked_for(
        runs_dir, tmp_path, monkeypatch):
    """T-A1's free path, at the flag.

    Unset must reach `serve` as `None`, because `None` is what makes the
    launcher omit `--judge-model` from the child's argv and leaves it on the
    CLI's own `mockllm/model` — the judge that costs nothing and the only
    reason this cockpit can be exercised end to end without a bill. A default
    of any real provider here would bill on every debugging launch.
    """
    from tests.cli_runner import CliRunner

    from evalyn.cli import app
    from evalyn.ui import server as server_module

    seen: dict = {}
    monkeypatch.setattr(server_module, "serve", lambda **kw: seen.update(kw))

    result = CliRunner().invoke(app, [
        "ui", "--runs-dir", str(runs_dir), "--no-open",
    ])

    assert result.exit_code == 0, result.output
    assert seen["judge_model"] is None


def test_the_ui_command_reports_an_unloadable_pack_as_a_setup_error(
        runs_dir, tmp_path, monkeypatch):
    """The refusal is a sentence an operator reads, not a traceback."""
    from tests.cli_runner import CliRunner

    from evalyn.cli import app

    # Same reason as `_stub_the_server`: unstubbed, this test passes only
    # because the refusal happens before `uvicorn.run`, and a build that failed
    # open would bind port 8765 and hang the suite instead of failing it.
    _stub_the_server(monkeypatch)
    result = CliRunner().invoke(app, [
        "ui", "--runs-dir", str(runs_dir),
        "--target", str(tmp_path / "not-a-pack"), "--no-open",
    ])

    assert result.exit_code == 2
    assert "evalyn ui: setup error:" in result.output
    assert "Traceback" not in result.output


def test_the_ui_help_lists_every_flag_the_plan_promised():
    from tests.cli_runner import CliRunner

    from evalyn.cli import app

    out = CliRunner().invoke(app, ["ui", "--help"]).output
    for flag in ("--port", "--runs-dir", "--target", "--allow-discover",
                 "--no-open", "--judge-model"):
        assert flag in out, out


# --------------------------------------------------------------------------
# 8. The server module itself
# --------------------------------------------------------------------------

def test_importing_the_server_is_the_only_thing_that_imports_the_run_index():
    """C-T7b. `evalyn.ui.index` pulls starlette transitively through
    `engine.run -> inspect_ai`, and the subprocess guard in `tests/test_smoke.py`
    pins that `import evalyn.cli` loads no web framework. That holds only
    because nothing imports `index` at module scope on the CLI's path — so
    `server.py` reaches for it inside `create_app`, not at the top of the file.
    """
    import subprocess

    probe = ("import evalyn.ui.server, sys, json;"
             "print(json.dumps('evalyn.ui.index' in sys.modules))")
    done = subprocess.run([sys.executable, "-c", probe], check=True,
                          capture_output=True, text=True)
    assert json.loads(done.stdout) is False, done.stdout
