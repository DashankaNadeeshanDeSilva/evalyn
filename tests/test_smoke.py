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

def test_cli_help_runs():
    out = subprocess.run([sys.executable, "-m", "evalyn.cli", "--help"],
                         capture_output=True, text=True)
    assert out.returncode == 0
    # Rich colours the help panel whenever FORCE_COLOR/GITHUB_ACTIONS is set, even
    # into a pipe — strip escapes so the assertion sees the text a user reads.
    assert "gate" in strip_ansi(out.stdout)
