import { Link } from "react-router-dom";

import type { RunSummary } from "../api/types";
import { formatUtc } from "../format";
import { Flatline } from "./Flatline";
import { IconFlatline } from "./InstrumentIcon";
import { RunStatusChip } from "./RunStatusChip";

/**
 * A run whose artifact could not be fully read — drawn as a dead channel.
 *
 * Not hidden, and deliberately not styled as an error alert. The row is
 * present, keeps its column positions, and the `run_id` stays fully legible and
 * openable; only the readouts the artifact cannot fill are flat-lined. That is
 * on-metaphor for a bench instrument and it discharges Product Principle 3:
 * degrade visibly rather than hide.
 *
 * The reason appears twice, on purpose — as the row's `title` and as stated
 * text beneath the id. A greyed row with no explanation is exactly the failure
 * mode `degraded_reason` exists to prevent, and a tooltip alone is invisible to
 * a keyboard and to a projector.
 *
 * `status` is still shown: it survives the salvage read, and suppressing it
 * would tell the operator less than the index actually knows.
 */
export function DegradedRow({ run }: { run: RunSummary }) {
  const reason = run.degraded_reason ?? "this artifact could not be read";

  return (
    <tr
      data-testid="run-row"
      data-run-id={run.run_id}
      data-degraded="true"
      title={reason}
      // The dead-channel wash: `degraded` at 8%, which is the one place that
      // 2.43:1 grey is honest — a ground tint that carries no meaning on its
      // own, under a row that states its condition three other ways.
      className="engrave-b bg-degraded/[0.08] align-top"
    >
      <td className="py-2 pl-4 pr-3 sm:pl-6">
        {/* Reported by the salvage read, not verified. */}
        <RunStatusChip status={run.status} unverified />
      </td>

      <td className="py-2 pr-3">
        <Link
          to={`/runs/${run.run_id}`}
          className="break-all text-readout text-chassis-900 underline decoration-chassis-500 underline-offset-4 transition-colors duration-state hover:decoration-chassis-900"
        >
          {run.run_id}
        </Link>
        {/*
         * ONE line, clipped, never wrapped.
         *
         * ~26 of 80 real rows are degraded. Wrapped, this sentence repeats
         * verbatim twenty-six times, roughly doubles the height of a third of
         * the table and destroys the rhythm the face depends on — the defect is
         * already visible at one row in four. The full text stays in the DOM
         * (for the row's `title`, for a screen reader, and for the test), and
         * the detail page states it in full.
         */}
        <p className="mt-1 flex items-center gap-2 text-legend text-chassis-600">
          <IconFlatline className="h-3 w-7 shrink-0 text-chassis-500" />
          <span className="truncate">
            <span className="uppercase tracking-legend text-chassis-700">
              Degraded
            </span>
            {" — "}
            {reason}
          </span>
        </p>
      </td>

      <td className="py-2 pr-3 text-readout text-chassis-700">{run.mode}</td>

      <td className="py-2 pr-3 text-readout text-chassis-700">
        {run.pack_name ?? (
          <Flatline word="unknown" reason="pack name not recoverable" />
        )}
      </td>

      <td
        data-numeric="created_at"
        className="whitespace-nowrap py-2 pr-3 text-readout tabular-nums text-chassis-700"
      >
        {formatUtc(run.created_at)}
      </td>

      {/* The readouts a dead channel cannot fill. Never `data-metric`, and
          always the `dead` mark — this is damage, not correct absence. */}
      <td className="py-2 pr-3">
        <Flatline
          word="unreadable"
          reason="no verdict: the probe results were not readable"
        />
      </td>
      <td className="py-2 pl-3 pr-4 text-right sm:pr-6">
        <Flatline
          word="unrecorded"
          reason="judge spend was not recorded on this artifact"
        />
      </td>
    </tr>
  );
}
