import { Link } from "react-router-dom";

import type { RunSummary, VerdictHint } from "../api/types";
import { formatUsd, formatUtc } from "../format";
import { DegradedRow } from "./DegradedRow";
import { Flatline } from "./Flatline";
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
 * - Numerics are `tabular-nums`, so a column does not jitter between renders.
 */

const COLUMNS = [
  { key: "status", label: "Status" },
  { key: "run", label: "Run" },
  { key: "mode", label: "Mode" },
  { key: "pack", label: "Pack" },
  { key: "created", label: "Created (UTC)" },
  { key: "verdict", label: "Verdict" },
  { key: "spend", label: "Judge USD", numeric: true },
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
    return <Flatline reason="this mode produces no gate verdict" />;
  }
  return (
    <span
      data-metric="verdict_hint"
      title="Approximate — computed from the probe rows. The authoritative verdict comes from the gate."
      className={`text-legend uppercase tabular-nums ${HINT_INK[hint]}`}
    >
      {hint}
      <span aria-hidden="true" className="text-chassis-400">
        {" ~"}
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
      className="engrave-b align-top transition-colors duration-detent hover:bg-chassis-50"
    >
      <td className="py-2 pl-4 pr-3 sm:pl-6">
        <RunStatusChip status={run.status} />
      </td>

      <td className="py-2 pr-3">
        <Link
          to={`/runs/${run.run_id}`}
          className="break-all text-readout text-chassis-900 underline decoration-chassis-400 underline-offset-4 transition-colors duration-detent hover:decoration-chassis-900"
        >
          {run.run_id}
        </Link>
      </td>

      <td className="py-2 pr-3 text-readout text-chassis-700">{run.mode}</td>

      <td className="py-2 pr-3 text-readout text-chassis-700">
        {run.pack_name ?? <Flatline reason="pack name not recorded" />}
      </td>

      <td className="whitespace-nowrap py-2 pr-3 text-readout tabular-nums text-chassis-700">
        {formatUtc(run.created_at)}
      </td>

      <td className="py-2 pr-3">
        <VerdictHintCell hint={run.verdict_hint} />
      </td>

      <td className="py-2 pl-3 pr-4 text-right sm:pr-6">
        {/* `null` is "this run cannot tell you", never 0.00. */}
        {run.judge_usd === null ? (
          <Flatline reason="judge spend was not recorded" />
        ) : (
          <span
            data-metric="judge_usd"
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
      <table className="w-full min-w-[54rem] border-collapse text-left">
        <caption className="sr-only">
          Indexed run artifacts, newest first.
        </caption>
        <thead>
          <tr className="engrave-b rule-major bg-chassis-50">
            {COLUMNS.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`whitespace-nowrap py-2 text-legend font-normal uppercase text-chassis-600 ${
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
