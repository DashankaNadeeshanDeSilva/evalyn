import type { TrendMetric } from "../api/types";
import { METRIC_FACTS, type Channel } from "../trends";
import { Flatline } from "./Flatline";

/**
 * The channel bank: every probe in the pack, written down.
 *
 * ## Why a table sits under the chart at all
 *
 * A line is unreadable by a screen reader, unreadable from the back of a room,
 * and unreadable when thirty of its neighbours are drawn as context. So every
 * number the scope draws is also here as text, in tabular figures, and the
 * chart is the *view* rather than the record. It is also the selector — one
 * click, or one Enter, promotes a channel to the focal line.
 *
 * Same conventions as `RunsTable`: `data-numeric` marks a cell whose value is a
 * figure, `data-flatlined` (via `Flatline`) marks a cell that carries none, and
 * a cell is never both.
 *
 * ## Two things it deliberately refuses
 *
 * - **A change of `+0.00` for a single reading.** A channel with one reading
 *   made no measurement of change; a zero there reads as "steady across the
 *   history" when the history is one point. It says `one reading` instead.
 * - **Colour on the change column.** Rising is not good and falling is not bad
 *   — on `judge_usd` the polarity is the other way round entirely — so the
 *   direction travels as a sign in text and nothing here is hued.
 */

const COLUMNS = [
  { key: "probe", label: "Probe", width: "44%" },
  { key: "readings", label: "Readings", width: "12%", numeric: true },
  { key: "first", label: "First", width: "14%", numeric: true },
  { key: "latest", label: "Latest", width: "14%", numeric: true },
  { key: "change", label: "Change", width: "16%", numeric: true },
] as const;

/** `+1.00` / `-1.00` / `0.00`. The sign is the direction, and it is text. */
function signed(delta: number, format: (v: number) => string): string {
  if (delta === 0) return format(0);
  return delta > 0 ? `+${format(delta)}` : `-${format(Math.abs(delta))}`;
}

function Reading({
  value,
  format,
  what,
}: {
  value: number | null;
  format: (v: number) => string;
  what: string;
}) {
  if (value === null) {
    return <Flatline word="no readings" reason={`no readable ${what} for this probe`} />;
  }
  return (
    <span data-metric={what} className="text-readout tabular-nums text-chassis-900">
      {format(value)}
    </span>
  );
}

export interface TrendChannelsProps {
  /** Already sorted by `buildTrendModel` — most notable for the metric first. */
  channels: Channel[];
  metric: TrendMetric;
  selectedProbeId: string | null;
  onSelect: (probeId: string) => void;
}

export function TrendChannels({
  channels,
  metric,
  selectedProbeId,
  onSelect,
}: TrendChannelsProps) {
  const facts = METRIC_FACTS[metric];

  if (channels.length === 0) {
    return (
      <p
        data-testid="trend-channels-empty"
        className="engrave-b px-4 py-8 text-readout text-chassis-600 sm:px-6"
      >
        No probes in this pack's history. Channels appear here as the CLI writes
        run artifacts — nothing is missing.
      </p>
    );
  }

  return (
    // Wide content scrolls inside its own container; the page body never
    // scrolls horizontally.
    <div className="overflow-x-auto">
      <table className="w-full min-w-[52rem] table-fixed border-collapse text-left">
        <caption className="sr-only">
          Every probe in this pack, most notable first. Select one to draw it.
        </caption>
        <colgroup>
          {COLUMNS.map((column) => (
            <col key={column.key} style={{ width: column.width }} />
          ))}
        </colgroup>
        <thead>
          {/* No fill — the major rule divides the header, the same way the runs
              table does it. A tinted band would be a second ground. */}
          <tr className="engrave-b rule-major">
            {COLUMNS.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`whitespace-nowrap py-2 text-legend font-normal uppercase tracking-legend text-chassis-600 ${
                  column.key === "probe"
                    ? "pl-4 pr-3 sm:pl-6"
                    : column.key === "change"
                      ? "pl-3 pr-4 text-right sm:pr-6"
                      : "pr-3 text-right"
                }`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {channels.map((channel) => {
            const isSelected = channel.probeId === selectedProbeId;
            return (
              <tr
                key={channel.probeId}
                data-testid="trend-channel"
                // Hover deepens the row's engraved rule rather than tinting the
                // row, which is the runs table's ruling: a fill would put every
                // ink in the row on a second, unmeasured ground.
                className="engrave-b align-top transition-colors duration-state hover:[--rule:theme(colors.chassis.700)]"
              >
                <td className="py-2 pl-4 pr-3 sm:pl-6">
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => onSelect(channel.probeId)}
                    className={`break-all text-left text-readout transition-colors duration-state ${
                      isSelected
                        ? "text-chassis-900 underline decoration-chassis-900 decoration-2 underline-offset-4"
                        : "text-chassis-700 underline decoration-chassis-300 underline-offset-4 hover:text-chassis-900 hover:decoration-chassis-900"
                    }`}
                  >
                    {channel.probeId}
                  </button>
                </td>

                <td
                  data-numeric="readings"
                  className="py-2 pr-3 text-right text-readout tabular-nums text-chassis-700"
                >
                  {channel.readings}
                </td>

                <td className="py-2 pr-3 text-right">
                  <Reading value={channel.first} format={facts.format} what="first" />
                </td>

                <td className="py-2 pr-3 text-right">
                  <Reading value={channel.last} format={facts.format} what="latest" />
                </td>

                <td className="py-2 pl-3 pr-4 text-right sm:pr-6">
                  {channel.delta === null ? (
                    <Flatline
                      variant="n/a"
                      word={channel.readings === 1 ? "one reading" : "no readings"}
                      reason={
                        channel.readings === 1
                          ? "one reading: a change needs two, so none was measured"
                          : "no readable run for this probe"
                      }
                    />
                  ) : (
                    <span
                      data-metric="change"
                      data-numeric="change"
                      className="text-readout tabular-nums text-chassis-900"
                    >
                      {signed(channel.delta, facts.format)}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
