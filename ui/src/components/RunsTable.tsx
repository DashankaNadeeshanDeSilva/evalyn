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
 * Sizing at the 78rem (1248px) floor, verified in a browser for all nine
 * members — the check is that no cell overflows and the narrowest STATUS-to-RUN
 * gap stays above one character.
 *
 * The floor moved from 70rem when `Flatline` gained its required word: three
 * columns that previously held a bare hairline now hold a mark plus a label,
 * and an absent value needs as much room as a present one.
 *
 *   status  16% = 200px  — "✓ failed_to_start", the longest chip
 *   run     30% = 374px  — a 44-char run id at 14px mono
 *   mode     7% =  87px  — "discover"
 *   pack     8% = 100px  — "example", or the mark plus "unknown"
 *   created 15% = 187px  — "2026-08-06 09:10:11Z", whitespace-nowrap
 *   verdict 12% = 150px  — "✓ gate passed", or the mark plus "unreadable"
 *   spend   12% = 150px  — "$0.1234", or the mark plus "unrecorded"
 */
const COLUMNS = [
  { key: "status", label: "Status", width: "16%" },
  { key: "run", label: "Run", width: "30%" },
  { key: "mode", label: "Mode", width: "7%" },
  { key: "pack", label: "Pack", width: "8%" },
  { key: "created", label: "Created (UTC)", width: "15%" },
  // "hint" is in the header rather than on every cell: the list's verdict is
  // computed from `probes[]` without calling `evaluate_gate`, and the contract
  // says never to render it without saying so.
  { key: "verdict", label: "Verdict (hint)", width: "12%" },
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
      className="engrave-b align-top transition-colors duration-state hover:bg-chassis-50"
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
          <tr className="engrave-b rule-major bg-chassis-50">
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
