"""The cockpit's ASGI app and its one entry point (Plan #4, Task 6).

**This is the only module in the package that may import FastAPI.**
`evalyn/ui/__init__.py` is empty and `evalyn/cli.py` imports `serve` inside the
`ui` command body, so `import evalyn.cli` still loads no web framework and
`evalyn gate` still runs on a machine that never installed the `[ui]` extra. A
subprocess guard in `tests/test_smoke.py` pins that; it is a subprocess because
an in-process check is worthless the moment another test imports this file.

`evalyn.ui.index` is imported **inside** `create_app` for a second, sharper
reason (C-T7b): it reaches `inspect_ai` through `engine.run`, which drags
starlette in transitively. Importing it at module scope here would be invisible
today and would break the guard the moment anything on the CLI's path touched
this module.

Three properties this factory exists to establish:

* **Redaction is mounted, not merely available.** Task 4 built the chokepoint;
  it protects nothing until an app installs it, and installing
  `route_class=RedactingRoute` alone is **not sufficient**. `HTTPException` and
  every registered handler are rendered by Starlette's `ExceptionMiddleware`,
  which sits *above* the route and never passes through the route class — so
  `redacting_exception_handlers()` goes on as well. Error bodies are precisely
  the ones carrying the operator's run directory under `$HOME`.
* **Every non-2xx body is `ErrorEnvelope`.** The SPA reads `error.code` and has
  no second parser, so an unknown `/api` path must not come back as FastAPI's
  `{"detail": …}`. That is what the explicit `/api` catch-all below is for: it
  turns "no route matched" into a 404 the handlers can shape, instead of
  letting the SPA's history fallback answer for the API.
* **Loopback only.** This server reads `runs/` and (Task 19) launches
  processes. `--host 0.0.0.0` on conference wifi is not a configuration.

**Which `run_id` (C-T6/7).** The engine's `run_id` excludes the mode suffix
(`runs/<run_id><suffix>.json`); the id this cockpit indexes, routes and keys
sidecars by is the **artifact stem, suffix included** — `<id>-compare`,
`<id>-discover`. `RunIndex` already derives it that way from `path.stem`, and
`RunIndex._sidecar` joins that same string onto `runs/.evalyn-ui/`, so the
launcher must write `meta.json` under the suffixed id too. One of the two
readings had to win before the events emitter lands; the stem wins because it
is the only one that round-trips to a file on disk.
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

import evalyn
from evalyn.targets.loader import load_pack
from evalyn.ui.models import HealthResponse, MetaResponse, RedactionMeta, display_path
from evalyn.ui.redact import Redactor, RedactingRoute, no_redact, redacting_exception_handlers

if TYPE_CHECKING:                       # pragma: no cover - typing only
    from fastapi import FastAPI

__all__ = ["create_app", "serve", "build_redactor", "STATIC_DIR", "INDEX_HTML",
           "DEFAULT_PORT", "LOOPBACK_HOST"]

#: The committed Vite bundle, shipped inside the wheel by hatchling.
STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"
ASSETS_DIR = STATIC_DIR / "assets"

#: Matches the dev proxy target in `ui/vite.config.ts`. Changing one without
#: the other silently breaks `npm run dev` against a real server.
DEFAULT_PORT = 8765

#: Not a default — the only accepted value. See `serve`.
LOOPBACK_HOST = "127.0.0.1"

_API_PREFIX = "/api"


def build_redactor(packs: list[Path]) -> Redactor:
    """The app's redactor, taught by the packs the run is allowed to touch.

    Only `not_contains` values are harvested, and that asymmetry is deliberate
    (ruling R4-18, implemented in `harvest_from_probes`): a `not_contains` value
    is a string the product must never emit — a secret the pack itself has
    already identified — while a `contains` value is the *correct answer*, and
    harvesting those would blank the passing transcripts out of the demo.

    **A pack that will not load is fatal.** Continuing would start a server
    whose redactor is missing exactly the literals that pack declared secret,
    and a redaction hole that announces itself as a warning nobody reads is
    worse than a refusal. `load_pack`'s `PackError` / `AllowlistError`
    propagates to the CLI, which prints it as a setup error.
    """
    redactor = Redactor()
    for pack_path in packs:
        redactor.harvest_from_probes(load_pack(pack_path).probes)
    return redactor


def create_app(runs_dir: Path, packs: list[Path], *,
               allow_discover: bool = False) -> FastAPI:
    """Build the cockpit app over one `runs/` directory and one pack allowlist.

    `allow_discover` is a *start-time* decision, not a request-time one: the
    launcher (Task 19) refuses a `discover` request unless the operator asked
    for it on the command line, because discover spends real money.
    """
    from fastapi import APIRouter, FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from starlette.staticfiles import StaticFiles

    # Imported HERE, not at module scope: `index` pulls starlette in through
    # `engine.run -> inspect_ai`, and the CLI's import-isolation guard holds
    # only while nothing on that path imports it eagerly (C-T7b).
    from evalyn.ui.index import RunIndex

    runs_dir = Path(runs_dir).resolve()
    packs = [Path(p).resolve() for p in packs]

    app = FastAPI(title="Evalyn cockpit", version=evalyn.__version__)

    # Every route this factory adds directly to the app inherits the chokepoint
    # too, not just the ones on the `/api` router. Belt and braces: the escape
    # hatch should be the explicit `@no_redact` marker and nothing else.
    app.router.route_class = RedactingRoute

    app.state.runs_dir = runs_dir
    app.state.packs = packs
    app.state.allow_discover = allow_discover
    app.state.redactor = build_redactor(packs)
    # Keyed by the artifact stem — see the module docstring (C-T6/7). When Task
    # 19 starts minting ids, note that an explicit `EVALYN_RUN_ID` removes the
    # collision-proofing `new_run_id` provides: two runs handed the same id
    # `os.replace`-clobber each other with no exists-check (C-T7).
    app.state.index = RunIndex(runs_dir)

    # C-T6b: the second gate. `RedactingRoute` wraps the endpoint call only, so
    # without these the 404 body reading "no such run at /Users/alice/…" goes
    # out verbatim — the single most likely string on a projector when a live
    # demo goes wrong.
    for exc_class, handler in redacting_exception_handlers().items():
        app.add_exception_handler(exc_class, handler)

    api = APIRouter(prefix=_API_PREFIX, route_class=RedactingRoute)

    # `api_route(methods=["GET", "HEAD"])` rather than `@api.get`: FastAPI's
    # `get` does NOT add HEAD the way Starlette's bare `Route` does, and
    # `curl -I` is the "is it up" check somebody runs mid-demo.
    @api.api_route("/meta", methods=["GET", "HEAD"], response_model=MetaResponse)
    @no_redact
    async def meta() -> MetaResponse:
        """One of exactly two redaction-exempt routes. Exempt, not unexamined:
        `MetaResponse` makes its own filesystem fields display-safe at
        validation time (R4-14), which is why the raw `runs_dir` goes in here."""
        return MetaResponse(
            version=evalyn.__version__,
            runs_dir=str(runs_dir),
            packs=[str(p) for p in packs],
            allow_discover=allow_discover,
            redaction=RedactionMeta(),
        )

    @api.api_route("/health", methods=["GET", "HEAD"],
                   response_model=HealthResponse)
    @no_redact
    async def health() -> HealthResponse:
        """The other exempt route. Carries no run content at all."""
        return HealthResponse(ok=True, version=evalyn.__version__)

    app.include_router(api)

    # Registered AFTER the router, so a route a later task adds to `api` is
    # matched first and this only ever answers for paths that genuinely do not
    # exist. Without it an unknown `/api/...` would fall through to the SPA
    # history fallback below and a client would get HTML, or a 405, instead of
    # an envelope.
    #
    # HEAD and OPTIONS are in the list for the same reason every other method
    # is: a 405 on an unknown path tells a prober the path exists, which is the
    # signal this route exists to suppress. Answering 404 for all of them says
    # nothing either way.
    @app.api_route("/api/{unmatched:path}", include_in_schema=False,
                   methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH",
                            "DELETE"])
    async def api_not_found(unmatched: str):
        # `unmatched` is deliberately NOT echoed: reflecting a client-supplied
        # path into a body is a needless gift to anyone probing the server.
        raise HTTPException(status_code=404, detail="no such API endpoint")

    if ASSETS_DIR.is_dir():
        # Mounted before the catch-all so the hashed bundle wins. `index.html`
        # references these as `./assets/...` (vite `base: "./"`).
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

    @app.api_route("/{spa_path:path}", methods=["GET", "HEAD"],
                   include_in_schema=False)
    async def spa(spa_path: str):
        """The SPA's history fallback — `BrowserRouter` owns `/runs/<id>`.

        Without it every deep link and every browser refresh is a 404, which is
        the difference between a cockpit and a demo nobody may click in.
        """
        if spa_path == "api" or spa_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="no such API endpoint")
        if not INDEX_HTML.is_file():
            raise HTTPException(
                status_code=500,
                detail="the cockpit bundle is missing from this install")
        # `no-cache` so a rebuilt bundle is picked up on reload; the hashed
        # assets under /assets are immutable and may be cached by the browser.
        return FileResponse(INDEX_HTML, media_type="text/html",
                            headers={"cache-control": "no-cache"})

    return app


def serve(*, runs_dir: Path, packs: list[Path], port: int = DEFAULT_PORT,
          host: str = LOOPBACK_HOST, allow_discover: bool = False,
          open_browser: bool = True) -> None:
    """Build the app and serve it on loopback until interrupted.

    `host` exists to be **refused**. It is a parameter rather than a constant so
    that the refusal is a testable behaviour instead of an absence, and there is
    deliberately no CLI flag feeding it: this server reads an operator's `runs/`
    directory and will grow the ability to launch evals, so binding it to
    anything reachable from the network hands both to the room.
    """
    if host != LOOPBACK_HOST:
        raise ValueError(
            f"evalyn ui binds {LOOPBACK_HOST} only; refusing host {host!r} — the "
            f"cockpit reads your runs directory and launches evals, and neither "
            f"belongs on a network interface")

    app = create_app(Path(runs_dir), [Path(p) for p in packs],
                     allow_discover=allow_discover)

    url = f"http://{host}:{port}/"
    print(f"evalyn ui: serving {display_path(str(Path(runs_dir).resolve()))} "
          f"at {url} — redaction is on", file=sys.stderr)

    # Opened before the bind, not after: uvicorn.run() does not return until the
    # server stops, and the browser takes far longer to start than the socket
    # does. Skipped for `--port 0`, where the real port is not known until
    # uvicorn logs it.
    if open_browser and port:
        webbrowser.open(url)

    import uvicorn

    uvicorn.run(app, host=host, port=port)
