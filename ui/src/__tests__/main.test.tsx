import { describe, expect, it } from "vitest";

import { META } from "../mocks/fixtures";

/**
 * End-to-end smoke over the whole scaffold: the entry module mounts React into
 * `#root` and reads `/api/meta` through the mock layer.
 *
 * Worth its keep because it is the one test that exercises the seam Tasks 8–21
 * actually stand on — types, MSW, and a React root — rather than any one piece
 * of it. `main.tsx` runs its work at import time, so the import *is* the act
 * under test.
 */
describe("SPA entry point", () => {
  it("mounts into #root and renders the meta line from the mock API", async () => {
    document.body.innerHTML = '<div id="root"></div>';

    await import("../main");

    const root = document.getElementById("root")!;
    // Wait for the mount and the /api/meta round trip to settle.
    await vi.waitFor(() => {
      expect(root.textContent).toContain("Evalyn");
      expect(document.getElementById("meta")!.textContent).toContain(
        META.version,
      );
    });

    // The runs_dir is rendered as the display-safe label the server sent —
    // `~`-collapsed, never an absolute home path.
    const meta = document.getElementById("meta")!.textContent!;
    expect(meta).toContain(META.runs_dir);
    expect(meta).not.toMatch(/\/(Users|home)\//);
  });
});
