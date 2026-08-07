"""Emission — a confirmed finding becomes a reproducible `gate` probe.

This is the flywheel's output end, and it is deliberately boring: deterministic,
stdlib-only, no model call, no network. Four properties are load-bearing.

**1. ONE definition of the candidate.** `candidate_probe` builds both the probe
handed to the trust boundary (`Confirmer.confirm`) and the probe staged on disk.
If those were two functions they could silently diverge — the pack would gain a
regression probe that is not the thing the scorers actually confirmed, which is
exactly what the trust boundary exists to prevent. `loop.py` imports this one.

**2. Outcome-graded by construction.** `_assert_outcome_graded` runs *inside*
`candidate_probe`, so there is no call site to forget. A probe must assert the
violation *class* — an invariant id, a rubric id, or a needle the agent quoted
verbatim — never the path that produced it. `type: contains` is refused
outright: "the reply still contains X" pins today's wording, and model drift
would turn it into a false alarm in a month. The assertion **fails closed**: a
value it cannot show to be verbatim is rejected rather than waved through, and
`loop.py` turns the `ValueError` into a rejected proposal, not a dead session.

**3. The id is content-addressed.** `discovered-<objective>-<sha8>` over the
objective, the slots and the turns: the same finding rediscovered next week gets
the same id and the same filename, so re-running `discover` cannot silt the
staging directory up with near-identical files.

**4. Staging is inert and atomic.** Files land in `<pack>/discoveries/`, which
`load_pack` does not glob (it reads `probes/*.yaml` non-recursively) — adoption
is a human moving a file, never a side effect of a run. The write is
temp-then-`os.replace` so a crash mid-write cannot leave a half-probe that a
later `load_prior_discoveries` would choke on.

The provenance header is comments only, and every provenance key AND value is
treated as hostile: it is agent-influenced text, and a single character PyYAML
ends a comment at — LF, CR, NUL, NEL (U+0085), LS (U+2028) or PS (U+2029) —
would otherwise emit a non-comment line and let agent text prepend an entry to
the staged list.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import warnings
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import yaml
from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageUser

from evalyn.discovery.objectives import Objective
from evalyn.targets.loader import Pack
from evalyn.targets.schema import Check, Probe

#: Where staged discoveries live, relative to the pack root. NOT `probes/` —
#: `load_pack` must not pick these up (see the module docstring).
STAGING_DIRNAME = "discoveries"

#: A probe id that is safe to use as a FILENAME and to interpolate raw into the
#: staged header. Code-built ids (`discovered-<slug>-<sha8>`) always match; the
#: guard exists because `stage_probe` is a public function reached with a `Probe`
#: whose id is a free-form string, and both uses are unescaped: `/`, `..` or a
#: `\n` would write outside the staging dir or break out of the comment header.
_SAFE_PROBE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

#: Longest provenance value written into the header, in characters. Turn
#: excerpts and slot values are agent-authored and unbounded; a header is for
#: humans, and the full structured record rides in the run artifact.
_MAX_PROVENANCE_CHARS = 300

#: Everything PyYAML treats as the end of a comment: LF, CR, NUL, NEL, LS, PS.
#: (NUL arrives via the C0 sweep below, which runs first.)
_YAML_BREAKS = re.compile("[\n\r\x85\u2028\u2029]")

#: The COMPLEMENT of PyYAML's printable set — anything the YAML reader rejects.
#: Wider than C0+DEL (R8-4): it also sweeps the C1 block (U+0080-U+009F), lone
#: surrogates (U+D800-U+DFFF) and U+FFFE/U+FFFF. Provenance carries
#: agent-influenced text; a single such character otherwise makes the staged
#: file unparseable (PyYAML rejects it, `load_prior_discoveries` warn-skips the
#: whole file, the discovery drops from the dedup corpus) — and a lone surrogate
#: crashes `stage_probe`'s `Path.write_text` outright with UnicodeEncodeError.
#: Applied AFTER the break split, so the break chars above split first.
_NON_PRINTABLE = re.compile(
    "[^\x09\x20-\x7e\x85\xa0-퟿-�\U00010000-\U0010ffff]")


# --------------------------------------------------------------------------
# transcript -> turns
# --------------------------------------------------------------------------

def answered_user_turns(transcript: Sequence[ChatMessage]) -> list[str]:
    """The user turns the target actually answered, in order.

    `TargetSession` appends the user message *before* the HTTP call, so a
    transient send failure (502, read timeout) leaves an **unanswered** user
    turn in `session.messages`. Replaying that turn would put a message into
    the conversation the target never saw a reply to — a different conversation
    from the one that produced the finding.

    Pair-wise walk: a user turn counts only once a later assistant turn answers
    it; an earlier still-pending turn is dropped when a new user turn arrives,
    and a trailing unanswered turn is dropped too.

    This is **replay fidelity only** — it cannot change a confirmation verdict,
    because the `Confirmer` scores the transcript, not `probe.turns`.
    """
    turns: list[str] = []
    pending: str | None = None
    for message in transcript:
        if isinstance(message, ChatMessageUser):
            pending = message.text     # a previous unanswered turn is dropped
        elif isinstance(message, ChatMessageAssistant) and pending is not None:
            turns.append(pending)
            pending = None
    return turns


# --------------------------------------------------------------------------
# the candidate probe — the ONE definition
# --------------------------------------------------------------------------

def _check_problem(check: Check, quoted: frozenset[str]) -> str | None:
    """Why this check is not outcome-graded, or None if it is."""
    if check.type == "contains":
        return ("type 'contains' grades the path (today's wording), not the "
                "violation class — model drift would make it a false alarm")
    if check.type == "classifier":
        return ("type 'classifier' grades a judge's opinion of the reply, not "
                "a violation class")
    if check.type == "invariant":
        if not (check.ref or "").strip():
            return "type 'invariant' with no `ref` — there is no invariant to assert"
        return None
    if check.type == "rubric":
        if not (check.rubric or "").strip():
            return "type 'rubric' with no `rubric` id — nothing to judge against"
        return None
    # not_contains: the needle must be evidence the agent quoted verbatim.
    if check.values is not None:
        return ("`values` cannot be shown verbatim — a not_contains check "
                "carries a single quoted `value`")
    value = (check.value or "").strip()
    if not value:
        return "type 'not_contains' with an empty `value` would match every reply"
    if value not in quoted:
        return (f"value {value!r} is not a verbatim slot value the agent quoted "
                f"— unverifiable, so refused")
    return None


def _assert_outcome_graded(probe: Probe, *,
                           slot_values: Sequence[str] = ()) -> None:
    """Raise `ValueError` unless every check asserts a violation class.

    Allowed, per spec §7: a pattern-class **invariant** ref, a **rubric** id, or
    a **verbatim** slot value the agent quoted (a `not_contains` needle). Pass
    `slot_values` so "verbatim" is checkable — with none supplied, a needle
    cannot be shown to be quoted and is refused (fail closed).
    """
    quoted = frozenset(v.strip() for v in slot_values if v and v.strip())
    problems = [f"check[{i}]: {why}"
                for i, c in enumerate(probe.checks)
                if (why := _check_problem(c, quoted)) is not None]
    if problems:
        raise ValueError(
            f"probe {probe.id!r} is not outcome-graded: {'; '.join(problems)}")


def _probe_id(objective: Objective, slots: Mapping[str, str],
              turns: Sequence[str]) -> str:
    """`discovered-<objective>-<sha8>` — content-addressed, not step-indexed.

    Same finding (same objective, slots and path) → same id → the same staged
    filename, so a rediscovery overwrites rather than accumulates.
    """
    canonical = json.dumps(
        [objective.id, sorted((str(k), str(v)) for k, v in slots.items()),
         [str(t) for t in turns]],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    return f"discovered-{objective.id}-{digest}"


def candidate_probe(objective: Objective, slots: Mapping[str, str],
                    turns: Sequence[str], *,
                    reference_hint: str | None = None) -> Probe:
    """Build the probe for a proposed finding — the ONE definition.

    Used for both the candidate handed to `Confirmer.confirm` and the probe
    staged on disk, so what was confirmed and what a human adopts cannot drift.

    Raises `ValueError` if the objective's checks are not outcome-graded, or if
    the slots are unusable (the objective's own check factory raises).
    """
    probe = Probe(
        id=_probe_id(objective, slots, turns),
        category=objective.category,
        kind="regression",
        safety_critical=objective.safety_critical,
        turns=[str(t) for t in turns],
        checks=objective.confirm_checks(slots),
        # Safety-critical probes gate on pass^k — one lucky sample is not
        # evidence the leak is gone.
        samples=3 if objective.safety_critical else 1,
        # Never invented: the caller's hint, else the objective's, else nothing.
        reference=reference_hint or getattr(objective, "reference_hint", None))
    _assert_outcome_graded(probe, slot_values=list(slots.values()))
    return probe


# --------------------------------------------------------------------------
# YAML + staging
# --------------------------------------------------------------------------

def _comment_safe_lines(text: str) -> list[str]:
    """Split on every character PyYAML ends a comment at, C0 controls dropped.

    Not just LF: a YAML comment also ends at CR, NUL, NEL (U+0085), LS (U+2028)
    and PS (U+2029). `splitlines`-shaped sanitizing misses the last three, and
    one of them is enough for agent text to break out of the header and prepend
    an entry to the staged list.
    """
    segments = _YAML_BREAKS.split(text.replace("\r\n", "\n"))
    return [_NON_PRINTABLE.sub(" ", seg) for seg in segments]


def _comment_lines(key: object, value: object) -> list[str]:
    """`# key: value`, safe for text containing line breaks or `#`.

    Provenance carries agent-influenced text (slot values, turn excerpts), so
    BOTH halves are normalized: the key collapses to one line, the value keeps
    its line structure with every continuation line re-prefixed `#`.
    """
    text = str(value)
    if len(text) > _MAX_PROVENANCE_CHARS:
        text = text[:_MAX_PROVENANCE_CHARS] + " ..."
    safe_key = " ".join(p for p in _comment_safe_lines(str(key)) if p.strip())
    head, *rest = _comment_safe_lines(text)
    lines = [f"# {safe_key}: {head}"]
    lines += [f"#     {ln}" for ln in rest if ln.strip()]
    return [ln.rstrip() for ln in lines]


def probe_yaml(probe: Probe, *, provenance: dict) -> str:
    """The staged file: provenance header comments over a one-entry YAML list.

    The list shape matches `<pack>/probes/*.yaml`, so adopting a discovery is a
    `git mv` and nothing else. The replay verdict is deliberately absent —
    staging happens before replay; it rides in the run artifact instead.
    """
    header = [
        "# Discovered by Evalyn `discover` — STAGED, not adopted.",
        f"# Move this file to ../probes/{probe.id}.yaml to adopt it as a gate probe.",
        "# CAUTION: this file may contain LIVE DATA captured from the target — a",
        "#   leaked value (an email address, a phone number, an internal path) is",
        "#   embedded VERBATIM as a check value, because redacting it would break",
        "#   the outcome-graded confirmation the check exists to make.",
        # Scoped, not absolute. The old wording asserted flatly that this file
        # IS gitignored — a claim `--staging-dir` can falsify by pointing at a
        # tracked directory, and one a single `*` in the ignore pattern already
        # failed for nested packs. Claim only what the repo delivers, and name
        # the command that settles it.
        "#   REVIEW BEFORE COMMITTING OR SHARING. A `discoveries/` staging dir in",
        "#   Evalyn's own repo is gitignored (`**/discoveries/*.yaml`); a",
        "#   --staging-dir elsewhere, another repo, or moving this file out of",
        "#   staging is NOT covered. Settle it with `git check-ignore -v <file>`.",
    ]
    for key, value in provenance.items():
        header.extend(_comment_lines(str(key), value))
    body = yaml.safe_dump([probe.model_dump(exclude_none=True)], sort_keys=False,
                          allow_unicode=True, default_flow_style=False)
    return "\n".join(header) + "\n" + body


@lru_cache(maxsize=64)
def _git_exposed(directory: str) -> bool:
    """True when `directory` is inside a git work tree AND not gitignored.

    That conjunction is the whole point. The risk this guards is *accidentally
    committing live target data*, so a directory git does not track at all
    (`/tmp`, an operator's scratch dir) carries no risk and must stay silent —
    warning there would be noise on the common path. Any uncertainty (no git on
    PATH, a slow or erroring invocation) resolves to False for the same reason:
    an unprovable exposure is not an exposure, and this must never be able to
    fail a staging write that already succeeded.

    Cached per directory: one hunt stages many probes into the same dir, and
    `git check-ignore` is a subprocess.
    """
    try:
        inside = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5, check=False)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return False
        # A directory, not a file: `check-ignore` matches `**/discoveries/*.yaml`
        # against a concrete path, so ask about a representative staged file.
        probe_path = str(Path(directory) / "probe.yaml")
        ignored = subprocess.run(
            ["git", "-C", directory, "check-ignore", "-q", probe_path],
            capture_output=True, timeout=5, check=False)
        return ignored.returncode != 0
    except (OSError, subprocess.SubprocessError):
        return False


def stage_probe(pack: Pack, probe: Probe, yaml_text: str, *,
                staging_dir: Path | None = None) -> Path:
    """Write the probe under `<pack>/discoveries/` and return its path.

    Atomic: a temp file in the *same* directory (so `os.replace` is a rename,
    not a cross-device copy) is swapped into place. A reader never sees a
    partial probe. The temp name is unique per call, so two concurrent sessions
    that confirm the *same* finding cannot clobber each other mid-write.

    The id is validated first (`_SAFE_PROBE_ID`) because it is used unescaped
    twice — as this filename, and interpolated raw into the header `probe_yaml`
    built. Unreachable for a `candidate_probe` id, and it stays that way: the
    check fails closed BEFORE any file exists, so a hand-built probe with a
    traversing or newline-bearing id writes nothing at all.
    """
    if not _SAFE_PROBE_ID.fullmatch(probe.id or ""):
        raise ValueError(
            f"probe id {probe.id!r} is not safe to stage: a staged probe's id "
            f"becomes its filename and is written into its header, so it must "
            f"match {_SAFE_PROBE_ID.pattern}")
    directory = Path(staging_dir) if staging_dir is not None \
        else pack.root / STAGING_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{probe.id}.yaml"
    tmp = directory / f".{probe.id}.{os.getpid()}.{uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(yaml_text, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    # AFTER the write, never instead of it: the file exists either way, and the
    # operator's problem is that it exists somewhere committable. `--staging-dir`
    # is a first-class flag and `--staging-dir <pack>/probes` stages verbatim
    # leaked PII into a TRACKED directory — the header's caution is no guard if
    # nobody reads it before `git add`.
    if _git_exposed(str(directory.resolve())):
        warnings.warn(
            f"staged discovery {path} is NOT gitignored and sits inside a git "
            f"work tree — this file embeds LIVE DATA captured from the target "
            f"(a leaked path, email or phone number, verbatim, as a check "
            f"value). Do not `git add` it: stage into a `discoveries/` "
            f"directory, or add this path to .gitignore",
            RuntimeWarning, stacklevel=2)
    return path


def load_prior_discoveries(staging_dir: Path) -> list[Probe]:
    """Every probe already staged in `staging_dir` — the dedup corpus.

    Lives here rather than in `dedup.py` because it is the read side of
    `stage_probe`; `dedup.py` stays a pure comparison with no file access.

    A file that will not parse is **warned about and skipped**, never fatal: a
    hand-edited or half-written staged file must not stop a run from recording
    the finding it just made. A missing directory is simply "no priors yet".
    """
    directory = Path(staging_dir)
    if not directory.is_dir():
        return []
    probes: list[Probe] = []
    for path in sorted({*directory.glob("*.yaml"), *directory.glob("*.yml")}):
        try:
            entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            # Validate the whole file before keeping any of it: a file that is
            # half-valid is skipped whole, not partially adopted.
            parsed = [Probe.model_validate(e) for e in entries]
        except Exception as e:  # noqa: BLE001 — any unreadable file is skippable
            warnings.warn(
                f"skipping unreadable staged discovery {path.name!r} "
                f"({type(e).__name__}: {e})", RuntimeWarning, stacklevel=2)
        else:
            probes.extend(parsed)
    return probes
