import type { ReactElement, SVGProps } from "react";

import type { VerdictTier } from "../api/types";
import { IconCheck, IconCross, IconQuery } from "./InstrumentIcon";

/**
 * One check's verdict, as glyph AND word AND colour — never colour alone.
 *
 * Two facts are collapsed here on purpose, because an operator reads them
 * together: **which tier** the check belongs to, and **what it answered**.
 *
 * ## `abstained` is a tier, not an outcome, and not tier zero
 *
 * `VerdictTier` is `"1" | "2" | "3" | "abstained"` and it is a **string on the
 * wire, always** — the member `abstained` is why an integer form was never
 * expressible. So the tier is the authority: an abstained check reads
 * `abstained` whatever the boolean beside it says, because the judge declining
 * to score is a third answer rather than a quiet failure.
 *
 * ## `passed: null` is not `passed: false`
 *
 * On a scored tier, `null` means the check produced no score. Rendering that as
 * a failure invents a verdict the run never reached, and this product's whole
 * claim is that it reports what happened. It reads `unscored`, and it shares the
 * unresolved-reading mark with `abstained` rather than the cross.
 *
 * `OUTCOME_INK` and `TIER_LABEL` are written out in full because Tailwind reads
 * source text — a computed class name emits no CSS — and because a `Record`
 * keyed on the union makes a widened enum a compile error instead of a blank
 * badge. All three inks measure above AA on the one ground a badge sits on
 * (`chassis-25`): status-passed 4.84, status-gate_failed 6.24, chassis-600 5.98.
 */

type Outcome = "pass" | "fail" | "abstained" | "unscored";

const OUTCOME_INK: Record<Outcome, string> = {
  pass: "text-status-passed",
  fail: "text-status-gate_failed",
  // Neither is a negative reading, so neither takes the failure hue.
  abstained: "text-chassis-600",
  unscored: "text-chassis-600",
};

const OUTCOME_GLYPH: Record<
  Outcome,
  (props: SVGProps<SVGSVGElement>) => ReactElement
> = {
  pass: IconCheck,
  fail: IconCross,
  abstained: IconQuery,
  unscored: IconQuery,
};

/**
 * The tier, spelled the way the wire spells it. `abstained` carries no numeric
 * tier because it *is* the tier — appending "tier abstained" would read as a
 * fourth severity level rather than as a judge that stood down.
 */
const TIER_LABEL: Record<VerdictTier, string | null> = {
  "1": "tier 1",
  "2": "tier 2",
  "3": "tier 3",
  abstained: null,
};

/** The full sentence, for the tooltip and for a screen reader. */
const OUTCOME_REASON: Record<Outcome, string> = {
  pass: "the check passed",
  fail: "the check failed",
  abstained: "the judge declined to score this check",
  unscored: "the check produced no score — that is not a failure",
};

export function outcomeOf(tier: VerdictTier, passed: boolean | null): Outcome {
  if (tier === "abstained") return "abstained";
  if (passed === true) return "pass";
  if (passed === false) return "fail";
  return "unscored";
}

export function VerdictBadge({
  tier,
  passed,
}: {
  tier: VerdictTier;
  /** `null` is "no score", never "failed". */
  passed: boolean | null;
}) {
  const outcome = outcomeOf(tier, passed);
  const Mark = OUTCOME_GLYPH[outcome];
  const tierLabel = TIER_LABEL[tier];
  return (
    <span
      data-testid="verdict-badge"
      data-tier={tier}
      data-outcome={outcome}
      title={OUTCOME_REASON[outcome]}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap text-legend uppercase tracking-legend ${OUTCOME_INK[outcome]}`}
    >
      <Mark className="h-4 w-4 shrink-0" />
      <span>{outcome}</span>
      {tierLabel === null ? null : (
        // De-emphasised, not hidden: the tier is what says whether a failure is
        // a deterministic invariant or a judge's opinion.
        <span className="text-chassis-600">{tierLabel}</span>
      )}
      <span className="sr-only">{` — ${OUTCOME_REASON[outcome]}`}</span>
    </span>
  );
}
