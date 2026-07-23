from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field

from evalyn.scoring.tier1 import INVARIANT_PATTERNS, _eval_invariant
from evalyn.targets.loader import Pack

KNOWN_INVARIANTS = {"non-empty", *INVARIANT_PATTERNS.keys()}


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_pack(pack: Pack) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    if not pack.probes:
        errors.append("pack has no probes")

    # 0. session endpoints the solver hard-requires
    for endpoint in ("open", "message"):
        if endpoint not in pack.spec.sessions:
            errors.append(
                f"sessions has no {endpoint!r} endpoint (the session solver requires it)")

    # 1. unknown invariants (pack-level) + malformed checks (probe-level).
    #    Malformed checks silently no-op or crash at scoring time, so they are
    #    errors here: missing invariant ref, dangling ref, contains/not_contains
    #    without a value, classifier without a question.
    for inv in pack.spec.invariants:
        if inv.id not in KNOWN_INVARIANTS:
            errors.append(f"unknown pack invariant: {inv.id!r}")
    for probe in pack.probes:
        for chk in probe.checks:
            if chk.type == "invariant":
                if chk.ref is None:
                    errors.append(
                        f"probe {probe.id!r}: invariant check has no ref "
                        f"(would silently no-op at Tier-1)")
                elif chk.ref not in KNOWN_INVARIANTS:
                    errors.append(f"probe {probe.id!r}: unknown invariant {chk.ref!r}")
            elif chk.type in ("contains", "not_contains") and not (chk.value or "").strip():
                errors.append(
                    f"probe {probe.id!r}: {chk.type} check has no value "
                    f"(would crash or trivially pass at scoring time)")
            elif chk.type == "classifier" and not (chk.question or "").strip():
                errors.append(
                    f"probe {probe.id!r}: classifier check has no question "
                    f"(Tier-2 would skip or misbehave)")

    # 2. reference solvability against deterministic checks
    for probe in pack.probes:
        if probe.reference is None:
            continue
        for chk in probe.checks:
            if chk.type == "invariant" and chk.required and chk.ref is not None:
                ok, _ = _eval_invariant(chk.ref, probe.reference)
                if not ok:
                    errors.append(
                        f"probe {probe.id!r}: reference fails its own required "
                        f"invariant {chk.ref!r} (broken grader or wrong reference)")
            elif chk.type == "contains" and chk.required and chk.value is not None:
                if chk.value.lower() not in probe.reference.lower():
                    errors.append(
                        f"probe {probe.id!r}: reference missing required substring {chk.value!r}")
            elif chk.type == "not_contains" and chk.required and chk.value is not None:
                if chk.value.lower() in probe.reference.lower():
                    errors.append(
                        f"probe {probe.id!r}: reference contains forbidden substring {chk.value!r}")

    # 3. balanced-set lint
    by_cat: dict[str, list] = defaultdict(list)
    for probe in pack.probes:
        by_cat[probe.category].append(probe)
    for cat, probes in by_cat.items():
        has_attack = any(p.safety_critical for p in probes)
        has_control = any(not p.safety_critical for p in probes)
        if has_attack and not has_control:
            warnings.append(
                f"category {cat!r} has attack probes but no benign control "
                f"(one-sided suite → one-sided optimization)")

    return ValidationReport(ok=not errors, errors=errors, warnings=warnings)
