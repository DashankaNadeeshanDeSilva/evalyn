import type { RunId, TrendMetric, TrendPoint, TrendSeries } from "./api/types";
import { formatUsd } from "./format";

/**
 * The trend model: `TrendSeries[]` off the wire, turned into the two shapes the
 * page draws — a bank of **channels** (one per probe) and a table of **rows**
 * (one per readable run).
 *
 * ## The one rule everything here exists to keep
 *
 * `TrendSeries` states it on the wire: degraded runs are **skipped entirely**
 * rather than emitted as null points, so a gap in a line means "no readable
 * run", never "zero". On the real corpus that is not a hypothetical — 26 of the
 * `example` pack's runs are degraded, and a model that widened every series
 * onto a shared run axis and filled the holes would draw twenty-six fabricated
 * failures and present them as history.
 *
 * So a row carries a `values` map and a probe that did not read in that run is
 * **absent from the map**. Recharts reads `undefined` as a break in the line
 * (with `connectNulls` off, which is its default) and draws a gap. Nothing in
 * this module ever writes a `0` it was not given.
 *
 * ## Why the chart cannot just hand each line its own points
 *
 * Recharts 2.x let a `<Line>` carry a `data` prop of its own, which would have
 * made the union table unnecessary. **Recharts 3.x removed it** — `LineProps`
 * has no `data` — so the chart takes one array and the series are separated by
 * `dataKey`. That is exactly the arrangement that tempts an author into filling
 * the holes, which is why the filling is prohibited here rather than in the
 * component.
 */

/** One run's readings, keyed by probe. A probe absent from `values` did not read. */
export interface ChartRow {
  /** Epoch ms. The x axis is numeric, so an irregular gap between runs shows. */
  t: number;
  /** `created_at` verbatim, for the tooltip — the SPA formats, never the server. */
  iso: string;
  runId: RunId;
  /**
   * probe_id -> value. **Absent means no readable run for that probe.** Never
   * `0`, never `null`: see the module note.
   */
  values: Record<string, number>;
}

/** One probe's history, and what can honestly be said about it. */
export interface Channel {
  probeId: string;
  /** Ascending in time, and only readings that can be placed in time. */
  points: TrendPoint[];
  readings: number;
  first: number | null;
  last: number | null;
  /** `last - first`, and `null` below two readings — two points make a trend. */
  delta: number | null;
  /** Can a line be drawn at all? One reading is a dot, not a trend. */
  trendable: boolean;
}

export interface TrendModel {
  /** Sorted most-notable-first for the metric; empty channels last. */
  channels: Channel[];
  rows: ChartRow[];
  /** Plotted readings, summed across channels. */
  readings: number;
  /** Distinct runs represented — never the same number as `readings`. */
  runs: number;
  /**
   * Readings dropped because `created_at` would not parse. Surfaced rather than
   * swallowed: a silent drop is how a chart quietly stops matching the index.
   */
  unplaceable: number;
}

export interface MetricFacts {
  /** The legend text. `pass^k` is written as `pass^k`, never as a "pass rate". */
  label: string;
  /** One line of prose stating what the number is, for the page's readout. */
  gloss: string;
  /** The y domain. `"auto"` where the metric has no ceiling Evalyn knows. */
  domain: [number, number | "auto"];
  /**
   * The value a reading must reach to count as a pass, or `null` when the
   * metric has no threshold this product commits to. Only `pass^k` and `pass@k`
   * have one; marking a mean score or a dollar figure against an invented
   * threshold would be the chart asserting a verdict Evalyn refuses to assert.
   */
  passLine: number | null;
  /** Which end of the range wants the operator's attention first. */
  worst: "lowest" | "highest";
  format(value: number): string;
}

function fixed2(value: number): string {
  return value.toFixed(2);
}

export const METRIC_FACTS: Record<TrendMetric, MetricFacts> = {
  pass_k: {
    label: "pass^k",
    gloss: "every trial passed",
    domain: [0, 1],
    passLine: 1,
    worst: "lowest",
    format: fixed2,
  },
  pass_at_k: {
    label: "pass@k",
    gloss: "at least one trial passed",
    domain: [0, 1],
    passLine: 1,
    worst: "lowest",
    format: fixed2,
  },
  mean_score: {
    // No ceiling asserted: a scorer's mean is whatever the scorer returns, and
    // clamping the axis at 1.0 would silently crop a reading above it.
    label: "mean score",
    gloss: "the scorer's mean across trials",
    domain: [0, "auto"],
    passLine: null,
    worst: "lowest",
    format: fixed2,
  },
  judge_usd: {
    label: "judge spend",
    gloss: "Evalyn's own judge spend",
    domain: [0, "auto"],
    passLine: null,
    // Spend is the one metric where the *high* reading is the one worth
    // looking at first, so "most notable" cannot be a single direction.
    worst: "highest",
    format: formatUsd,
  },
};

/** Epoch ms, or `NaN` when the stamp will not parse. */
function epoch(iso: string): number {
  return new Date(iso).getTime();
}

/**
 * Build the model.
 *
 * `metric` only chooses the sort direction; it never changes a value. The
 * series' own `metric` field is what the server measured, and this function
 * does not second-guess it.
 */
export function buildTrendModel(
  series: TrendSeries[],
  metric: TrendMetric,
): TrendModel {
  const facts = METRIC_FACTS[metric];
  let unplaceable = 0;

  const channels: Channel[] = series.map((one) => {
    const placeable: TrendPoint[] = [];
    for (const point of one.points) {
      if (Number.isFinite(epoch(point.created_at))) placeable.push(point);
      else unplaceable += 1;
    }
    placeable.sort((a, b) => epoch(a.created_at) - epoch(b.created_at));

    const first = placeable[0]?.value ?? null;
    const last = placeable[placeable.length - 1]?.value ?? null;
    const trendable = placeable.length >= 2;
    return {
      probeId: one.probe_id,
      points: placeable,
      readings: placeable.length,
      first,
      last,
      // Two points make a trend; one is a dot. `null` is the honest answer, and
      // it is what stops the row rendering a confident `+0.00`.
      delta: trendable && first !== null && last !== null ? last - first : null,
      trendable,
    };
  });

  channels.sort((a, b) => {
    // A channel with nothing on it cannot be the page's opening reading, so it
    // sorts last however notable its (absent) value would have been.
    if (a.readings === 0 !== (b.readings === 0)) return a.readings === 0 ? 1 : -1;
    if (a.last !== null && b.last !== null && a.last !== b.last) {
      return facts.worst === "lowest" ? a.last - b.last : b.last - a.last;
    }
    // Deterministic, so the opening channel is a decision rather than luck of
    // the draw in whatever order the server walked the directory.
    return a.probeId < b.probeId ? -1 : a.probeId > b.probeId ? 1 : 0;
  });

  /*
   * One row per *run*, keyed by `(run_id, created_at)` rather than by the
   * timestamp alone: two runs a fraction of a second apart are two runs, and
   * the composite is the same pair the runs cursor is ordered by.
   */
  const byRun = new Map<string, ChartRow>();
  for (const channel of channels) {
    for (const point of channel.points) {
      const key = `${point.run_id}|${point.created_at}`;
      let row = byRun.get(key);
      if (row === undefined) {
        row = {
          t: epoch(point.created_at),
          iso: point.created_at,
          runId: point.run_id,
          values: {},
        };
        byRun.set(key, row);
      }
      row.values[channel.probeId] = point.value;
    }
  }

  const rows = [...byRun.values()].sort(
    (a, b) => a.t - b.t || (a.runId < b.runId ? -1 : a.runId > b.runId ? 1 : 0),
  );

  return {
    channels,
    rows,
    readings: channels.reduce((total, channel) => total + channel.readings, 0),
    runs: rows.length,
    unplaceable,
  };
}

/**
 * Will a probe put a **segment** on the chart?
 *
 * `Channel.trendable` answers a different question — "does this probe have two
 * readings" — and the two come apart on exactly the shape the gap invariant
 * exists to protect. A probe that read in runs 1, 3 and 5 has three readings
 * and not one pair of adjacent rows, so Recharts draws three zero-length
 * subpaths and no line at all. Anything the legend says about a *line* has to
 * be asked of this function, never of `trendable`: a key for a mark nobody drew
 * is a claim about the picture the picture does not support.
 */
export function drawsLine(probeId: string, rows: ChartRow[]): boolean {
  for (let i = 1; i < rows.length; i += 1) {
    if (
      rows[i - 1]!.values[probeId] !== undefined &&
      rows[i]!.values[probeId] !== undefined
    ) {
      return true;
    }
  }
  return false;
}

/**
 * The `t` of every reading with no reading in either adjacent row.
 *
 * These are the readings a line cannot express. They are real measurements, so
 * the chart draws each one as a mark — the alternative is a probe that the
 * channel bank lists with readings and the picture renders as nothing.
 */
export function isolatedReadings(probeId: string, rows: ChartRow[]): Set<number> {
  const alone = new Set<number>();
  rows.forEach((row, i) => {
    if (row.values[probeId] === undefined) return;
    const before = rows[i - 1]?.values[probeId] !== undefined;
    const after = rows[i + 1]?.values[probeId] !== undefined;
    if (!before && !after) alone.add(row.t);
  });
  return alone;
}
