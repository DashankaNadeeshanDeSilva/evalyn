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
 *
 * ---------------------------------------------------------------------------
 * DEFERRED — Task 21 Steps 4, 5, 6 and 7 are NOT built
 * ---------------------------------------------------------------------------
 *
 * This file is the closest thing the SPA has to an end-to-end smoke, so the
 * obligation is recorded here rather than only in a report. Nothing below is
 * stubbed, simulated or partially wired to make any of it look done: there is
 * no `ui/e2e/` directory, no Playwright dependency, no `ui-e2e` CI job, and
 * `pyproject.toml` is still at its pre-Plan-#4 version.
 *
 * **Step 4 — the Playwright smoke (`ui/e2e/smoke.spec.ts`), chromium only.**
 * Prerequisites: Tasks 6 and 7 (the `evalyn ui` server and its read endpoints)
 * and Task 20 (the launcher, control and SSE endpoints). There is no server to
 * point a browser at today. When they land, the smoke must: start `evalyn ui`;
 * launch a **gate** run against the toy target from the launch console; watch
 * it reach a terminal state; open a transcript; open Discoveries and assert the
 * TwinCore sentinel address is **absent** from the default response.
 *
 * **Step 5 — CI stage S4, the `ui-e2e` job.** Prerequisite: Step 4. Add the job
 * to `.github/workflows/ci.yml` gated on `if: github.event_name ==
 * 'pull_request'`, with the Playwright browsers cached on
 * `~/.cache/ms-playwright`.
 *
 * **Step 6 — docs and the version bump.** Prerequisite: the plan being
 * finished. Document `evalyn ui` in `README.md` including that redaction is
 * default-on and revealing is deliberate; update `CONTEXT.md` and `ROADMAP.md`;
 * add the Plan #4 journal section; bump to **v0.5.0** and move the
 * version-guard test with it. Bumping now would claim a release that does not
 * exist.
 *
 * **Step 7 — the wheel test.** Prerequisite: Task 10 (packaging). `uv build`,
 * then `pip install 'dist/evalyn-*.whl[ui]'` into a clean venv; assert the
 * committed bundle is present under `site-packages` and that
 * `evalyn ui --port 0 --no-open` starts; prove Node-independence with `env -i`.
 *
 * The live-path deferrals for what **is** built are recorded beside the code
 * they belong to: `hooks/useRunEvents.ts`, `components/LiveRunPanel.tsx`,
 * `components/__tests__/LiveRunPanel.test.tsx` and `pages/Launch.tsx`.
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
