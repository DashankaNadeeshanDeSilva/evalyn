"""`python -m evalyn` — the entry point the cockpit's launcher spawns.

`pyproject.toml` declares a console script (`evalyn = "evalyn.cli:app"`), and
that is still the form a human types. It is the wrong form for the launcher:
finding `evalyn` on `PATH` requires the venv's scripts directory to be on it,
which is true when an operator activated the venv and false when the server was
started any other way — by an IDE, by `uv run`, by a supervisor. `sys.executable`
is guaranteed to be the interpreter already running the server, so
`sys.executable -m evalyn` resolves without depending on how the server was
launched.

The two forms must stay the *same* CLI. `app` is imported from `evalyn.cli`
rather than redefined here, so a command added to one is a command added to
both; `tests/ui/test_launcher.py` spawns this module for real and checks that
`gate --help` answers through it.
"""
from evalyn.cli import app

if __name__ == "__main__":
    app()
