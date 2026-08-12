import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import type { TrendSeries } from "../../api/types";
import { server } from "../../mocks/server";
import { Trends } from "../Trends";

/**
 * The trends page.
 *
 * The shipped MSW fixture is deliberately thin — two probes, one readable run
 * between them — because that is the *degenerate* state and it must render
 * honestly. The corpus-shaped dataset below is an override, not a replacement:
 * it mirrors what the real `twincore-injection` pack measures (an anchor probe
 * flat on the floor with a single blip, siblings that heal, and a probe whose
 * middle run is degraded and therefore skipped) so the drawing paths are
 * exercised against something the demo will actually meet.
 */

const RUNS = [
  "2026-08-01T09:00:00+00:00",
  "2026-08-02T09:00:00+00:00",
  "2026-08-03T09:00:00+00:00",
];

function corpus(): TrendSeries[] {
  const point = (i: number, value: number) => ({
    run_id: `2026080${i + 1}T090000-0000000${i + 1}-twincore-injection`,
    created_at: RUNS[i]!,
    value,
  });
  return [
    {
      pack_name: "example",
      probe_id: "injection-exfil-boundaries",
      metric: "pass_k",
      // Flat on the floor with one blip — the anchor.
      points: [point(0, 0), point(1, 1), point(2, 0)],
    },
    {
      pack_name: "example",
      probe_id: "injection-ignore-instructions",
      metric: "pass_k",
      // Healed, and its middle run is degraded so the server skipped it.
      points: [point(0, 0), point(2, 1)],
    },
    {
      pack_name: "example",
      probe_id: "grounding-work-history",
      metric: "pass_k",
      points: [point(0, 1), point(1, 1), point(2, 1)],
    },
  ];
}

function serveCorpus(series: TrendSeries[] = corpus()) {
  const asked: string[] = [];
  server.use(
    http.get("/api/trends", ({ request }) => {
      asked.push(new URL(request.url).search);
      return HttpResponse.json(series);
    }),
  );
  return asked;
}

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/trends"]}>
        <Trends />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Trends", () => {
  it("asks for the pack by NAME and for a metric it did not invent", async () => {
    const asked = serveCorpus();
    renderPage();

    await waitFor(() => expect(asked.length).toBeGreaterThan(0));
    // `PackRow.name` is what `?pack=` filters on server-side; `PackRow.path` is
    // a display-safe label that is never sent back.
    expect(asked[asked.length - 1]).toContain("pack=example");
    expect(asked[asked.length - 1]).toContain("metric=pass_k");
  });

  it("counts the probes, readings and runs it actually received", async () => {
    serveCorpus();
    renderPage();

    // 3 probes, 8 readings (3 + 2 + 3), 3 runs. Every figure derived — a
    // literal in the component would be wrong the day a run lands.
    //
    // Awaited rather than read once: while EITHER read is in flight the page
    // must say so, and asserting on the first render is what caught it
    // reporting "0 probes" before the allowlist had even landed.
    await waitFor(() =>
      expect(screen.getByTestId("trends-readout").textContent).toMatch(/3 probes/),
    );
    const readout = screen.getByTestId("trends-readout");
    expect(readout.textContent).toMatch(/8 readings/);
    expect(readout.textContent).toMatch(/3 runs/);
  });

  /**
   * Zero is a measurement, and before either read lands the client does not
   * have one. This is asserted on the FIRST render deliberately: the page
   * shipped its first draft reporting "0 probes · 0 readings · 0 runs" for
   * every frame before the pack allowlist arrived, which no `waitFor` would
   * ever have caught.
   */
  it("reports no count at all while either read is still in flight", () => {
    serveCorpus();
    renderPage();

    const readout = screen.getByTestId("trends-readout");
    expect(readout.textContent).toMatch(/reading/i);
    expect(readout.textContent).not.toMatch(/0 probes/);
  });

  /**
   * The announcement was inside the skeleton's own `aria-hidden` wrapper, so
   * the accessibility tree removed the whole subtree and the sentence with it.
   * Deleting the sentence outright reddened nothing — a guard that reads as
   * coverage and provides none.
   */
  it("announces the wait somewhere a screen reader can actually reach", () => {
    serveCorpus();
    renderPage();

    const note = screen.getByText(/reading the trend history/i);
    expect(
      note.closest('[aria-hidden="true"]'),
      "the announcement sits inside a subtree hidden from the accessibility tree",
    ).toBeNull();
  });

  it("opens on the most notable channel without a click", async () => {
    serveCorpus();
    renderPage();

    const anchor = await screen.findByRole("button", {
      name: /injection-exfil-boundaries/,
    });
    expect(anchor).toHaveAttribute("aria-pressed", "true");
    // ...and the scope is drawing that channel, not merely listing it.
    const title = document.querySelector("svg title");
    expect(title?.textContent).toMatch(/injection-exfil-boundaries/);
  });

  it("draws the channel the operator selects instead of the one it opened on", async () => {
    serveCorpus();
    renderPage();

    const other = await screen.findByRole("button", {
      name: /grounding-work-history/,
    });
    await userEvent.click(other);

    await waitFor(() => {
      expect(document.querySelector("svg title")?.textContent).toMatch(
        /grounding-work-history/,
      );
    });
  });

  it("re-asks the server when the metric detent moves, rather than converting", async () => {
    const asked = serveCorpus();
    renderPage();

    await waitFor(() => expect(asked.length).toBeGreaterThan(0));
    await userEvent.click(screen.getByRole("button", { name: /pass@k/i }));

    await waitFor(() =>
      expect(asked[asked.length - 1]).toContain("metric=pass_at_k"),
    );
  });

  it("says the history could not be read, with a glyph rather than colour alone", async () => {
    server.use(http.get("/api/trends", () => HttpResponse.error()));
    renderPage();

    const message = await screen.findByTestId("trends-error");
    expect(message.textContent).toMatch(/could not/i);
    expect(
      message.querySelector("svg"),
      "the failed-read branch renders without a glyph",
    ).not.toBeNull();
  });

  /**
   * Against the shipped fixture rather than the override: two probes, both
   * read in the same single run. A chart drawn from one x value is a dot on a
   * degenerate axis, and the page has to say so instead of drawing it.
   */
  it("refuses to plot a single readable run and still lists its readings", async () => {
    renderPage();

    expect(await screen.findByText(/one readable run/i)).toBeInTheDocument();
    expect(document.querySelector("svg.recharts-surface")).toBeNull();

    const bank = screen.getByRole("table");
    expect(
      within(bank).getByRole("button", { name: /injection-ignore-instructions/ }),
    ).toBeInTheDocument();
  });

  it("names the pack it is reading, so two servers are never confused", async () => {
    serveCorpus();
    renderPage();

    const pack = await screen.findByTestId("trends-pack");
    await waitFor(() =>
      expect(within(pack).getByRole("button", { name: /example/i })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
  });
});
