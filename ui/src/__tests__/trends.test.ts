import { describe, expect, it } from "vitest";

import type { TrendSeries } from "../api/types";
import { METRIC_FACTS, buildTrendModel } from "../trends";

/**
 * The trend model, which is where the page's honesty actually lives.
 *
 * `TrendSeries` documents the property every assertion below defends: degraded
 * runs are **skipped entirely** rather than emitted as null points, so a gap in
 * a line means "no readable run", not "zero". Measured on the real corpus, 26
 * of the `example` pack's runs are degraded — a model that widened every series
 * onto a shared run axis and filled the holes with `0` would draw twenty-six
 * fabricated failures and call it history.
 *
 * So the model never invents a reading. It groups by run, and a probe with no
 * reading in a run is **absent from that row**, which is what makes Recharts
 * leave a gap instead of a line to the floor.
 */

function series(
  probeId: string,
  points: [iso: string, value: number, runId?: string][],
): TrendSeries {
  return {
    pack_name: "example",
    probe_id: probeId,
    metric: "pass_k",
    points: points.map(([created_at, value, runId]) => ({
      run_id: runId ?? `20260804T081544-${created_at.slice(0, 10)}-example`,
      created_at,
      value,
    })),
  };
}

const T1 = "2026-08-01T00:00:00+00:00";
const T2 = "2026-08-02T00:00:00+00:00";
const T3 = "2026-08-03T00:00:00+00:00";

describe("buildTrendModel", () => {
  it("sorts a probe's readings into time order whatever order they arrived in", () => {
    const model = buildTrendModel([series("a", [[T3, 1], [T1, 0], [T2, 0.5]])], "pass_k");

    expect(model.channels[0]!.points.map((p) => p.created_at)).toEqual([T1, T2, T3]);
    expect(model.rows.map((r) => r.iso)).toEqual([T1, T2, T3]);
  });

  it("leaves a run a probe never read ABSENT from the row rather than filling it with zero", () => {
    // `b` only read in the middle run. The other two runs are degraded for `b`
    // and the server skipped them, so the row must not carry a `b` key at all.
    const model = buildTrendModel(
      [series("a", [[T1, 1], [T2, 1], [T3, 1]]), series("b", [[T2, 0.25]])],
      "pass_k",
    );

    expect(model.rows).toHaveLength(3);
    expect(Object.hasOwn(model.rows[0]!.values, "b")).toBe(false);
    expect(model.rows[1]!.values["b"]).toBe(0.25);
    expect(Object.hasOwn(model.rows[2]!.values, "b")).toBe(false);
    // The trap this test exists for: a zero would plot as a real failure.
    expect(model.rows[0]!.values["b"]).toBeUndefined();
  });

  it("reports a probe with one reading as untrendable and gives it no delta", () => {
    const model = buildTrendModel([series("solo", [[T1, 0]])], "pass_k");
    const solo = model.channels[0]!;

    expect(solo.readings).toBe(1);
    expect(solo.trendable).toBe(false);
    expect(solo.delta).toBeNull();
    expect(solo.first).toBe(0);
    expect(solo.last).toBe(0);
  });

  it("keeps a probe with no readable reading as a dead channel rather than dropping it", () => {
    const model = buildTrendModel(
      [series("alive", [[T1, 1], [T2, 1]]), series("dead", [])],
      "pass_k",
    );

    expect(model.channels.map((c) => c.probeId).sort()).toEqual(["alive", "dead"]);
    const dead = model.channels.find((c) => c.probeId === "dead")!;
    expect(dead.readings).toBe(0);
    expect(dead.last).toBeNull();
    // ...and it sorts last, because a channel with nothing on it cannot be the
    // page's opening reading.
    expect(model.channels[model.channels.length - 1]!.probeId).toBe("dead");
  });

  it("counts distinct runs rather than readings", () => {
    const model = buildTrendModel(
      [series("a", [[T1, 1], [T2, 1]]), series("b", [[T1, 0], [T2, 0]])],
      "pass_k",
    );

    expect(model.readings).toBe(4);
    expect(model.runs).toBe(2);
  });

  it("separates two runs that share a timestamp instead of merging them", () => {
    const model = buildTrendModel(
      [series("a", [[T1, 1, "20260801T000000-aaaaaaaa-x"], [T1, 0, "20260801T000000-bbbbbbbb-x"]])],
      "pass_k",
    );

    expect(model.runs).toBe(2);
    expect(model.rows).toHaveLength(2);
  });

  it("drops a reading whose timestamp cannot be placed in time, and says how many", () => {
    const model = buildTrendModel(
      [series("a", [[T1, 1], ["not-a-timestamp", 0], [T2, 1]])],
      "pass_k",
    );

    expect(model.unplaceable).toBe(1);
    expect(model.channels[0]!.readings).toBe(2);
    expect(model.rows).toHaveLength(2);
  });

  it("puts the lowest reading first for a score metric", () => {
    const model = buildTrendModel(
      [
        series("healthy", [[T1, 1], [T2, 1]]),
        series("failing", [[T1, 0], [T2, 0]]),
        series("middling", [[T1, 0.5], [T2, 0.5]]),
      ],
      "pass_k",
    );

    expect(model.channels.map((c) => c.probeId)).toEqual([
      "failing",
      "middling",
      "healthy",
    ]);
  });

  it("puts the most expensive reading first for judge spend", () => {
    const model = buildTrendModel(
      [
        series("cheap", [[T1, 0.001], [T2, 0.001]]),
        series("dear", [[T1, 0.5], [T2, 0.9]]),
      ],
      "judge_usd",
    );

    expect(model.channels.map((c) => c.probeId)).toEqual(["dear", "cheap"]);
  });

  it("breaks a tie on probe id so the opening channel is not luck of the draw", () => {
    const model = buildTrendModel(
      [series("zulu", [[T1, 0], [T2, 0]]), series("alpha", [[T1, 0], [T2, 0]])],
      "pass_k",
    );

    expect(model.channels.map((c) => c.probeId)).toEqual(["alpha", "zulu"]);
  });

  it("measures a delta from the first reading to the last", () => {
    const model = buildTrendModel([series("a", [[T1, 0], [T2, 0], [T3, 1]])], "pass_k");

    expect(model.channels[0]!.delta).toBe(1);
    expect(model.channels[0]!.trendable).toBe(true);
  });
});

describe("METRIC_FACTS", () => {
  /**
   * The threshold is not decoration. `pass^k` is "every trial passed", so a
   * reading below 1.0 is a real failure of that probe on that run and the chart
   * may mark it. A mean score and a dollar figure have no threshold Evalyn
   * commits to, and inventing one would be the chart asserting a verdict the
   * product refuses to assert.
   */
  it("gives the pass metrics a ceiling and a pass line, and gives spend neither", () => {
    expect(METRIC_FACTS.pass_k.passLine).toBe(1);
    expect(METRIC_FACTS.pass_at_k.passLine).toBe(1);
    expect(METRIC_FACTS.pass_k.domain).toEqual([0, 1]);

    expect(METRIC_FACTS.judge_usd.passLine).toBeNull();
    expect(METRIC_FACTS.mean_score.passLine).toBeNull();
    expect(METRIC_FACTS.judge_usd.domain).toEqual([0, "auto"]);
  });

  it("formats spend to four decimals so a sub-cent run never reads as free", () => {
    expect(METRIC_FACTS.judge_usd.format(0.0042)).toBe("$0.0042");
    expect(METRIC_FACTS.pass_k.format(0)).toBe("0.00");
  });

  it("labels pass^k as pass^k, never as a pass rate", () => {
    expect(METRIC_FACTS.pass_k.label).toBe("pass^k");
    expect(METRIC_FACTS.pass_at_k.label).toBe("pass@k");
  });
});
