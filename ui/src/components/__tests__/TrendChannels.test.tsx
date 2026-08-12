import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { TrendSeries } from "../../api/types";
import { buildTrendModel } from "../../trends";
import { TrendChannels } from "../TrendChannels";

/**
 * The channel bank: every probe in the pack, as text, beside the scope.
 *
 * It is the chart's accessibility backstop as much as its selector. A line is
 * not readable by a screen reader and is not readable from the back of a room;
 * every number the chart draws is also written down here, in tabular figures,
 * with the empty cells stating what is absent rather than rendering blank.
 */

function seriesOf(
  probeId: string,
  values: number[],
  metric: TrendSeries["metric"] = "pass_k",
): TrendSeries {
  return {
    pack_name: "twincore-injection",
    probe_id: probeId,
    metric,
    points: values.map((value, i) => ({
      run_id: `2026080${i + 1}T000000-0000000${i + 1}-twincore`,
      created_at: `2026-08-0${i + 1}T00:00:00+00:00`,
      value,
    })),
  };
}

function renderBank(
  series: TrendSeries[],
  {
    metric = "pass_k" as TrendSeries["metric"],
    selected = null as string | null,
    onSelect = vi.fn(),
  } = {},
) {
  const model = buildTrendModel(series, metric);
  render(
    <TrendChannels
      channels={model.channels}
      metric={metric}
      selectedProbeId={selected}
      onSelect={onSelect}
    />,
  );
  return { onSelect };
}

describe("TrendChannels", () => {
  it("lists every probe the server sent, including one that never read", () => {
    renderBank([
      seriesOf("injection-exfil-boundaries", [0, 1, 0]),
      seriesOf("never-read", []),
    ]);

    expect(
      screen.getByRole("button", { name: /injection-exfil-boundaries/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /never-read/ })).toBeInTheDocument();
  });

  /**
   * The id column and the table's accessible caption call the row a *channel*,
   * not a probe, and they do it for every metric. On `judge_usd` the route
   * answers with one run-level series whose `probe_id` is `(whole run)` — a
   * column headed "Probe" over that cell is simply wrong, and the two are the
   * only naming in the bank a screen reader reaches before the ids themselves.
   */
  it("heads the id column and the caption with `channel`, whatever the metric", () => {
    renderBank([seriesOf("(whole run)", [0.02, 0.03], "judge_usd")], {
      metric: "judge_usd",
    });

    expect(screen.getByRole("columnheader", { name: "Channel" })).toBeInTheDocument();
    expect(screen.getByRole("table").querySelector("caption")?.textContent).toMatch(
      /every channel in this pack/i,
    );
  });

  it("marks the selected channel with aria-pressed, not with colour alone", () => {
    renderBank([seriesOf("a", [0, 0]), seriesOf("b", [1, 1])], { selected: "a" });

    expect(screen.getByRole("button", { name: /^a$/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /^b$/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("selects a channel from the keyboard, because every row is a real key", async () => {
    const { onSelect } = renderBank([seriesOf("a", [0, 0]), seriesOf("b", [1, 1])], {
      selected: "a",
    });

    await userEvent.tab();
    await userEvent.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith("a");
  });

  /**
   * The trap. One reading has no change, and `+0.00` is a measurement this
   * channel never made — it would read as "steady across the history" when the
   * history is a single point.
   */
  it("says one reading rather than reporting a change of zero", () => {
    renderBank([seriesOf("solo", [0.5])]);

    const row = screen.getByRole("button", { name: /solo/ }).closest("tr")!;
    expect(row.querySelector('[data-metric="change"]')).toBeNull();
    expect(row.querySelector('[data-flatlined]')?.textContent).toMatch(/one reading/i);
  });

  it("signs the change so its direction is text rather than a hue", () => {
    renderBank([seriesOf("healed", [0, 1]), seriesOf("broke", [1, 0])]);

    expect(screen.getByText("+1.00")).toBeInTheDocument();
    expect(screen.getByText("-1.00")).toBeInTheDocument();
  });

  it("writes a flat channel as an unsigned zero, not as a rise of nothing", () => {
    renderBank([seriesOf("flat", [0, 0, 0])]);

    const row = screen.getByRole("button", { name: /flat/ }).closest("tr")!;
    expect(row.querySelector('[data-metric="change"]')?.textContent).toBe("0.00");
  });

  it("formats judge spend to four decimals so a sub-cent reading never reads as free", () => {
    renderBank([seriesOf("dear", [0.0042, 0.0091], "judge_usd")], {
      metric: "judge_usd",
    });

    expect(screen.getByText("$0.0042")).toBeInTheDocument();
    expect(screen.getByText("$0.0091")).toBeInTheDocument();
  });

  it("states what is absent in a channel that never read, rather than rendering blank", () => {
    renderBank([seriesOf("never-read", [])]);

    // `Flatline` requires a visible word for exactly this reason.
    const row = screen.getByRole("button", { name: /never-read/ }).closest("tr")!;
    expect(row.querySelectorAll("[data-flatlined]").length).toBeGreaterThan(0);
    expect(row.textContent).toMatch(/no readings/i);

    // The full reason travels as `title` and as screen-reader text — it is the
    // only place an empty cell names its own subject, and the noun is
    // `channel`, for the same reason the column head is. Asserted as whole
    // strings because un-renaming either one must redden this.
    const reasons = [...row.querySelectorAll("[data-flatlined]")].map((cell) =>
      cell.getAttribute("title"),
    );
    expect(reasons).toContain("no readable first for this channel");
    expect(reasons).toContain("no readable latest for this channel");
  });

  it("says the pack has no channels at all rather than rendering an empty table", () => {
    renderBank([]);

    expect(screen.getByText(/no channels/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("counts the readings behind each channel, because seven runs is not seven readings", () => {
    renderBank([seriesOf("gappy", [1, 0])]);

    const row = screen.getByRole("button", { name: /gappy/ }).closest("tr")!;
    expect(row.querySelector('[data-numeric="readings"]')?.textContent).toBe("2");
  });
});
