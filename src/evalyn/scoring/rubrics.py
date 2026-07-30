from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from inspect_ai.model import get_model

_STEPS_PROMPT = """You are designing an evaluation rubric's grading procedure.
Given the rubric below, produce 3-6 concrete, checkable evaluation STEPS a grader
would follow to score a conversation on this rubric. When a step refers to a
rubric criterion, use the criterion's exact `##` heading name, verbatim — never
rename, retitle, or abbreviate it. Reply with ONLY a JSON array of short strings.

Rubric:
{rubric}
"""
# GOTCHA: the grading-steps cache key is (rubric_hash, judge_model) only — it
# does NOT cover this prompt template, so editing _STEPS_PROMPT silently
# reuses stale cached steps (JOURNAL open item; candidate: fold a
# prompt-template hash into the cache filename).

_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_rubric_context(pack, rubric_id: str) -> str | None:
    """Optional judge context: a sibling `<rubric_id>.facts.md` fact sheet."""
    path = Path(pack.root) / "rubrics" / f"{rubric_id}.facts.md"
    return path.read_text() if path.exists() else None


def load_rubric(pack, rubric_id: str) -> tuple[str, str]:
    path = Path(pack.root) / "rubrics" / f"{rubric_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"rubric {rubric_id!r} not found at {path}")
    text = path.read_text()
    ctx = load_rubric_context(pack, rubric_id)
    # The hash COVERS the fact sheet: editing facts stales calibration records,
    # is_stale, and the grading-steps cache exactly like a rubric edit.
    hashed = text if ctx is None else text + "\0" + ctx
    return text, _hash_text(hashed)


def parse_criteria(rubric_text: str) -> list[str]:
    """Named criteria of a rubric: its `## <name>` section headings, in order.

    Fallbacks for section-less rubrics: the `# <title>` H1 as a single
    criterion, else a single "overall" criterion.
    """
    names = _H2_RE.findall(rubric_text)
    if names:
        return names
    h1 = _H1_RE.search(rubric_text)
    return [h1.group(1)] if h1 else ["overall"]


async def grading_steps(rubric_text: str, rubric_hash: str, judge_model: str,
                        cache_dir: Path | None) -> list[str]:
    """G-Eval phase 1: generate grading steps once per (rubric-hash x judge-model)."""
    cache_file = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / (
            f"steps-{rubric_hash[:16]}-{_hash_text(judge_model)[:8]}.json")
        if cache_file.exists():
            return json.loads(cache_file.read_text())
    model = get_model(judge_model)
    out = await model.generate(_STEPS_PROMPT.format(rubric=rubric_text))
    try:
        steps = [str(s) for s in json.loads(out.completion.strip())]
    except Exception:
        steps = [rubric_text.strip()[:500]]  # fallback: score against raw rubric
    if cache_file is not None:
        # atomic write (temp file + os.replace): concurrent first-time samples
        # must never observe a partially written cache entry
        fd, tmp = tempfile.mkstemp(dir=cache_file.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(steps))
        os.replace(tmp, cache_file)
    return steps
