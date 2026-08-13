import type { CheckView } from "../api/types";
import { Flatline } from "./Flatline";
import { RedactedChip } from "./RedactedChip";
import { VerdictBadge } from "./VerdictBadge";

/**
 * One check, with what it actually looked at.
 *
 * The verdict is the headline; this is the sentence under it. A check row says
 * four things an operator needs before they trust a red gate:
 *
 * - **Which tier**, because a tier-1 invariant failing and a tier-3 judge
 *   disagreeing are different kinds of news. `VerdictBadge` carries that.
 * - **Whether it was required**, because a non-required check can fail without
 *   moving the gate.
 * - **Where it looked** — a turn index, or the whole session. `turn: null` is
 *   not turn zero: whole-session checks genuinely have no index, and rendering
 *   one would point the operator at a turn the check never read.
 * - **What it found**, verbatim, including the redaction marker if the redactor
 *   touched it.
 *
 * `evidence` is deliberately rendered as-is and not parsed. On the artifacts in
 * `runs/` today it is often a *description* of what was missing rather than a
 * quotation — `"missing 'I'm here to help with…'"` — and reformatting it into
 * something that looks like a quote would misrepresent a check's own words.
 */
export function CheckEvidence({ check }: { check: CheckView }) {
  return (
    <li
      data-testid="check-evidence"
      data-check={check.check}
      className="engrave-b px-4 py-3 sm:px-6"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <VerdictBadge tier={check.tier} passed={check.passed} />
        <span className="break-all text-readout text-chassis-900">
          {check.check}
        </span>
        {check.redacted ? <RedactedChip what="this evidence" /> : null}
      </div>

      <dl className="mt-1.5 flex flex-wrap items-baseline gap-x-5 gap-y-1 text-legend text-chassis-600">
        <div className="flex items-baseline gap-1.5">
          <dt className="uppercase tracking-legend">Required</dt>
          <dd className="text-chassis-700">{check.required ? "yes" : "no"}</dd>
        </div>
        <div className="flex items-baseline gap-1.5">
          <dt className="uppercase tracking-legend">Weight</dt>
          <dd className="tabular-nums text-chassis-700">
            {check.weight.toFixed(2)}
          </dd>
        </div>
        <div className="flex items-baseline gap-1.5">
          <dt className="uppercase tracking-legend">Score</dt>
          <dd className="tabular-nums text-chassis-700">
            {/* `null` is "no score", never 0.00 — the badge already says so and
                the number must not contradict it. */}
            {check.score === null ? (
              <Flatline
                variant="n/a"
                word="none"
                reason="this check returned no score"
              />
            ) : (
              check.score.toFixed(2)
            )}
          </dd>
        </div>
        <div className="flex items-baseline gap-1.5">
          <dt className="uppercase tracking-legend">Looked at</dt>
          <dd className="text-chassis-700">
            {check.turn === null ? "the whole session" : `turn ${check.turn}`}
          </dd>
        </div>
        {check.unsure ? (
          <div className="flex items-baseline gap-1.5">
            <dt className="uppercase tracking-legend">Unsure</dt>
            <dd className="text-chassis-700">
              the judge was not confident in this reading
            </dd>
          </div>
        ) : null}
      </dl>

      {check.evidence === "" ? null : (
        <p className="mt-2 whitespace-pre-wrap break-words text-readout text-chassis-700">
          {check.evidence}
        </p>
      )}
    </li>
  );
}
