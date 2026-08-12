import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TrendMetric, TrendSeries } from "../../api/types";
import { TrendChart } from "../TrendChart";

/**
 * The scope.
 *
 * Every assertion here is about what the chart **draws**, not about what it was
 * asked to draw, because four defects in this plan were found only by looking
 * at the rendered output. Recharts needs a measured container and jsdom has no
 * `ResizeObserver` at all — verified, `typeof ResizeObserver === "undefined"` —
 * so `TrendChart` passes `initialDimension` to `ResponsiveContainer`, which is
 * what makes the surface render at a real size here **and** removes the
 * zero-width first paint in a browser.
 */

const T = (day: number) => `2026-08-0${day}T00:00:00+00:00`;

function series(
  probeId: string,
  points: [day: number, value: number][],
  metric: TrendMetric = "pass_k",
): TrendSeries {
  return {
    pack_name: "twincore-injection",
    probe_id: probeId,
    metric,
    points: points.map(([day, value]) => ({
      run_id: `2026080${day}T000000-0000000${day}-twincore`,
      created_at: T(day),
      value,
    })),
  };
}

function curves(container: HTMLElement): SVGPathElement[] {
  return [...container.querySelectorAll<SVGPathElement>(".recharts-line-curve")];
}

describe("TrendChart", () => {
  it("says there is no readable history instead of drawing an empty axis frame", () => {
    const { container } = render(
      <TrendChart series={[]} metric="pass_k" selectedProbeId={null} />,
    );

    expect(screen.getByText(/no readable history/i)).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("refuses to draw a trend from a single run and says why", () => {
    const { container } = render(
      <TrendChart
        series={[series("a", [[1, 0]]), series("b", [[1, 1]])]}
        metric="pass_k"
        selectedProbeId="a"
      />,
    );

    expect(screen.getByText(/one readable run/i)).toBeInTheDocument();
    expect(screen.getByText(/needs two/i)).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("draws one line per probe and gives the selected one the heavier stroke", () => {
    const { container } = render(
      <TrendChart
        series={[
          series("anchor", [[1, 0], [2, 0], [3, 0]]),
          series("sibling", [[1, 0], [2, 1], [3, 1]]),
        ]}
        metric="pass_k"
        selectedProbeId="anchor"
      />,
    );

    const drawn = curves(container);
    expect(drawn).toHaveLength(2);

    const widths = drawn.map((c) => Number(c.getAttribute("stroke-width")));
    const heaviest = Math.max(...widths);
    expect(widths.filter((w) => w === heaviest)).toHaveLength(1);
    expect(heaviest).toBeGreaterThan(Math.min(...widths));
  });

  /**
   * The defect this chart exists to avoid. `injection-ignore-instructions` read
   * in runs 1 and 3 and its run-2 artifact is degraded, so the server skipped
   * it. The line must **break**, not dive to the floor and back.
   *
   * Asserted on the path's own `d`: a broken line is drawn as two subpaths, so
   * it carries two `M` commands. One `M` would mean the gap was bridged.
   */
  it("breaks the selected line at a run the probe never read rather than bridging it", () => {
    const { container } = render(
      <TrendChart
        series={[
          series("gappy", [[1, 1], [3, 1]]),
          series("dense", [[1, 1], [2, 1], [3, 1]]),
        ]}
        metric="pass_k"
        selectedProbeId="gappy"
      />,
    );

    const focal = curves(container).find(
      (c) => Number(c.getAttribute("stroke-width")) > 1,
    )!;
    const moves = (focal.getAttribute("d") ?? "").match(/M/g) ?? [];
    expect(
      moves.length,
      "the selected line bridged a run the probe never read",
    ).toBe(2);
  });

  it("marks every reading that did not reach the pass line, and says so in words", () => {
    const { container } = render(
      <TrendChart
        series={[series("anchor", [[1, 0], [2, 1], [3, 0]])]}
        metric="pass_k"
        selectedProbeId="anchor"
      />,
    );

    expect(
      container.querySelectorAll('[data-trend-mark="failed"]'),
    ).toHaveLength(2);
    // Never colour alone: the mark is a different shape AND the legend states
    // in words what a marked reading means.
    expect(screen.getByText(/did not reach 1\.00/i)).toBeInTheDocument();
  });

  it("marks nothing on a metric with no threshold Evalyn commits to", () => {
    const { container } = render(
      <TrendChart
        series={[series("anchor", [[1, 0.004], [2, 0.9]], "judge_usd")]}
        metric="judge_usd"
        selectedProbeId="anchor"
      />,
    );

    expect(container.querySelectorAll('[data-trend-mark="failed"]')).toHaveLength(0);
    expect(screen.queryByText(/did not reach/i)).toBeNull();
  });

  it("names the selected probe and the metric in the chart's own accessible title", () => {
    const { container } = render(
      <TrendChart
        series={[series("injection-exfil-boundaries", [[1, 0], [2, 0]])]}
        metric="pass_k"
        selectedProbeId="injection-exfil-boundaries"
      />,
    );

    const title = container.querySelector("svg title");
    expect(title?.textContent).toMatch(/injection-exfil-boundaries/);
    expect(title?.textContent).toMatch(/pass\^k/);
  });

  it("draws the context lines but still says the selected probe has one reading", () => {
    render(
      <TrendChart
        series={[
          series("solo", [[2, 0]]),
          series("dense", [[1, 1], [2, 1], [3, 1]]),
        ]}
        metric="pass_k"
        selectedProbeId="solo"
      />,
    );

    expect(screen.getByText(/one reading/i)).toBeInTheDocument();
    expect(screen.getByText(/no line can be drawn/i)).toBeInTheDocument();
  });

  /*
   * The three below were all found by rendering the page in a browser and
   * looking at it, which is the only place any of them was visible.
   */

  it("draws a lone reading as a mark rather than drawing nothing at all", () => {
    const { container } = render(
      <TrendChart
        series={[
          series("solo", [[2, 0]]),
          series("dense", [[1, 1], [2, 1], [3, 1]]),
        ]}
        metric="pass_k"
        selectedProbeId="solo"
      />,
    );

    // One reading is a real measurement. Recharts draws no curve through a
    // single point, so showing it implies no trend — and the caption says so.
    expect(container.querySelectorAll("[data-trend-mark]")).toHaveLength(1);
  });

  it("does not explain a mark it never drew", () => {
    render(
      <TrendChart
        series={[series("clean", [[1, 1], [2, 1]]), series("dirty", [[1, 0], [2, 0]])]}
        metric="pass_k"
        selectedProbeId="clean"
      />,
    );

    // `dirty` is on screen as a context line and every one of its readings is
    // below the pass line — but context lines carry no marks, so the key would
    // be describing something the picture does not contain.
    expect(screen.queryByText(/did not reach/i)).toBeNull();
  });

  it("keeps a reading that sits on the domain floor inside the frame", () => {
    const { container } = render(
      <TrendChart
        series={[series("floor", [[1, 0], [2, 0]])]}
        metric="pass_k"
        selectedProbeId="floor"
      />,
    );

    const mark = container.querySelector('[data-trend-mark="failed"]')!;
    const axis = container.querySelector(
      ".recharts-xAxis .recharts-cartesian-axis-line",
    )!;
    // `pass^k` spends most of its life at exactly 0.00, so a mark centred on
    // the plot's own bottom edge — half of it outside the frame — is the
    // common case rather than an edge one. The y padding is what lifts it.
    const markCentre = Number(mark.getAttribute("y")) + 4;
    expect(markCentre).toBeLessThan(Number(axis.getAttribute("y1")));
  });

  /*
   * The three below are the same defect at three ranges, found by rendering a
   * gapped channel in a browser: `trendable` is not "draws", so the legend was
   * keying a 2.5px line to a channel the picture drew as loose dots, counting
   * probes that had put no ink on the page at all, and leaving a context
   * reading with no neighbour invisible.
   */

  it("keys the selected channel to a line only when a line was actually drawn", () => {
    const { container } = render(
      <TrendChart
        series={[
          series("gapped", [[1, 1], [3, 1], [5, 1]]),
          series("dense", [[1, 1], [2, 1], [3, 1], [4, 1], [5, 1]]),
        ]}
        metric="pass_k"
        selectedProbeId="gapped"
      />,
    );

    // Three readings, never two in a row: Recharts draws three zero-length
    // subpaths and no segment, so a line swatch would key a mark nobody drew.
    const caption = container.querySelector("figcaption")!;
    const keyed = [...caption.querySelectorAll("line")].map((l) =>
      Number(l.getAttribute("stroke-width")),
    );
    expect(keyed, "the legend keyed a line to a channel drawn as loose marks").not.toContain(
      2.5,
    );
    expect(screen.getByText(/never two in consecutive runs/i)).toBeInTheDocument();
    // ...and the channel is still ink on the page rather than nothing.
    expect(container.querySelectorAll("[data-trend-mark]")).toHaveLength(3);
  });

  it("draws a context reading with no neighbouring run as a mark rather than nothing", () => {
    const { container } = render(
      <TrendChart
        series={[
          series("dense", [[1, 1], [2, 1], [3, 1]]),
          series("sparse", [[1, 0], [3, 0]]),
        ]}
        metric="pass_k"
        selectedProbeId="dense"
      />,
    );

    // `dot={false}` on a context line whose every reading is isolated means the
    // probe is on the chart's own count and absent from the picture.
    expect(
      container.querySelectorAll('[data-trend-mark="context"]'),
      "a context channel that draws no segment put no ink on the page",
    ).toHaveLength(2);
  });

  it("counts only the probes it drew a line for, and says how the rest were drawn", () => {
    render(
      <TrendChart
        series={[
          series("anchor", [[1, 0], [2, 0], [3, 0]]),
          series("twin", [[1, 1], [2, 1], [3, 1]]),
          series("sparse", [[1, 1], [3, 1]]),
          series("silent", []),
        ]}
        metric="pass_k"
        selectedProbeId="anchor"
      />,
    );

    // Four channels, one selected. Of the other three, one draws a line, one
    // draws marks alone, and one drew nothing whatever and is claimed by
    // neither entry.
    expect(screen.getByText(/1 other probe$/i)).toBeInTheDocument();
    expect(screen.getByText(/^1 more, drawn as marks alone$/i)).toBeInTheDocument();
  });

  it("counts the context lines in the legend rather than leaving them unexplained", () => {
    render(
      <TrendChart
        series={[
          series("anchor", [[1, 0], [2, 0]]),
          series("s1", [[1, 0], [2, 1]]),
          series("s2", [[1, 0], [2, 1]]),
        ]}
        metric="pass_k"
        selectedProbeId="anchor"
      />,
    );

    expect(screen.getByText(/2 other probes/i)).toBeInTheDocument();
  });
});
