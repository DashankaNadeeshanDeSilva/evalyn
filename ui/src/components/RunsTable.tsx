import { Link } from "react-router-dom";

import type { RunSummary, VerdictHint } from "../api/types";
import { formatUsd, formatUtc } from "../format";
import { DegradedRow } from "./DegradedRow";
import { Flatline } from "./Flatline";
import { VerdictHintIcon } from "./InstrumentIcon";
import { RunStatusChip } from "./RunStatusChip";

/**
 * The run history, as an instrument face rather than a stack of cards.
 *
 * One continuous table divided by engraved panel lines — no card shell, no
 * rounded container, no shadow. Density is the point: this list runs to ~80
 * rows and grows, and no count is ever written down anywhere (ruling R4-6).
 *
 * Two conventions the rest of the cockpit inherits from here:
 *
 * - `data-metric` marks a cell carrying a real measured value. `data-flatlined`
 *   marks one that carries none. A cell is never both.
 * - `data-numeric` marks a cell whose value is a *figure* — a subset of
 *   `data-metric` plus the timestamp. Every one of them is `tabular-nums`, so
 *   the column does not jitter between renders. The verdict hint is a metric
 *   but not a figure, which is why the two attributes are not the same set.
 */

/**
 * The column budget.
 *
 * `width` is what turns this into an instrument face rather than a stretched
 * HTML table. Without it the run-id column absorbs every spare pixel, and at
 * 1600px the row breaks into two halves separated by ~400px of dead chassis —
 * the eye stops reading it as one row, which is worse on a projector than on a
 * desk. The percentages are the face's fixed graduation; `table-fixed` is what
 * makes the browser honour them.
 *
 * **The budget is sized against the widest content each column can ever hold, at
 * the table's own minimum width — not against the desktop render and not against
 * what the fixtures happen to contain.** `table-fixed` does not clip an
 * overflowing cell; it lets it collide with its neighbour, so an under-sized
 * column is illegible rather than merely tight.
 *
 * Two attempts got this wrong in the same way, which is why the numbers below
 * are measured rather than estimated. STATUS at 9% of a 62rem floor gave a chip
 * 89px and left a 7px gap to the run id — and on a degraded row, where the chip
 * is muted to the same grey as the id, the two read as one string. Re-sizing to
 * 12% fixed the fixtures (all of which say `passed`) while still overflowing by
 * 41px on `failed_to_start`, the longest `RunStatus` member, which no fixture
 * exercises. The column has to hold the widest **enum member**, not the widest
 * sample.
 *
 * An earlier revision derived this budget arithmetically and claimed "zero
 * overflow"; the claim did not survive measurement — pack overflowed by ~2px
 * and spend by ~12.5px, right-aligned, straight into VERDICT. Arithmetic cannot
 * see that a cell inherited the wrong font size, which was the actual cause:
 * the verdict and spend `<td>`s carry no size token, so `Flatline`'s word fell
 * through to the user agent's 16px. Fixing that (the component now states
 * `text-legend`, and `index.css` sets the base to the scale) recovered most of
 * the room on its own.
 *
 * **VERDICT was then narrowed 12% -> 11% against the wrong worst case** — the
 * widest thing that column holds is not a `Flatline` at all. It is
 * `VerdictHintCell`'s longest rendition, `gate unknown`, which needs 125.9px of
 * content box where 11% leaves 124.3. The third mis-sizing of this budget, and
 * the third with the same shape: a column measured against the content in front
 * of the author instead of the widest content the column's own type admits.
 *
 * ## How the numbers below were taken
 *
 * In Chrome, against the **built** stylesheet (the dev-injected styles disabled
 * and `assets/index-*.css` linked in their place), on the **real component
 * markup**, with the scroller pinned to the table's own floor (78rem = 1248px)
 * so every `<td>` box is exactly its percentage of the floor. Each column was
 * then forced through every value its type admits: all nine `RunStatus` members
 * in STATUS, all three `VerdictHint` renditions plus both `Flatline` words in
 * VERDICT, `formatUsd` plus the `Flatline` word in SPEND.
 *
 * **`sr-only` nodes are removed before measuring.** They are `position:absolute`
 * and cannot affect layout, but their text pollutes a range measurement — which
 * is how a reading of this column came back 11px wide of the truth.
 *
 * The face is monospace, so every reading here cross-checks against character
 * count: 0.6em advance, plus `tracking-legend` (0.12em) on the uppercase runs.
 * `gate unknown` = 12 chars x (7.2 + 1.44) + a 16px mark + a 6px gap = 125.9.
 * Two readings that disagree with the character count are two readings to
 * retake.
 *
 * Slack at the 1248px floor, worst case, in the content box (box minus padding):
 *
 *   col        %     avail   widest content it can hold    width   slack
 *   status   16     163.7   "failed_to_start" + mark      151.9   +11.8
 *   run      28.9   347.7   a 38-char id at 14px mono     320.3   +27.4
 *   mode      7      74.3   "discover"                     67.4    +6.9
 *   pack      9      99.3   the mark plus "unknown"        80.5   +18.8
 *   created  15     174.2   "2026-08-06 09:10:11Z"        168.6    +5.6
 *   verdict  12.1   138.0   "gate unknown" + mark         125.9   +12.1
 *   spend    12     113.8   the mark plus "unrecorded"    102.2   +11.6
 *
 * Two columns hold values with no upper bound at all — a `run_id`'s trailing
 * slug and a `pack_name` are whatever the artifact says. Neither can be sized
 * against a worst case, so neither is allowed to overflow: the run id is
 * `break-all` and the degraded row's reason is `truncate`, so an unusually long
 * value costs a second line rather than a collision. The 38-char id above is the
 * canonical stem length, not a ceiling.
 *
 * VERDICT's 12.1% is a floor set by ruling, not by the measurement: 11.2% is
 * where `gate unknown` just fits. The extra is deliberate — it lands VERDICT's
 * slack alongside STATUS's and SPEND's, so the three columns that carry a mark
 * plus a word all have the same room to grow. The 1.1% comes out of RUN, which
 * has the most slack and wraps rather than collides.
 *
 * Re-measure rather than re-derive when this changes — and note that the budget
 * is now executable: `RunsTable.test.tsx` re-derives the worst case from
 * `RUN_STATUSES`, `RUN_MODES` and `VERDICT_HINTS` and reds when a column is
 * narrowed below what its own type can hold. A comment could not stop this
 * happening three times; the assertion can.
 */
export const COLUMNS = [
  { key: "status", label: "Status", width: "16%" },
  { key: "run", label: "Run", width: "28.9%" },
  { key: "mode", label: "Mode", width: "7%" },
  { key: "pack", label: "Pack", width: "9%" },
  { key: "created", label: "Created (UTC)", width: "15%" },
  // "hint" is in the header rather than on every cell: the list's verdict is
  // computed from `probes[]` without calling `evaluate_gate`, and the contract
  // says never to render it without saying so.
  { key: "verdict", label: "Verdict (hint)", width: "12.1%" },
  { key: "spend", label: "Judge USD", width: "12%", numeric: true },
] as const;

/**
 * The list row's verdict is an **approximation**, computed from `probes[]`
 * without calling `evaluate_gate`. The contract says never to render it without
 * saying so, so the column is titled "hint" and every cell carries the caveat.
 */
const HINT_INK: Record<VerdictHint, string> = {
  passed: "text-status-passed",
  failed: "text-status-gate_failed",
  unknown: "text-chassis-600",
};

function VerdictHintCell({ hint }: { hint: VerdictHint | null }) {
  if (hint === null) {
    // Correctness, not damage: `compare` and `discover` have no gate verdict
    // to report. A dead-channel mark here would dilute the one that means the
    // artifact is broken.
    return (
      <Flatline
        variant="n/a"
        word="no gate"
        reason="this mode produces no gate verdict"
      />
    );
  }
  return (
    <span
      data-metric="verdict_hint"
      title="Approximate — computed from the probe rows. The authoritative verdict comes from the gate."
      className={`inline-flex items-center gap-1.5 whitespace-nowrap text-legend uppercase tracking-legend ${HINT_INK[hint]}`}
    >
      {/* Glyph AND word AND colour. This column is the product's central
          output and was the one carrying colour + word alone. */}
      <VerdictHintIcon hint={hint} className="h-4 w-4 shrink-0" />
      {/* "gate " prefixes the word so this column and STATUS stop rendering
          the same green `passed` twice on a gate run — and because the gate
          outcome is literally what this is. */}
      <span>
        {/* chassis-600, NOT chassis-500: this is 12px body text in the
            product's central-output column, and the config's own rule is that
            4.03:1 does not carry text. 5.98:1 de-emphasises just as well. */}
        <span className="text-chassis-600">gate </span>
        {hint}
      </span>
      <span className="sr-only"> (approximate)</span>
    </span>
  );
}

function RunRow({ run }: { run: RunSummary }) {
  return (
    <tr
      data-testid="run-row"
      data-run-id={run.run_id}
      /*
       * Hover deepens the row's engraved rule; it does NOT tint the row.
       *
       * `hover:bg-chassis-50` was a quiet AA failure: it put every status ink
       * on a second ground, and `status-unreadable` measures 4.34:1 there —
       * the exact pairing `tailwind.config.ts` prohibits by name. A state
       * reachable by moving the mouse is not an edge case.
       *
       * It was also a false affordance. The row is not clickable; the run id
       * inside it is. Highlighting the whole row promised a click target that
       * does not exist, so the honest cue is the one an engraved panel would
       * give: the line under the row cuts deeper. It aids the same horizontal
       * tracking a tint was there for, changes no text's ground, and stays
       * inside the world's own vocabulary.
       */
      className="engrave-b align-top transition-colors duration-state hover:[--rule:theme(colors.chassis.700)]"
    >
      <td className="py-2 pl-4 pr-3 sm:pl-6">
        <RunStatusChip status={run.status} />
      </td>

      <td className="py-2 pr-3">
        <Link
          to={`/runs/${run.run_id}`}
          className="break-all text-readout text-chassis-900 underline decoration-chassis-400 underline-offset-4 transition-colors duration-state hover:decoration-chassis-900"
        >
          {run.run_id}
        </Link>
      </td>

      <td className="py-2 pr-3 text-readout text-chassis-700">{run.mode}</td>

      <td className="py-2 pr-3 text-readout text-chassis-700">
        {run.pack_name ?? (
          <Flatline word="unknown" reason="pack name not recorded" />
        )}
      </td>

      <td
        data-numeric="created_at"
        className="whitespace-nowrap py-2 pr-3 text-readout tabular-nums text-chassis-700"
      >
        {formatUtc(run.created_at)}
      </td>

      <td className="py-2 pr-3">
        <VerdictHintCell hint={run.verdict_hint} />
      </td>

      <td className="py-2 pl-3 pr-4 text-right sm:pr-6">
        {/* `null` is "this run cannot tell you", never 0.00. */}
        {run.judge_usd === null ? (
          <Flatline word="unrecorded" reason="judge spend was not recorded" />
        ) : (
          <span
            data-metric="judge_usd"
            data-numeric="judge_usd"
            className="text-readout tabular-nums text-chassis-900"
          >
            {formatUsd(run.judge_usd)}
          </span>
        )}
      </td>
    </tr>
  );
}

export function RunsTable({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) {
    return (
      <p
        data-testid="runs-empty"
        className="engrave-b px-4 py-8 text-readout text-chassis-600 sm:px-6"
      >
        No run artifacts indexed. Runs appear here as the CLI writes them —
        nothing is missing.
      </p>
    );
  }

  return (
    // Wide content scrolls inside its own container; the page body never
    // scrolls horizontally.
    <div className="overflow-x-auto">
      {/* No `max-w` here: the shell's terminating edge (R4-19) owns the
          face's measure, and a second competing cap is how two truths start
          drifting apart. The floor stays — the column budget derives from it. */}
      <table className="w-full min-w-[78rem] table-fixed border-collapse text-left">
        <caption className="sr-only">
          Indexed run artifacts, newest first.
        </caption>
        <colgroup>
          {COLUMNS.map((column) => (
            <col key={column.key} style={{ width: column.width }} />
          ))}
        </colgroup>
        <thead>
          {/* No fill. A tinted band was a second ground under every status ink
              in this table — the thing that let `hover:bg-chassis-50` hide a
              4.34:1 pairing. The major rule beneath already divides the header,
              and an engraved division is the world's own vocabulary anyway. */}
          <tr className="engrave-b rule-major">
            {COLUMNS.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`whitespace-nowrap py-2 text-legend font-normal uppercase tracking-legend text-chassis-600 ${
                  column.key === "status"
                    ? "pl-4 pr-3 sm:pl-6"
                    : column.key === "spend"
                      ? "pl-3 pr-4 text-right sm:pr-6"
                      : "pr-3"
                }`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) =>
            run.degraded ? (
              <DegradedRow key={run.run_id} run={run} />
            ) : (
              <RunRow key={run.run_id} run={run} />
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}
