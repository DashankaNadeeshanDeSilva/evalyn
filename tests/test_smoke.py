import subprocess
import sys
import tomllib
from pathlib import Path

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
    assert "gate" in out.stdout
