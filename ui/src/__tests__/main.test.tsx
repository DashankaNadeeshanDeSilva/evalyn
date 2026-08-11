import { describe, expect, it } from "vitest";

import { MOCK_PAGE_SIZE } from "../mocks/handlers";
import { META, RUN_SUMMARIES } from "../mocks/fixtures";

/**
 * End-to-end smoke over the whole seam: the entry module mounts React into
 * `#root`, the router lands on `/runs`, and the page fetches `/api/meta` and
 * `/api/runs` through the mock layer.
 *
 * Worth its keep because it is the one test that exercises the seam Tasks 8-21
 * stand on — types, MSW, TanStack Query, the router and the shell — rather than
 * any one piece of it. `main.tsx` runs its work at import time, so the import
 * *is* the act under test.
 */
describe("SPA entry point", () => {
  it("mounts into #root and renders the runs table from the mock API", async () => {
    document.body.innerHTML = '<div id="root"></div>';

    await import("../main");

    const root = document.getElementById("root")!;
    await vi.waitFor(() => {
      // `/` redirects to `/runs`, so the shell and its first page are both
      // live: the legend strip is mounted and the table has real rows in it.
      expect(root.querySelector("header nav")).not.toBeNull();
      expect(
        root.querySelectorAll('[data-testid="run-row"]').length,
      ).toBeGreaterThan(0);
    });

    // One page's worth of rows, because the cursor is only followed on demand.
    // Derived from the mock's own page size — never a literal row count.
    expect(root.querySelectorAll('[data-testid="run-row"]')).toHaveLength(
      Math.min(MOCK_PAGE_SIZE, RUN_SUMMARIES.length),
    );

    // The server's display-safe labels are rendered as sent: `~`-collapsed,
    // never an absolute home path reconstructed on the client.
    const legend = root.querySelector('[data-testid="meta-legend"]')!;
    expect(legend.textContent).toContain(META.version);
    expect(legend.textContent).toContain(META.runs_dir);
    expect(legend.textContent).not.toMatch(/\/(Users|home)\//);
  });
});
