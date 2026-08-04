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
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n(.*)\n?```\s*$", re.DOTALL)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_rubric_context(pack, rubric_id: str) -> str | None:
    """Optional judge context: a sibling `<rubric_id>.facts.md` fact sheet."""
    path = Path(pack.root) / "rubrics" / f"{rubric_id}.facts.md"
    return path.read_text() if path.exists() else None


def parse_steps_file(path: Path) -> list[str]:
    """Parse a frozen grading-steps artifact; raise ValueError if malformed.

    The contract (also enforced by validate-pack): valid JSON, a non-empty
    list of non-empty strings. Fail-closed — when present this file IS the
    judge's operative rubric, so a malformed one must never be judged with.
    """
    try:
        steps = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"steps file {path.name}: invalid JSON ({e})") from e
    if (not isinstance(steps, list) or not steps
            or not all(isinstance(s, str) and s.strip() for s in steps)):
        raise ValueError(
            f"steps file {path.name}: frozen grading steps must be a "
            f"non-empty JSON list of non-empty strings")
    return steps


def load_rubric_steps(pack, rubric_id: str) -> list[str] | None:
    """Optional frozen grading steps: a sibling `<rubric_id>.steps.json`.

    2026-07-31 remediation (calibration runs #1/#3): when this committed,
    human-reviewed artifact exists it IS the grading steps for the rubric —
    no runtime generation and no steps-cache read/write happen for it.
    None when absent; ValueError when present but malformed (fail-closed).
    """
    path = Path(pack.root) / "rubrics" / f"{rubric_id}.steps.json"
    return parse_steps_file(path) if path.exists() else None


def load_rubric(pack, rubric_id: str) -> tuple[str, str]:
    path = Path(pack.root) / "rubrics" / f"{rubric_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"rubric {rubric_id!r} not found at {path}")
    text = path.read_text()
    ctx = load_rubric_context(pack, rubric_id)
    # The hash COVERS the sibling artifacts because both change judge behavior:
    # editing facts or frozen steps stales calibration records, is_stale, and
    # cache keys exactly like a rubric edit. Deterministic concatenation order:
    #   text  [+ "\0" + facts]  [+ "\0steps\0" + raw steps-file text]
    # (facts keeps the pre-steps separator so facts-only rubrics hash exactly
    # as before; a rubric with neither file hashes as plain sha256(text), so
    # packs without these artifacts are unaffected).
    hashed = text
    if ctx is not None:
        hashed += "\0" + ctx
    steps_path = Path(pack.root) / "rubrics" / f"{rubric_id}.steps.json"
    if steps_path.exists():
        hashed += "\0steps\0" + steps_path.read_text()
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
                        cache_dir: Path | None, *,
                        usage_acc: dict[str, dict[str, int]] | None = None,
                        ) -> list[str]:
    """G-Eval phase 1: generate grading steps once per (rubric-hash x judge-model).

    ``usage_acc`` (optional, PR #6): a model-id -> {"input_tokens",
    "output_tokens"} dict the GENERATION path accumulates into, so callers
    that meter their own judge spend (judge_pair) can count a cache-miss
    generation call. Cache hits accumulate nothing; the default None keeps
    every existing caller byte-compatible.
    """
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
    if usage_acc is not None:  # meter the generation call (same shape/zeros
        #                        discipline as judge_pair's per-draw metering)
        acc = usage_acc.setdefault(getattr(out, "model", "") or judge_model,
                                   {"input_tokens": 0, "output_tokens": 0})
        u = getattr(out, "usage", None)
        if u is not None:
            acc["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            acc["output_tokens"] += getattr(u, "output_tokens", 0) or 0
    raw = out.completion.strip()
    fenced = _FENCE_RE.match(raw)  # a ```json fenced reply is ordinary, unwrap it
    if fenced:
        raw = fenced.group(1).strip()
    # FAIL LOUD on unparseable output (2026-07-31, calibration run #3 root
    # cause): the old silent fallback [rubric_text[:500]] was cached and judged
    # with — a truncated rubric with no band definitions. Refusing beats
    # judging with a corrupt instrument; nothing is ever cached on failure.
    try:
        parsed = json.loads(raw)
        if (not isinstance(parsed, list) or not parsed
                or not all(isinstance(s, str) and s.strip() for s in parsed)):
            raise ValueError("not a non-empty JSON array of non-empty strings")
        steps = list(parsed)
    except Exception as e:
        raise RuntimeError(
            f"judge model {judge_model!r} returned unparseable grading steps "
            f"for rubric {rubric_hash[:16]} ({e}); output started: "
            f"{out.completion.strip()[:200]!r}. Refusing to judge with a "
            f"degraded rubric — re-run, or commit human-reviewed steps as "
            f"rubrics/<rubric_id>.steps.json in the pack.") from e
    if cache_file is not None:
        # atomic write (temp file + os.replace): concurrent first-time samples
        # must never observe a partially written cache entry
        fd, tmp = tempfile.mkstemp(dir=cache_file.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(steps))
        os.replace(tmp, cache_file)
    return steps
