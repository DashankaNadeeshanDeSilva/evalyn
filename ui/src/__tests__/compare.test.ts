import { describe, expect, it } from "vitest";

import type { CategoryTally, HardMetrics, Scoreboard } from "../api/types";
import {
  ADVISORY,
  DELTA_LEGEND,
  buildCompareModel,
  formatDelta,
  formatFlipRate,
  formatValue,
} from "../compare";

/**
 * The compare model layer.
 *
 * The load-bearing case here is not the full board — it is the **half-empty**
 * one, which is what the only real compare artifact in `runs/` actually is.
 * `packs/twincore-injection` carries no rubric check, `run_compare` judges only
 * rubric-checked probes, so `categories` is `{}` while `hard_metrics` is real.
 * That is a correct result, not a failure, and the sentence this module emits
 * for it is the single most likely place this page ships a lie.
 */

const TALLY = (over: Partial<CategoryTally> = {}): CategoryTally => ({
  wins_a: 0,
  wins_b: 0,
  ties: 0,
  unsure: 0,
  flips: 0,
  criteria_judged: 0,
  flip_rate: 0,
  ...over,
});

const METRICS = (over: Partial<HardMetrics> = {}): HardMetrics => ({
  latency_mean_a: null,
  latency_mean_b: null,
  latency_p95_a: null,
  latency_p95_b: null,
  invariant_failures_a: 0,
  invariant_failures_b: 0,
  trials_a: 0,
  trials_b: 0,
  ...over,
});

const BOARD = (over: Partial<Scoreboard> = {}): Scoreboard => ({
  run_id: "20260812T164746520652-9ec23a3d-twincore-injection-compare",
  pack_name: "twincore-injection",
  created_at: "2026-08-12T16:47:46.520170+00:00",
  label_a: "2026-08-11 run",
  label_b: "2026-08-12 run",
  source_a: "runs/20260811T142601440952-ddfc322c-twincore-injection.json",
  source_b: "runs/20260812T103632337028-bed5f950-twincore-injection.json",
  created_at_a: "2026-08-11T14:26:01.439309+00:00",
  created_at_b: "2026-08-12T10:39:26.130197+00:00",
  categories: {},
  hard_metrics: {},
  excluded_pairs: 0,
  judge_usd: 0,
  rubric_scores_untrusted: false,
  redacted: false,
  ...over,
});

/**
 * The real artifact, measured today, verbatim from
 * `runs/20260812T164746520652-9ec23a3d-twincore-injection-compare.json`.
 */
const REAL = BOARD({
  hard_metrics: {
    injection: {
      latency_mean_a: 2.814908505967697,
      latency_mean_b: 2.274650753461375,
      latency_p95_a: 13.109940875001485,
      latency_p95_b: 10.235264917006134,
      invariant_failures_a: 0,
      invariant_failures_b: 0,
      trials_a: 217,
      trials_b: 217,
    },
  },
});

/**
 * A board on which no two figures coincide.
 *
 * `wins_a: 1, ties: 1, flips: 1` and `217/217` trials make a full `toEqual`
 * look strict while proving nothing: with the values equal, reading `ties`
 * where `flips` was meant is invisible. Distinct figures are what turn the same
 * assertion into a statement about **which field was read**.
 */
const DISTINCT = BOARD({
  categories: {
    boundary: TALLY({
      wins_a: 2,
      wins_b: 3,
      ties: 5,
      unsure: 7,
      flips: 11,
      criteria_judged: 13,
      flip_rate: 0.5,
    }),
  },
  hard_metrics: {
    boundary: METRICS({
      latency_mean_a: 1.11,
      latency_mean_b: 2.75,
      latency_p95_a: 3.3,
      latency_p95_b: 4.95,
      invariant_failures_a: 5,
      invariant_failures_b: 6,
      trials_a: 7,
      trials_b: 10,
    }),
  },
});

describe("which side is which", () => {
  it("reads every tally field into its own key", () => {
    expect(buildCompareModel(DISTINCT).verdicts).toEqual([
      {
        category: "boundary",
        winsA: 2,
        winsB: 3,
        ties: 5,
        unsure: 7,
        flips: 11,
        criteriaJudged: 13,
        flipRate: 0.5,
      },
    ]);
  });

  it("reads every hard-metric field into its own side", () => {
    const rows = buildCompareModel(DISTINCT).metrics[0]!.rows;

    expect(rows.map((row) => [row.key, row.a, row.b, row.delta])).toEqual([
      ["latency_mean", 1.11, 2.75, 2.75 - 1.11],
      ["latency_p95", 3.3, 4.95, 4.95 - 3.3],
      ["invariant_failures", 5, 6, 1],
      ["trials", 7, 10, 3],
    ]);
    // Signed the way the column is labelled — B − A — so B ahead of A is
    // positive. A sign flip here would read as the wrong run being slower.
    expect(rows[3]!.delta).toBeGreaterThan(0);
  });

  it("gives every measurement its own unit and its own spoken absence", () => {
    const rows = buildCompareModel(DISTINCT).metrics[0]!.rows;

    expect(rows.map((row) => row.unit)).toEqual([
      "seconds",
      "seconds",
      "count",
      "count",
    ]);
    expect(rows[0]!.absence).toContain("latency");
    expect(rows[3]!.absence).toContain("trial");
    for (const row of rows) expect(row.absence.length).toBeGreaterThan(0);
  });
});

describe("the empty verdict half", () => {
  /**
   * The copy that must not lie. An earlier page in this codebase shipped a "no
   * checks" sentence that was false about real data and had to be fixed and
   * pinned; this is that pin, written before the page exists.
   */
  it("says no rubric-checked probes were judged, and says why", () => {
    const model = buildCompareModel(REAL);

    expect(model.verdicts).toEqual([]);
    expect(model.verdictAbsence).toContain("No rubric-checked probes were judged");
    // The mechanism, so the sentence is an explanation rather than an apology.
    expect(model.verdictAbsence).toContain("rubric check");
    // ...and the other half of the board is not implicated in the absence.
    expect(model.verdictAbsence).toContain("hard metrics");
  });

  it("never reads as a failure, a skip, a refusal or a load in progress", () => {
    const absence = buildCompareModel(REAL).verdictAbsence ?? "";

    expect(absence).not.toMatch(
      /fail|error|could not|unable|skip|refus|loading|reading|pending|unavailable|missing|not available|no data|yet/i,
    );
  });

  it("states an exclusion only when pairs were actually excluded", () => {
    expect(buildCompareModel(REAL).exclusion).toBeNull();
    expect(buildCompareModel(BOARD({ excluded_pairs: 1 })).exclusion).toBe(
      "1 pair was excluded from judging.",
    );
    expect(buildCompareModel(BOARD({ excluded_pairs: 3 })).exclusion).toBe(
      "3 pairs were excluded from judging.",
    );
  });

  it("falls silent about the absence as soon as a category was judged", () => {
    const model = buildCompareModel(
      BOARD({ categories: { injection: TALLY({ wins_a: 1, criteria_judged: 1 }) } }),
    );

    expect(model.verdictAbsence).toBeNull();
    expect(model.verdicts).toHaveLength(1);
  });
});

describe("the verdict tallies", () => {
  it("carries every figure through unchanged and invents no total", () => {
    const model = buildCompareModel(
      BOARD({
        categories: {
          grounding: TALLY({
            wins_a: 1,
            wins_b: 4,
            ties: 1,
            unsure: 0,
            flips: 1,
            criteria_judged: 6,
            flip_rate: 0.16666666666666666,
          }),
        },
      }),
    );

    expect(model.verdicts[0]).toEqual({
      category: "grounding",
      winsA: 1,
      winsB: 4,
      ties: 1,
      unsure: 0,
      flips: 1,
      criteriaJudged: 6,
      flipRate: 0.16666666666666666,
    });
    // Nothing on the row is a score, a lead or a margin.
    expect(Object.keys(model.verdicts[0]!)).not.toContain("winner");
  });

  it("orders categories the way the CLI report orders them", () => {
    const model = buildCompareModel(
      BOARD({
        categories: { injection: TALLY(), grounding: TALLY(), boundary: TALLY() },
        hard_metrics: { injection: METRICS(), grounding: METRICS(), boundary: METRICS() },
      }),
    );

    expect(model.verdicts.map((row) => row.category)).toEqual([
      "boundary",
      "grounding",
      "injection",
    ]);
    // Both halves in the same order, so a category reads straight down the page.
    expect(model.metrics.map((block) => block.category)).toEqual(
      model.verdicts.map((row) => row.category),
    );
  });

  it("sums the criteria the judge actually scored, across categories", () => {
    const model = buildCompareModel(
      BOARD({
        categories: {
          grounding: TALLY({ criteria_judged: 6 }),
          injection: TALLY({ criteria_judged: 4 }),
        },
      }),
    );

    expect(model.criteriaJudged).toBe(10);
  });
});

describe("the hard metrics", () => {
  it("puts the two sides beside each other with the arithmetic difference", () => {
    const injection = buildCompareModel(REAL).metrics[0]!;

    expect(injection.category).toBe("injection");
    expect(injection.rows.map((row) => row.label)).toEqual([
      "Latency mean",
      "Latency p95",
      "Invariant failures",
      "Trials",
    ]);

    const mean = injection.rows[0]!;
    expect(mean.a).toBeCloseTo(2.814908505967697, 12);
    expect(mean.b).toBeCloseTo(2.274650753461375, 12);
    expect(mean.delta).toBeCloseTo(2.274650753461375 - 2.814908505967697, 12);
    expect(injection.rows[3]).toMatchObject({ a: 217, b: 217, delta: 0 });
  });

  it("keeps an unrecorded latency null, and refuses a difference against it", () => {
    // The pre-#2b shape: latency was never recorded, trials still counted.
    const block = buildCompareModel(
      BOARD({ hard_metrics: { injection: METRICS({ trials_a: 3, trials_b: 3 }) } }),
    ).metrics[0]!;

    expect(block.rows[0]).toMatchObject({ a: null, b: null, delta: null });
    // Zero would be a measurement. Null is the absence of one, and a difference
    // needs both sides.
    expect(block.rows[0]!.a).not.toBe(0);
    expect(block.rows[3]).toMatchObject({ a: 3, b: 3, delta: 0 });
  });

  it("refuses a difference when only one side is recorded", () => {
    const block = buildCompareModel(
      BOARD({ hard_metrics: { injection: METRICS({ latency_mean_b: 1.5 }) } }),
    ).metrics[0]!;

    expect(block.rows[0]).toMatchObject({ a: null, b: 1.5, delta: null });
  });

  it("says so plainly when the artifact records no hard metrics at all", () => {
    const model = buildCompareModel(BOARD());

    expect(model.metrics).toEqual([]);
    expect(model.metricAbsence).toContain("no hard metrics");
    expect(model.metricAbsence).toContain("trial records");
    expect(model.metricAbsence).not.toMatch(/fail|error|loading|missing|yet/i);
    expect(buildCompareModel(REAL).metricAbsence).toBeNull();
  });
});

describe("the readouts", () => {
  it("formats seconds to the two decimals the CLI report prints", () => {
    // `2.81s/2.27s` and `13.11s/10.24s` are what `evalyn compare` emitted for
    // this artifact; the cockpit must not disagree with the terminal.
    expect(formatValue(2.814908505967697, "seconds")).toBe("2.81s");
    expect(formatValue(2.274650753461375, "seconds")).toBe("2.27s");
    expect(formatValue(13.109940875001485, "seconds")).toBe("13.11s");
    expect(formatValue(10.235264917006134, "seconds")).toBe("10.24s");
  });

  it("formats a count as itself", () => {
    expect(formatValue(217, "count")).toBe("217");
    expect(formatValue(0, "count")).toBe("0");
  });

  it("signs a difference, and refuses a signed zero", () => {
    expect(formatDelta(-0.540257752506322, "seconds")).toBe("-0.54s");
    expect(formatDelta(0.540257752506322, "seconds")).toBe("+0.54s");
    expect(formatDelta(0, "seconds")).toBe("0.00s");
    // Rounds to nothing, so it is nothing — `-0.00s` is a sign on no difference.
    expect(formatDelta(-0.004, "seconds")).toBe("0.00s");
    expect(formatDelta(-2, "count")).toBe("-2");
    expect(formatDelta(2, "count")).toBe("+2");
    expect(formatDelta(0, "count")).toBe("0");
  });

  it("reads a flip rate as a percentage", () => {
    expect(formatFlipRate(0.16666666666666666)).toBe("16.7%");
    expect(formatFlipRate(0)).toBe("0.0%");
    expect(formatFlipRate(1)).toBe("100.0%");
  });
});

describe("the advisory rule", () => {
  it("refuses a combined winner in the engine's own words", () => {
    expect(ADVISORY).toMatch(/advisory/i);
    expect(ADVISORY).toMatch(/no combined winner is computed/i);
    expect(ADVISORY).toMatch(/never combined/i);
  });

  it("says the difference column is arithmetic, not a judgement", () => {
    expect(DELTA_LEGEND).toContain("B − A");
    expect(DELTA_LEGEND).not.toMatch(/better|worse|faster|slower|improve|regress|win/i);
  });

  it("keeps every ranking word out of the model's own copy", () => {
    const model = buildCompareModel(REAL);
    const copy = [
      model.verdictAbsence,
      model.metricAbsence,
      model.exclusion,
      ADVISORY,
      DELTA_LEGEND,
    ]
      .filter((line): line is string => line !== null)
      .join(" ");

    expect(copy).not.toMatch(/better|worse|faster|slower|improve|regress|recommend/i);
  });
});
