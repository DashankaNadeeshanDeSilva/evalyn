import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { matchRoutes, MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import { NAV_DESTINATIONS } from "../../nav";
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
  it("still has an unshipped destination, so the gating assertions bite", () => {
    expect(SHIPPED.length).toBeGreaterThan(0);
    expect(UNSHIPPED.length).toBeGreaterThan(0);
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
    for (const destination of UNSHIPPED) {
      expect(
        screen.queryByRole("link", { name: destination.label }),
        `${destination.label} has no page yet and must not appear in the legend`,
      ).toBeNull();
    }
    // Nothing else sneaks into the strip either.
    expect(nav.querySelectorAll("a")).toHaveLength(SHIPPED.length);
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
