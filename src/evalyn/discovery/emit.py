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

The provenance header is comments only, and every provenance value is treated as
hostile: it is agent-influenced text, and one raw newline in it would otherwise
emit a non-comment line and corrupt the document.
"""
from __future__ import annotations

import hashlib
import json
import os
import warnings
from collections.abc import Mapping, Sequence
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

#: Longest provenance value written into the header, in characters. Turn
#: excerpts and slot values are agent-authored and unbounded; a header is for
#: humans, and the full structured record rides in the run artifact.
_MAX_PROVENANCE_CHARS = 300


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

def _comment_lines(key: str, value: object) -> list[str]:
    """`# key: value`, safe for a value that contains newlines or `#`.

    Provenance carries agent-influenced text (slot values, turn excerpts). A raw
    newline would end the comment and emit a line YAML then parses as content.
    """
    text = str(value)
    if len(text) > _MAX_PROVENANCE_CHARS:
        text = text[:_MAX_PROVENANCE_CHARS] + " ..."
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    head, *rest = lines
    return [f"# {key}: {head}"] + [f"#     {ln}" for ln in rest]


def probe_yaml(probe: Probe, *, provenance: dict) -> str:
    """The staged file: provenance header comments over a one-entry YAML list.

    The list shape matches `<pack>/probes/*.yaml`, so adopting a discovery is a
    `git mv` and nothing else. The replay verdict is deliberately absent —
    staging happens before replay; it rides in the run artifact instead.
    """
    header = [
        "# Discovered by Evalyn `discover` — STAGED, not adopted.",
        f"# Move this file to ../probes/{probe.id}.yaml to adopt it as a gate probe.",
    ]
    for key, value in provenance.items():
        header.extend(_comment_lines(str(key), value))
    body = yaml.safe_dump([probe.model_dump(exclude_none=True)], sort_keys=False,
                          allow_unicode=True, default_flow_style=False)
    return "\n".join(header) + "\n" + body


def stage_probe(pack: Pack, probe: Probe, yaml_text: str, *,
                staging_dir: Path | None = None) -> Path:
    """Write the probe under `<pack>/discoveries/` and return its path.

    Atomic: a temp file in the *same* directory (so `os.replace` is a rename,
    not a cross-device copy) is swapped into place. A reader never sees a
    partial probe. The temp name is unique per call, so two concurrent sessions
    that confirm the *same* finding cannot clobber each other mid-write.
    """
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
