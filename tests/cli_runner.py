"""ANSI-tolerant ``CliRunner`` for the CLI tests.

Typer renders ``--help`` (and usage errors) through Rich, which emits ANSI colour
whenever it believes it is writing to a terminal — that includes GitHub Actions and
any environment with ``FORCE_COLOR`` set. Rich interleaves those escape sequences
*through* the option names in the help panel, so a plain
``assert "--target" in result.stdout`` fails in CI while passing locally, even though
the flag is genuinely there.

CLI test modules import ``CliRunner`` from here instead of from ``typer.testing``: it
behaves identically except that the captured output has ANSI escapes stripped, so
substring assertions match the text a user actually reads. Nothing else is relaxed —
absent text is still absent.
"""
from __future__ import annotations

import re
from typing import Any

from click.testing import Result
from typer.testing import CliRunner as _TyperCliRunner

# CSI sequences (colour/style/cursor), OSC strings, and the short two-character
# escapes — the forms Rich can put in a captured stream.
_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")

_OUTPUT_ATTRS = ("stdout_bytes", "stderr_bytes", "output_bytes")


def strip_ansi(text: str) -> str:
    """Return *text* with ANSI escape sequences removed."""
    return _ANSI_RE.sub("", text)


class CliRunner(_TyperCliRunner):
    """``typer.testing.CliRunner`` whose captured output is ANSI-free."""

    def invoke(self, *args: Any, **kwargs: Any) -> Result:
        result = super().invoke(*args, **kwargs)
        for attr in _OUTPUT_ATTRS:
            raw = getattr(result, attr, None)
            if isinstance(raw, bytes):
                clean = strip_ansi(raw.decode(self.charset, "replace"))
                setattr(result, attr, clean.encode(self.charset))
        return result
