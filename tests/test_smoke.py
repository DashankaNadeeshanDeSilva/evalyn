import json
import subprocess
import sys
from pathlib import Path

try:                                    # stdlib on 3.11+; the package declares >=3.10
    import tomllib
except ModuleNotFoundError:             # pragma: no cover - only on 3.10
    import tomli as tomllib             # type: ignore[no-redef]

from tests.cli_runner import strip_ansi

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

def test_version_importable():
    import evalyn
    assert evalyn.__version__

def test_version_matches_pyproject():
    """`__version__` and `pyproject.toml` must be bumped together.

    Plan #2b bumped `pyproject.toml` to 0.3.0 and left `__init__.py` at 0.2.0;
    the truthiness assertion above could not see it. Read the repo file with
    `tomllib` — NOT `importlib.metadata`, which reports the installed dist-info
    and goes stale between a bump and the next `uv sync`.
    """
    import evalyn
    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert evalyn.__version__ == declared, (
        f"evalyn.__version__ = {evalyn.__version__!r} but pyproject.toml declares "
        f"{declared!r} — bump both.")

def test_importing_the_cli_loads_no_web_framework():
    """`evalyn ui` must not cost `evalyn gate` a FastAPI import (Plan #4, T6).

    The `ui` command imports `evalyn.ui.server` **inside its body**, and that
    module is the only one in the package allowed to touch fastapi. Move the
    import to the top of `cli.py` and every CLI invocation — in CI, in a
    container, on a machine without the `[ui]` extra — pays for a web framework
    or dies with an `ImportError` from three modules away.

    A subprocess, because this interpreter has already imported everything:
    in-process the assertion is worthless the moment another test touches the
    server. `tests/ui/test_index.py` carries the same probe, but that module is
    `pytest.mark.ui` and disappears under `-m "not ui"` — which is precisely the
    run where a base install would be exercised, so the guard lives here too.
    """
    probe = ("import evalyn.cli, sys, json;"
             "print(json.dumps(sorted({name.split('.')[0] for name in sys.modules}"
             " & {'fastapi', 'starlette', 'uvicorn'})))")
    done = subprocess.run([sys.executable, "-c", probe], check=True,
                          capture_output=True, text=True)
    assert json.loads(done.stdout) == [], done.stdout


def test_cli_help_runs():
    out = subprocess.run([sys.executable, "-m", "evalyn.cli", "--help"],
                         capture_output=True, text=True)
    assert out.returncode == 0
    # Rich colours the help panel whenever FORCE_COLOR/GITHUB_ACTIONS is set, even
    # into a pipe — strip escapes so the assertion sees the text a user reads.
    assert "gate" in strip_ansi(out.stdout)
