import { useMemo, type ReactNode } from "react";
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
import {
  METRIC_FACTS,
  buildTrendModel,
  drawsLine,
  isolatedReadings,
  type ChartRow,
} from "../trends";

/**
 * The scope: one channel picked out of the whole bank.
 *
 * ## Why one focal line over faint context, and not thirty-one legible ones
 *
 * The `twincore-injection` pack is 31 probes across 7 runs, 21 of whose lines
 * actually move — and it is a DIFFERENT pack from the `example` one the gap
 * invariant is argued from in `trends.ts`, which is 88 runs and 4 probes with
 * 26 of the runs degraded (both measured over the runs index during the Trends
 * review rather than estimated). The two shapes matter together: the wide pack
 * has no gaps at all, the gapped pack has four probes, and the page has to hold
 * for an operator who meets either.
 *
 * Thirty-one distinguishable colours is not a palette, it is a failure — and it
 * would be exactly the "meaning by colour alone" the surface brief forbids,
 * because no legend of thirty-one swatches is readable from a projector. So
 * every probe is drawn, the selected one is drawn in the ink at 2.5px, and the
 * rest are context at 1px. The distinction is **weight**, which survives
 * greyscale, and the selected probe is named in words above the chart.
 *
 * The context lines are drawn but never *reported*: the tooltip reads the entry
 * whose name is the selected probe's, so inspecting a run answers about the one
 * reading the operator asked about instead of thirty-one they did not. It is
 * done there rather than with `tooltipType="none"` on each line for the reason
 * given at the tooltip itself — that flag does not do it.
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
 * ## Recharts 3.x — each claim below carries the check that produced it
 *
 * An earlier draft of this block asserted that `<Line data={…}>` no longer
 * exists, under a header saying the block had been verified. It was the one
 * claim in it that had been reasoned about instead of run, and it was false. So
 * every line now names its own evidence, which is the only form of this note
 * that a later reader can audit.
 *
 * - `<Line data={…}>` **does still exist**: `LineProps extends DataProvider`,
 *   whose `data?: ChartData<…>` is right there in the installed
 *   `types/util/types.d.ts`, and `tsc` accepts it on this file's own `<Line>`.
 *   What it does not do is scope that array to the item — the same types say
 *   item data "is visible for the main chart, and all axes, tooltip, legend …
 *   This is not scoped to the graphical item only." **Rendered** (two `<Line>`s
 *   with their own arrays, one holding t=1 and t=3, the other t=2 and t=4): both
 *   draw, they share one x scale — and the first draws a single unbroken segment
 *   straight across t=2, a run it never read. Per-series arrays therefore
 *   **bridge every gap**, which is the one thing this page may not do. That, and
 *   not the absence of a prop, is why the union table in `trends.ts` is
 *   load-bearing.
 * - `accessibilityLayer` **defaults to `true`** on cartesian charts in 3.x (it
 *   was opt-in in 2.x): nothing here passes it, and the rendered chart is
 *   `role="application"` with a `tabIndex` — read out of the live accessibility
 *   tree in a browser, where arrow keys walk the readings. That is what makes
 *   the tooltip keyboard-reachable without any work here.
 * - `title` / `desc` fill the SVG's `<title>` / `<desc>`, which is where the
 *   chart's accessible name comes from — queried in the browser DOM, and
 *   asserted by name in `TrendChart.test.tsx`.
 * - `initialDimension` on `ResponsiveContainer` gives the chart a size before
 *   the first `ResizeObserver` callback. jsdom has no `ResizeObserver` at all,
 *   so without it the chart renders nothing in every test — which is exactly
 *   what the suite showed — and in a browser it removes a zero-width first
 *   paint.
 * - `activeIndex` is gone from `LineProps` in the installed types (grepped: no
 *   occurrence in `types/cartesian/Line.d.ts`); interaction is the `Tooltip`'s
 *   job now. Nothing here needed it, but a 2.x snippet would have carried it.
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
function KeyStroke({
  width,
  ink,
  dash,
}: {
  width: number;
  ink: string;
  dash?: string;
}) {
  return (
    <svg width="24" height="8" aria-hidden="true" focusable="false">
      <line
        x1="0"
        y1="4"
        x2="24"
        y2="4"
        stroke={ink}
        strokeWidth={width}
        strokeDasharray={dash}
      />
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

/**
 * The two keys for a reading a line cannot express, at the two weights the
 * chart draws them: the selected channel's open mark, and a context channel's
 * dot. Both reproduce the chart's own mark exactly, for the reason `KeyStroke`
 * does — a key that is not the mark is a second thing to learn.
 */
function KeyReading() {
  return (
    <svg width="10" height="10" aria-hidden="true" focusable="false">
      <circle
        cx="5"
        cy="5"
        r="3"
        fill={CHART_INK.face}
        stroke={CHART_INK.focal}
        strokeWidth={1.5}
      />
    </svg>
  );
}

function KeyContextReading() {
  return (
    <svg width="10" height="10" aria-hidden="true" focusable="false">
      <circle cx="5" cy="5" r="2" fill={CHART_INK.context} />
    </svg>
  );
}

function Note({ children }: { children: ReactNode }) {
  return (
    <p className="px-4 py-10 text-readout text-chassis-600 sm:px-6">{children}</p>
  );
}

export function TrendChart({ series, metric, selectedProbeId }: TrendChartProps) {
  const facts = METRIC_FACTS[metric];
  const model = useMemo(() => buildTrendModel(series, metric), [series, metric]);

  const selected = model.channels.find((c) => c.probeId === selectedProbeId);

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

  /*
   * The legend is keyed to what the picture CONTAINS, which is not what the
   * model says the channels have. Every count below is asked of `drawsLine`
   * rather than of `Channel.trendable`, because a probe that read in runs 1, 3
   * and 5 is trendable, draws no segment at all, and had a 2.5px line swatch
   * standing beside its name until a browser showed the three loose dots.
   *
   * A channel that read nothing is in neither count: it is not a line, and it
   * is not a mark either, because there is nothing to mark.
   */
  const context = model.channels.filter(
    (c) => c.readings > 0 && c.probeId !== selectedProbeId,
  );
  const contextLines = context.filter((c) => drawsLine(c.probeId, model.rows));
  const contextMarksOnly = context.length - contextLines.length;
  const focalDrawsLine =
    selected !== undefined && drawsLine(selected.probeId, model.rows);

  /*
   * How many of the SELECTED channel's readings carry the failure mark.
   *
   * The legend is keyed to this rather than to `facts.passLine`, because a
   * legend entry for a mark nobody drew is a claim about the picture that the
   * picture does not support — and it renders on exactly the screen where the
   * operator is least able to check it, since selecting a single-reading
   * channel draws no marks at all. Found by looking at the page.
   */
  const markedReadings =
    facts.passLine === null || selected === undefined
      ? 0
      : selected.points.filter((p) => p.value < facts.passLine!).length;

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

  /**
   * A context channel's isolated reading.
   *
   * Context lines carry `dot={false}`, which is right for a reading inside a
   * drawn segment — thirty channels of dots would be noise — and wrong for one
   * with no neighbour to draw to, which without a mark is a measurement the
   * channel bank lists and the picture omits entirely. So the dot appears for
   * exactly the readings a line cannot express, at the context weight.
   */
  const contextDot =
    (isolated: Set<number>) =>
    (props: DotItemDotProps) => {
      const { cx, cy, index, payload } = props;
      const t = (payload as ChartRow | undefined)?.t;
      if (typeof cx !== "number" || typeof cy !== "number") return null;
      if (t === undefined || !isolated.has(t)) return null;
      return (
        <circle
          key={`context-${index}`}
          data-trend-mark="context"
          cx={cx}
          cy={cy}
          r={2}
          fill={CHART_INK.context}
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
    if (!props.active || selected === undefined) return null;
    /*
     * The entry is found by NAME, not by position.
     *
     * `tooltipType="none"` used to sit on every context line with a comment
     * saying it kept them out of the tooltip. It does not: the installed
     * runtime honours that flag in `DefaultTooltipContent` only
     * (`entry.type === 'none'` is read while it renders its own list), and a
     * custom `content` renderer is handed every line regardless. So
     * `payload[0]` was the first line DECLARED — a context probe — and the
     * tooltip reported its reading under the run's stamp as if it belonged to
     * the channel on screen. Caught by the first test ever written for it.
     */
    const entry = props.payload?.find((p) => p.name === selected.probeId);
    const row = (entry?.payload ?? props.payload?.[0]?.payload) as
      | ChartRow
      | undefined;
    if (row === undefined) return null;
    const value = entry?.value;
    return (
      <div className="border border-chassis-500 bg-chassis-25 px-3 py-2 text-legend text-chassis-900">
        <p className="tabular-nums">
          {/* A gap is a run with no readable artifact for this probe, and it
              says so rather than falling silent — silence is what a broken
              tooltip also looks like. */}
          {typeof value === "number"
            ? `${facts.label} ${facts.format(value)}`
            : `no ${facts.label} reading in this run`}
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
            /*
             * Padding is applied to the RANGE, not the domain, so the scale
             * still says exactly what `facts.domain` says — it only stops a
             * reading that sits on the floor or the ceiling being drawn half
             * outside the frame. `pass^k` spends most of its life at exactly
             * 0.00 and 1.00, so this is the common case, not an edge one, and
             * the clipped marks were visible on the first render of the page.
             */
            padding={{ top: 8, bottom: 8 }}
            tickFormatter={facts.format}
            width={68}
            stroke={CHART_INK.axis}
            tick={{ fill: CHART_INK.tick, fontSize: 12 }}
          />
          <Tooltip content={tooltip} cursor={{ stroke: CHART_INK.axis }} />

          {context.map((channel) => (
            <Line
              key={channel.probeId}
              dataKey={(row: ChartRow) => row.values[channel.probeId]}
              name={channel.probeId}
              stroke={CHART_INK.context}
              strokeWidth={1}
              dot={contextDot(isolatedReadings(channel.probeId, model.rows))}
              activeDot={false}
              isAnimationActive={false}
              legendType="none"
            />
          ))}

          {/*
            Drawn whenever the channel read at all, NOT only when it is
            trendable: a single reading is a real measurement and the scope
            shows it as a lone mark. Recharts draws no curve through one point,
            so nothing here implies a trend the data cannot support — and the
            caption says so in words underneath.
          */}
          {selected && selected.readings > 0 ? (
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

          {/*
            Declared AFTER the lines on purpose. SVG paints in document order,
            so a rule declared first is covered by any line lying on it — and at
            pass^k the threshold is 1.00, which is exactly where every probe
            doing its job sits. Drawn last, the dash shows the reading through
            its own gaps instead of hiding under it.
          */}
          {facts.passLine === null ? null : (
            <ReferenceLine
              y={facts.passLine}
              stroke={CHART_INK.pass}
              strokeDasharray="6 4"
            />
          )}
        </LineChart>
      </ResponsiveContainer>

      <figcaption className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-legend text-chassis-600">
        {selected === undefined || selected.readings === 0 ? null : focalDrawsLine ? (
          <span className="flex items-center gap-2 text-chassis-900">
            <KeyStroke width={2.5} ink={CHART_INK.focal} />
            {selected.probeId}
          </span>
        ) : (
          <span className="flex items-center gap-2 text-chassis-900">
            {/* Keyed only when such a mark is on screen: a reading below the
                pass line is drawn as the failure mark instead, and that mark
                has its own entry below. */}
            {selected.readings > markedReadings ? <KeyReading /> : null}
            {selected.readings === 1
              ? `${selected.probeId} has one reading, so no line can be drawn for it.`
              : `${selected.probeId} has ${selected.readings} readings but never two in consecutive runs, so no line can be drawn for it.`}
          </span>
        )}

        {contextLines.length > 0 ? (
          <span className="flex items-center gap-2">
            <KeyStroke width={1} ink={CHART_INK.context} />
            {contextLines.length} other{" "}
            {contextLines.length === 1 ? "probe" : "probes"}
          </span>
        ) : null}

        {contextMarksOnly > 0 ? (
          <span className="flex items-center gap-2">
            <KeyContextReading />
            {contextMarksOnly} more, drawn as marks alone
          </span>
        ) : null}

        {/* Keyed whenever the rule is drawn, which is exactly when the metric
            has a threshold this product commits to. It was the one mark on the
            chart the caption never mentioned. */}
        {facts.passLine === null ? null : (
          <span className="flex items-center gap-2">
            <KeyStroke width={1} ink={CHART_INK.pass} dash="6 4" />
            the pass line at {facts.format(facts.passLine)}
          </span>
        )}

        {markedReadings === 0 || facts.passLine === null ? null : (
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
