import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type DotItemDotProps,
  type TooltipContentProps,
} from "recharts";

import type { TrendMetric, TrendSeries } from "../api/types";
import { CHART_INK } from "../chartInk";
import { formatUtc } from "../format";
import { METRIC_FACTS, buildTrendModel, type ChartRow } from "../trends";

/**
 * The scope: one channel picked out of the whole bank.
 *
 * ## Why one focal line over faint context, and not thirty-one legible ones
 *
 * The real corpus is 31 probes across 7 runs, 21 of whose lines actually move.
 * Thirty-one distinguishable colours is not a palette, it is a failure — and it
 * would be exactly the "meaning by colour alone" the surface brief forbids,
 * because no legend of thirty-one swatches is readable from a projector. So
 * every probe is drawn, the selected one is drawn in the ink at 2.5px, and the
 * rest are context at 1px. The distinction is **weight**, which survives
 * greyscale, and the selected probe is named in words above the chart.
 *
 * The context lines are excluded from the tooltip (`tooltipType="none"`) rather
 * than dropped, so hovering a run reports the one reading the operator asked
 * about instead of thirty-one they did not.
 *
 * ## What it refuses to draw
 *
 * - **Nothing readable** → a sentence, never an empty axis frame.
 * - **One readable run** → a sentence. A trend needs two points, and a chart
 *   with a single x value draws a dot on a degenerate axis and calls it history.
 * - **A gap** stays a gap. `connectNulls` is off (Recharts' default, stated here
 *   because bridging is the exact defect that would turn 26 skipped degraded
 *   runs into 26 invented failures).
 *
 * ## Recharts 3.x, verified against the installed types rather than assumed
 *
 * - `<Line data={…}>` **no longer exists** — 3.x's `LineProps` has no `data`
 *   key at all, so per-series arrays are out and the union table in `trends.ts`
 *   is not a preference.
 * - `accessibilityLayer` **defaults to `true`** on cartesian charts in 3.x (it
 *   was opt-in in 2.x). The surface is rendered `role="application"` with
 *   `tabIndex=0` and arrow keys walk the readings, which is what makes the
 *   tooltip keyboard-reachable without any work here.
 * - `title` / `desc` fill the SVG's `<title>` / `<desc>`, which is where the
 *   chart's accessible name comes from.
 * - `initialDimension` on `ResponsiveContainer` gives the chart a size before
 *   the first `ResizeObserver` callback. jsdom has no `ResizeObserver` at all,
 *   so without it the chart renders nothing in every test — and in a browser it
 *   removes a zero-width first paint.
 * - `activeIndex` was removed in 3.0; interaction is the `Tooltip`'s job now.
 *   Nothing here needed it, but a 2.x snippet would have carried it.
 */

export interface TrendChartProps {
  series: TrendSeries[];
  metric: TrendMetric;
  selectedProbeId: string | null;
}

const CHART_HEIGHT = 340;

/** The x tick: a run's stamp, short enough that seven of them fit. */
function tickDate(t: number): string {
  return formatUtc(new Date(t).toISOString()).slice(5, 16);
}

/**
 * A legend swatch, and deliberately **not** a member of the cockpit's icon
 * family.
 *
 * `InstrumentIcon` is one grid, one 1.5 stroke, always `currentColor` — a UI
 * mark. These two are the opposite thing: a key that reproduces the chart's own
 * marks at their own weight and their own ink, which is the only way a legend
 * can key to what is drawn. A `currentColor` glyph at a uniform weight could
 * not show the 2.5px-against-1px distinction the chart uses to separate the
 * selected channel from the rest — the distinction would be stated in the
 * legend and absent from the legend's own sample.
 *
 * Both are `aria-hidden`: the word beside each is the accessible content, so
 * nothing here is carried by the mark alone.
 */
function KeyStroke({ width, ink }: { width: number; ink: string }) {
  return (
    <svg width="24" height="8" aria-hidden="true" focusable="false">
      <line x1="0" y1="4" x2="24" y2="4" stroke={ink} strokeWidth={width} />
    </svg>
  );
}

function KeyMark() {
  return (
    <svg width="10" height="10" aria-hidden="true" focusable="false">
      <rect x="1" y="1" width="8" height="8" fill={CHART_INK.failed} />
    </svg>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-4 py-10 text-readout text-chassis-600 sm:px-6">{children}</p>
  );
}

export function TrendChart({ series, metric, selectedProbeId }: TrendChartProps) {
  const facts = METRIC_FACTS[metric];
  const model = useMemo(() => buildTrendModel(series, metric), [series, metric]);

  const selected = model.channels.find((c) => c.probeId === selectedProbeId);
  const contextCount = model.channels.filter(
    (c) => c.readings > 0 && c.probeId !== selectedProbeId,
  ).length;

  if (model.readings === 0) {
    return (
      <Note>
        No readable history for this pack and metric. Nothing is hidden — there
        is nothing to draw.
      </Note>
    );
  }

  if (model.rows.length < 2) {
    return (
      <Note>
        One readable run in this pack. A trend needs two, so nothing is plotted;
        the readings themselves are in the channel bank below.
      </Note>
    );
  }

  const ticks = model.rows.map((row) => row.t);

  /**
   * A reading's mark. Shape first, colour second — a reading that did not reach
   * the pass line is a filled square in the failure hue, one that did is a small
   * open circle in the ink, and the legend says which is which in words.
   *
   * Only the metrics with a real threshold get marked. `pass^k` is "every trial
   * passed", so below 1.0 IS a failure; a mean score and a dollar figure have no
   * threshold this product commits to, and inventing one would make the chart
   * assert a verdict Evalyn refuses to assert.
   */
  const readingDot = (props: DotItemDotProps) => {
    const { cx, cy, index, value } = props;
    if (typeof cx !== "number" || typeof cy !== "number") return null;
    const failed =
      facts.passLine !== null && typeof value === "number" && value < facts.passLine;
    if (failed) {
      return (
        <rect
          key={`mark-${index}`}
          data-trend-mark="failed"
          x={cx - 4}
          y={cy - 4}
          width={8}
          height={8}
          fill={CHART_INK.failed}
        />
      );
    }
    return (
      <circle
        key={`mark-${index}`}
        data-trend-mark="reading"
        cx={cx}
        cy={cy}
        r={3}
        fill={CHART_INK.face}
        stroke={CHART_INK.focal}
        strokeWidth={1.5}
      />
    );
  };

  /*
   * `TooltipContentProps`' generics default to Recharts' own `ValueType` /
   * `NameType`, and `<Tooltip>` is declared with those defaults too — narrowing
   * the callback to `<number, string>` does NOT narrow the component, so the
   * two sides stop being assignable and `tsc` refuses it. Take the wide type
   * and narrow the one value that is read.
   */
  const tooltip = (props: TooltipContentProps) => {
    const entry = props.payload?.[0];
    if (!props.active || entry === undefined) return null;
    const row = entry.payload as ChartRow;
    const value = entry.value;
    return (
      <div className="border border-chassis-400 bg-chassis-25 px-3 py-2 text-legend text-chassis-900">
        <p className="tabular-nums">
          {facts.label}{" "}
          {typeof value === "number" ? facts.format(value) : "unreadable"}
        </p>
        <p className="mt-1 text-chassis-600">{formatUtc(row.iso)}</p>
        <p className="break-all text-chassis-600">{row.runId}</p>
      </div>
    );
  };

  return (
    <figure className="px-4 py-4 sm:px-6">
      <ResponsiveContainer
        width="100%"
        height={CHART_HEIGHT}
        // jsdom has no ResizeObserver and a browser's first frame has no
        // measurement yet; both render at this size until one arrives.
        initialDimension={{ width: 960, height: CHART_HEIGHT }}
      >
        <LineChart
          data={model.rows}
          margin={{ top: 12, right: 16, bottom: 4, left: 0 }}
          title={
            selected
              ? `${facts.label} for ${selected.probeId}, across ${model.rows.length} runs`
              : `${facts.label} across ${model.rows.length} runs`
          }
          desc={
            `${model.channels.length} probes, ${model.readings} readings. ` +
            `A break in a line is a run with no readable artifact for that probe.`
          }
        >
          <CartesianGrid stroke={CHART_INK.grid} strokeDasharray="2 4" />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            ticks={ticks}
            interval="preserveStartEnd"
            minTickGap={24}
            tickFormatter={tickDate}
            stroke={CHART_INK.axis}
            tick={{ fill: CHART_INK.tick, fontSize: 12 }}
          />
          <YAxis
            type="number"
            domain={facts.domain}
            tickFormatter={facts.format}
            width={68}
            stroke={CHART_INK.axis}
            tick={{ fill: CHART_INK.tick, fontSize: 12 }}
          />
          {facts.passLine === null ? null : (
            <ReferenceLine
              y={facts.passLine}
              stroke={CHART_INK.context}
              strokeDasharray="6 4"
            />
          )}
          <Tooltip content={tooltip} cursor={{ stroke: CHART_INK.axis }} />

          {model.channels
            .filter((c) => c.readings > 0 && c.probeId !== selectedProbeId)
            .map((channel) => (
              <Line
                key={channel.probeId}
                dataKey={(row: ChartRow) => row.values[channel.probeId]}
                name={channel.probeId}
                stroke={CHART_INK.context}
                strokeWidth={1}
                dot={false}
                activeDot={false}
                isAnimationActive={false}
                legendType="none"
                // Kept out of the tooltip so hovering a run answers about the
                // probe the operator selected, not about thirty-one at once.
                tooltipType="none"
              />
            ))}

          {selected && selected.trendable ? (
            <Line
              dataKey={(row: ChartRow) => row.values[selected.probeId]}
              name={selected.probeId}
              stroke={CHART_INK.focal}
              strokeWidth={2.5}
              dot={readingDot}
              activeDot={{ r: 6, fill: CHART_INK.focal }}
              isAnimationActive={false}
              legendType="none"
            />
          ) : null}
        </LineChart>
      </ResponsiveContainer>

      <figcaption className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-legend text-chassis-600">
        {selected && selected.trendable ? (
          <span className="flex items-center gap-2 text-chassis-900">
            <KeyStroke width={2.5} ink={CHART_INK.focal} />
            {selected.probeId}
          </span>
        ) : selected && selected.readings === 1 ? (
          <span className="text-chassis-900">
            {selected.probeId} has one reading, so no line can be drawn for it.
          </span>
        ) : null}

        {contextCount > 0 ? (
          <span className="flex items-center gap-2">
            <KeyStroke width={1} ink={CHART_INK.context} />
            {contextCount} other {contextCount === 1 ? "probe" : "probes"}
          </span>
        ) : null}

        {facts.passLine === null ? null : (
          <span className="flex items-center gap-2">
            <KeyMark />
            did not reach {facts.format(facts.passLine)}
          </span>
        )}

        <span>a break in a line is a run with no readable artifact</span>
      </figcaption>
    </figure>
  );
}
