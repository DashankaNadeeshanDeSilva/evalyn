import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { matchRoutes, MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import { server } from "../../mocks/server";
import { NAV_DESTINATIONS, shippedDestinations, type NavDestination } from "../../nav";
import { appRoutes } from "../../routes";
import { META } from "../../mocks/fixtures";
import { AppShell } from "../AppShell";
import { RedactionBanner } from "../RedactionBanner";

const SHIPPED = NAV_DESTINATIONS.filter((d) => d.shipped);
const UNSHIPPED = NAV_DESTINATIONS.filter((d) => !d.shipped);

/**
 * Does a real page answer this path?
 *
 * The catch-all route matches everything, so `matchRoutes` alone would call
 * every destination resolved. A path that only reaches `*` has no page — which
 * is exactly the state the legend must not advertise.
 */
function hasPage(path: string): boolean {
  const matches = matchRoutes(appRoutes, path);
  const leaf = matches?.[matches.length - 1];
  return leaf !== undefined && leaf.route.path !== "*";
}

function renderShell() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/runs"]}>
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("the nav registry", () => {
  /**
   * The registry, stated in full.
   *
   * This assertion replaces `UNSHIPPED.length > 0`, which was a guard on the
   * guards: while some destination was unbuilt, the "unshipped labels must not
   * appear" loop below had something to iterate. Compare was the last one, so
   * that expectation could only be kept by refusing to ship a page — and
   * deleting it would have left the loop iterating an empty list, passing
   * however `shippedDestinations` broke.
   *
   * An inventory does not decay that way. Adding, removing, renaming,
   * reordering or re-flagging a destination reds here and names the difference,
   * and the iff test below then says which half of the change is missing. The
   * filter itself keeps a discriminating test of its own, against a registry
   * that still has an unshipped entry.
   */
  it("is exactly this inventory, in the operator's reading order", () => {
    expect(
      NAV_DESTINATIONS.map(
        (d) => `${d.path} ${d.label} ${d.shipped ? "shipped" : "unshipped"}`,
      ),
    ).toEqual([
      "/runs Runs shipped",
      "/launch Launch shipped",
      "/discoveries Discoveries shipped",
      "/compare Compare shipped",
      "/trends Trends shipped",
      "/trust Judge Trust shipped",
    ]);
  });

  it("keeps an unshipped destination out of the strip's source list", () => {
    const registry: NavDestination[] = [
      { path: "/built", label: "Built", shipped: true },
      { path: "/unbuilt", label: "Unbuilt", shipped: false },
    ];

    expect(shippedDestinations(registry).map((d) => d.path)).toEqual(["/built"]);
  });

  /**
   * The anti-404 invariant, and the reason `shipped` is a registry field rather
   * than markup: a legend listing destinations that 404 reads as broken
   * hardware. This asserts the flag cannot lie in *either* direction — flipping
   * `shipped` without adding the route reds, and adding a route without
   * flipping the flag reds too.
   */
  it("marks a destination shipped if and only if a route resolves it", () => {
    for (const destination of NAV_DESTINATIONS) {
      const resolved = hasPage(destination.path);
      expect(
        resolved,
        `${destination.path} is marked shipped=${destination.shipped} but ` +
          `the router ${resolved ? "has" : "has no"} page for it`,
      ).toBe(destination.shipped);
    }
  });
});

describe("AppShell", () => {
  it("is a thin legend strip, not a sidebar", () => {
    renderShell();

    const nav = screen.getByRole("navigation");
    // A `complementary`/aside landmark owning a column is the arrangement the
    // direction refuses; the strip is a banner-scoped nav.
    expect(nav.closest("header")).not.toBeNull();
    expect(document.querySelector("aside")).toBeNull();
  });

  it("renders only the destinations whose pages have shipped", () => {
    renderShell();

    const nav = screen.getByRole("navigation");
    for (const destination of SHIPPED) {
      expect(
        screen.getByRole("link", { name: destination.label }),
      ).toHaveAttribute("href", destination.path);
    }
    // Empty today, and re-arms by itself the moment a destination lands
    // unbuilt. The discriminating half of this rule lives on the filter above.
    for (const destination of UNSHIPPED) {
      expect(
        screen.queryByRole("link", { name: destination.label }),
        `${destination.label} has no page yet and must not appear in the legend`,
      ).toBeNull();
    }
    // Nothing else sneaks into the strip, and the reading order is the
    // registry's — a length alone would not have said that.
    expect(
      [...nav.querySelectorAll("a")].map((a) => a.getAttribute("href")),
    ).toEqual(SHIPPED.map((d) => d.path));
  });

  it("reads the server's own display-safe labels into the legend", async () => {
    renderShell();

    // The strip renders before the fetch settles, so wait for the readout to
    // fill rather than asserting against its own loading state.
    await waitFor(() =>
      expect(screen.getByTestId("meta-legend").textContent).toContain(
        META.version,
      ),
    );

    const legend = screen.getByTestId("meta-legend");
    expect(legend.textContent).toContain(META.runs_dir);
    // `runs_dir` arrives `~`-collapsed. A real home path here means something
    // reconstructed it client-side.
    expect(legend.textContent).not.toMatch(/\/(Users|home)\//);
  });

  /**
   * The error branch had no test at all: deleting `<IconAlert>` — the whole
   * remedy that stops "server unreachable" being colour alone — left the suite
   * green at 169/169. `tsc` catches a crude deletion through the unused import,
   * but a subtler change (a non-alarm glyph, `h-0`, an aria-hidden with no
   * text) passes both. The standard set in fix round 1 is that a design-review
   * fix ships with a test under it; this one did not.
   */
  it("says the server is unreachable with a glyph, not colour alone", async () => {
    server.use(
      http.get("/api/meta", () => HttpResponse.error()),
    );

    renderShell();

    const legend = await screen.findByText(/server unreachable/i);
    // The word is present...
    expect(legend.textContent).toMatch(/server unreachable/i);
    // ...and so is the mark, because red-on-grey alone is not a message.
    expect(
      legend.querySelector("svg"),
      "the unreachable state renders without a glyph — colour and word alone",
    ).not.toBeNull();
  });

  it("shows the redaction banner whenever the server says redaction is on", async () => {
    renderShell();

    expect(await screen.findByTestId("redaction-banner")).toBeInTheDocument();
  });
});

describe("RedactionBanner", () => {
  it("states what was scrubbed and how a redacted value reads", () => {
    render(
      <RedactionBanner
        redaction={{
          enabled: true,
          marker: "«redacted:<kind>»",
          reveal_required: true,
        }}
      />,
    );

    const banner = screen.getByTestId("redaction-banner");
    expect(banner.textContent).toContain("«redacted:<kind>»");
  });

  it("renders nothing at all when redaction is off", () => {
    render(
      <RedactionBanner
        redaction={{ enabled: false, marker: "", reveal_required: false }}
      />,
    );

    expect(screen.queryByTestId("redaction-banner")).toBeNull();
  });
});
