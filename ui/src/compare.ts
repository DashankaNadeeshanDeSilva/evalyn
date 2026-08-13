import type { CategoryTally, HardMetrics, Scoreboard } from "./api/types";

/**
 * `Scoreboard` — two maps and four scalars — arranged the way the board is read.
 *
 * The arithmetic and the wording live here rather than in the page for the
 * reason `trust.ts` and `discoveries.ts` do: the sentences below are the part
 * of this surface most likely to say something untrue, and a sentence in JSX is
 * a sentence nothing can pin.
 *
 * ## The half-empty board is the normal case, not an error
 *
 * `run_compare` judges only probes that carry a rubric check. A pack with none
 * produces a board whose verdict half is genuinely empty while its hard-metric
 * half is fully measured — which is exactly what the only compare artifact in
 * `runs/` is. So the absence carries a *reason* rather than a shrug, and the
 * reason never implies the comparison failed, was skipped, or is still loading.
 *
 * ## Nothing here ranks anything
 *
 * There is no combined winner field on the wire, and the engine prints "no
 * combined winner is computed" in its own report. This module computes no
 * score, no lead, no margin and no recommendation. The one derived number it
 * does emit is the arithmetic difference between two hard metrics, which is
 * subtraction rather than a judgement — and it is labelled as such.
 */

/** The unit a hard-metric row is read in. Decides the formatting, nothing else. */
export type MetricUnit = "seconds" | "count";

/** One category's verdict tally, renamed into the page's vocabulary. */
export interface VerdictRow {
  category: string;
  winsA: number;
  winsB: number;
  ties: number;
  unsure: number;
  flips: number;
  criteriaJudged: number;
  flipRate: number;
}

/** One measurement of one category, both sides and the difference between them. */
export interface MetricRow {
  /** Stable across renders and across categories. The React key. */
  key: string;
  label: string;
  unit: MetricUnit;
  /** What an absent value means here — the flat-line's spoken reason. */
  absence: string;
  a: number | null;
  b: number | null;
  /** `b - a`, and `null` unless **both** sides carry a value. */
  delta: number | null;
}

export interface MetricBlock {
  category: string;
  rows: MetricRow[];
}

export interface CompareModel {
  /** Alphabetical, matching `render_compare_report`'s own ordering. */
  verdicts: VerdictRow[];
  /** Non-null exactly when `verdicts` is empty: why, truthfully. */
  verdictAbsence: string | null;
  /** Same categories, same order, so a category reads straight down the page. */
  metrics: MetricBlock[];
  metricAbsence: string | null;
  /** Pairs dropped before judging. `null` when none were. */
  exclusion: string | null;
  /** What the judge actually scored. The denominator behind every tally. */
  criteriaJudged: number;
}

/**
 * The disclaimer the engine prints, in the engine's own words
 * (`compare.py` closes every report with it). It is not decoration: collapsing
 * verdicts and hard metrics into one number is the exact claim Evalyn refuses
 * to make, and a cockpit that quietly made it would be the more authoritative
 * of the two surfaces.
 */
export const ADVISORY =
  "Compare is advisory. Verdicts and hard metrics are reported side by side and " +
  "never combined, so no combined winner is computed.";

/** The difference column, disclaimed where it is read. */
export const DELTA_LEGEND =
  "The difference column is arithmetic — B − A — and carries no direction of its own.";

const VERDICT_ABSENCE =
  "No rubric-checked probes were judged, so this comparison has no pairwise " +
  "verdicts. Compare judges only probes that carry a rubric check. The hard " +
  "metrics below come from the trial records and are unaffected.";

const METRIC_ABSENCE =
  "This comparison records no hard metrics. They are measured from trial " +
  "records, so a run written without them has none to report.";

/**
 * The four measurements, in the order `render_compare_report` prints them.
 *
 * `absence` reads as a sentence about latency for the two rows that can
 * actually be absent. The counts are non-null on the wire, but they are handled
 * through the same branch rather than a second one — a legacy artifact that
 * carries a null where an int is declared meets a flat-line, not a `NaN`.
 */
const SPECS: readonly {
  key: string;
  label: string;
  unit: MetricUnit;
  absence: string;
  a: (m: HardMetrics) => number | null;
  b: (m: HardMetrics) => number | null;
}[] = [
  {
    key: "latency_mean",
    label: "Latency mean",
    unit: "seconds",
    absence: "latency was not recorded in this run's trial records",
    a: (m) => m.latency_mean_a,
    b: (m) => m.latency_mean_b,
  },
  {
    key: "latency_p95",
    label: "Latency p95",
    unit: "seconds",
    absence: "latency was not recorded in this run's trial records",
    a: (m) => m.latency_p95_a,
    b: (m) => m.latency_p95_b,
  },
  {
    key: "invariant_failures",
    label: "Invariant failures",
    unit: "count",
    absence: "this run's trial records carry no invariant count",
    a: (m) => m.invariant_failures_a,
    b: (m) => m.invariant_failures_b,
  },
  {
    key: "trials",
    label: "Trials",
    unit: "count",
    absence: "this run recorded no trial count",
    a: (m) => m.trials_a,
    b: (m) => m.trials_b,
  },
];

function tallyRow(category: string, tally: CategoryTally): VerdictRow {
  return {
    category,
    winsA: tally.wins_a,
    winsB: tally.wins_b,
    ties: tally.ties,
    unsure: tally.unsure,
    flips: tally.flips,
    criteriaJudged: tally.criteria_judged,
    flipRate: tally.flip_rate,
  };
}

function metricBlock(category: string, metrics: HardMetrics): MetricBlock {
  return {
    category,
    rows: SPECS.map((spec) => {
      const a = spec.a(metrics) ?? null;
      const b = spec.b(metrics) ?? null;
      return {
        key: spec.key,
        label: spec.label,
        unit: spec.unit,
        absence: spec.absence,
        a,
        b,
        // A difference needs both sides. Treating an unrecorded latency as zero
        // would report a 2.8s improvement on a run that measured nothing.
        delta: a === null || b === null ? null : b - a,
      };
    }),
  };
}

export function buildCompareModel(board: Scoreboard): CompareModel {
  const verdicts = Object.entries(board.categories)
    .map(([category, tally]) => tallyRow(category, tally))
    .sort((x, y) => x.category.localeCompare(y.category));

  const metrics = Object.entries(board.hard_metrics)
    .map(([category, hard]) => metricBlock(category, hard))
    .sort((x, y) => x.category.localeCompare(y.category));

  return {
    verdicts,
    verdictAbsence: verdicts.length === 0 ? VERDICT_ABSENCE : null,
    metrics,
    metricAbsence: metrics.length === 0 ? METRIC_ABSENCE : null,
    exclusion:
      board.excluded_pairs > 0
        ? `${board.excluded_pairs} ${
            board.excluded_pairs === 1 ? "pair was" : "pairs were"
          } excluded from judging.`
        : null,
    criteriaJudged: verdicts.reduce((sum, row) => sum + row.criteriaJudged, 0),
  };
}

/**
 * Two decimals for a latency, because that is what `evalyn compare` prints.
 *
 * The cockpit and the terminal read the same artifact; a figure that disagrees
 * between them makes the operator wonder which one is lying.
 */
export function formatValue(value: number, unit: MetricUnit): string {
  return unit === "seconds" ? `${value.toFixed(2)}s` : String(value);
}

/**
 * A signed difference — and never a signed zero.
 *
 * The sign is read off the **rounded** value, so a difference that rounds away
 * to nothing is printed as nothing. `-0.00s` puts a direction on a measurement
 * that has none, which on a board that refuses to name a winner is exactly the
 * wrong impression to leave.
 */
export function formatDelta(value: number, unit: MetricUnit): string {
  const rounded = unit === "seconds" ? Number(value.toFixed(2)) : value;
  const magnitude = formatValue(Math.abs(rounded), unit);
  if (rounded > 0) return `+${magnitude}`;
  if (rounded < 0) return `-${magnitude}`;
  return magnitude;
}

/**
 * `0.16666666666666666` -> `16.7%`.
 *
 * One decimal, fixed, so the column does not jitter between renders — the same
 * reason `formatUsd` fixes four.
 */
export function formatFlipRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}
