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
            elif chk.type == "contains":
                if chk.value is not None and chk.values is not None:
                    errors.append(
                        f"probe {probe.id!r}: contains check sets both value and values "
                        f"(mutually exclusive — scoring would silently ignore value)")
                elif chk.values is not None:
                    if not chk.values or any(not v.strip() for v in chk.values):
                        errors.append(
                            f"probe {probe.id!r}: contains check has empty values "
                            f"(every entry must be a non-empty string)")
                elif not (chk.value or "").strip():
                    errors.append(
                        f"probe {probe.id!r}: contains check has no value "
                        f"(would crash or trivially pass at scoring time)")
            elif chk.type == "not_contains":
                if chk.values is not None:
                    errors.append(
                        f"probe {probe.id!r}: not_contains check does not support values "
                        f"(scoring silently ignores it — use value)")
                if not (chk.value or "").strip():
                    errors.append(
                        f"probe {probe.id!r}: not_contains check has no value "
                        f"(would crash or trivially pass at scoring time)")
            elif chk.type == "classifier" and not (chk.question or "").strip():
                errors.append(
                    f"probe {probe.id!r}: classifier check has no question "
                    f"(Tier-2 would skip or misbehave)")
            elif chk.type == "rubric":
                if not (chk.rubric or "").strip():
                    errors.append(
                        f"probe {probe.id!r}: rubric check has no rubric id "
                        f"(Tier-3 would fail mid-eval)")
                elif not (pack.root / "rubrics" / f"{chk.rubric}.md").exists():
                    errors.append(
                        f"probe {probe.id!r}: rubric {chk.rubric!r} not found "
                        f"(expected {chk.rubric}.md under <pack>/rubrics/; criteria "
                        f"are its '##' headings)")

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
            elif chk.type == "contains" and chk.required and chk.values:
                # multi-value OR form: reference must contain at least one needle;
                # label matches the Task-1 CheckResult convention (contains:a|b)
                if not any(v.lower() in probe.reference.lower() for v in chk.values):
                    label = "contains:" + "|".join(chk.values)
                    errors.append(
                        f"probe {probe.id!r}: reference matches none of the needles "
                        f"of required check {label!r}")
            elif chk.type == "contains" and chk.required and chk.value is not None:
                if chk.value.lower() not in probe.reference.lower():
                    errors.append(
                        f"probe {probe.id!r}: reference missing required substring {chk.value!r}")
            elif chk.type == "not_contains" and chk.required and chk.value is not None:
                if chk.value.lower() in probe.reference.lower():
                    errors.append(
                        f"probe {probe.id!r}: reference contains forbidden substring {chk.value!r}")

    # 2b. contradictory intent: capability probes never gate the build, but
    #     safety_critical probes gate on pass^k — declaring both is a probe
    #     authoring mistake. Warn, never error.
    for probe in pack.probes:
        if probe.kind == "capability" and probe.safety_critical:
            warnings.append(
                f"probe {probe.id!r}: kind 'capability' combined with "
                f"safety_critical: true is contradictory (capability probes never "
                f"gate; safety-critical probes gate on pass^k) — pick one intent")

    # 2c. A1 visibility (PR #4 fix #10): Inspect epochs are PACK-WIDE — the
    #     task runs EVERY probe at max(samples), so one probe declaring
    #     samples > 1 multiplies every probe's sessions. Warn, never error.
    max_samples = max((p.samples for p in pack.probes), default=1)
    if max_samples > 1:
        raisers = sorted(p.id for p in pack.probes if p.samples == max_samples)
        warnings.append(
            f"probe(s) {', '.join(repr(r) for r in raisers)} declare "
            f"samples={max_samples}; epochs are pack-wide, so ALL "
            f"{len(pack.probes)} probes run {max_samples} trials each "
            f"({max_samples * len(pack.probes)} sessions total)")

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
