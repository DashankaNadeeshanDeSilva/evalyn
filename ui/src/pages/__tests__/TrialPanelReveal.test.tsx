import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../api/client";
import { PROBE_ID_EXFIL, RUN_ID_GATE } from "../../mocks/fixtures";
import { RunDetailPage } from "../RunDetailPage";

/**
 * Opening a trial panel has to *land* somewhere the operator can see.
 *
 * Found by a human in a live rehearsal, not by a test: the drill-down keys sit
 * on a probe row, and the panel they open renders **below the whole probe
 * table**. Measured in the browser at the time — the clicked row at document
 * top 2258, the panel's own heading at 2822, in an 891px viewport. So the
 * panel opened 565px past the bottom edge, nothing scrolled, and focus stayed
 * on the page root. The operator clicks and sees nothing happen; a screen
 * reader announces nothing either. On the demo's click path.
 *
 * Both halves of the fix are pinned here, because either one alone still fails
 * somebody: bringing the panel into view without moving focus leaves a screen
 * reader where it was, and moving focus without bringing it into view is only
 * accidentally correct (a browser scrolls to the focused element, but not with
 * a reduced-motion-aware behaviour and not when `preventScroll` is asked for).
 *
 * The distance is a *layout* fact, so no assertion here measures pixels —
 * jsdom has no layout at all. What is asserted is the reveal itself: the panel
 * element was asked to come into view, and it holds focus afterwards.
 */

/** Every `scrollIntoView` the render performed, with what it was asked for. */
const revealed: { element: Element; options: unknown }[] = [];

beforeEach(() => {
  revealed.length = 0;
  vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(function (
    this: Element,
    options?: unknown,
  ) {
    revealed.push({ element: this, options });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/runs/${RUN_ID_GATE}`]}>
        <Routes>
          <Route path="/runs/:runId" element={<RunDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function probeRow() {
  return await screen.findByTestId(`probe-row-${PROBE_ID_EXFIL}`);
}

/** The one entry that brought `element` into view, or a readable failure. */
function revealOf(element: Element) {
  const entry = revealed.find((call) => call.element === element);
  if (!entry) {
    throw new Error(
      "the opened panel was never brought into view — it renders below the " +
        "probe table and the operator sees nothing happen",
    );
  }
  return entry;
}

describe("an opened trial panel comes to the operator", () => {
  it("brings the single-trial panel into view and moves focus to it", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(within(await probeRow()).getAllByTestId("trial-key")[0]!);
    const panel = await screen.findByTestId("trial-panel");

    expect(revealOf(panel).options).toMatchObject({ block: "start" });
    expect(
      panel,
      "focus stayed where it was, so a screen reader was told nothing",
    ).toHaveFocus();
  });

  it("brings the all-trials panel into view and moves focus to it", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(within(await probeRow()).getByTestId("all-trials-key"));
    const panel = await screen.findByTestId("all-trials-panel");

    expect(revealOf(panel).options).toMatchObject({ block: "start" });
    expect(panel).toHaveFocus();
  });

  /**
   * The panel is not remounted when the operator moves from trial 1 to trial 4
   * — same component, same position in the tree, only a prop changed. So a
   * reveal written as a mount-only effect works exactly once and then goes
   * quiet for every subsequent key on the row, which is the more common
   * gesture.
   */
  it("reveals again when the operator moves to another trial", async () => {
    const user = userEvent.setup();
    renderPage();

    const keys = within(await probeRow()).getAllByTestId("trial-key");
    await user.click(keys[0]!);
    const panel = await screen.findByTestId("trial-panel");
    expect(panel.dataset["epoch"]).toBe("1");

    revealed.length = 0;
    await user.click(keys[3]!);
    await screen.findByTestId("trial-panel");
    expect(
      screen.getByTestId("trial-panel").dataset["epoch"],
      "the fixture stopped having a fourth trial, so this proves nothing",
    ).toBe("4");

    expect(revealOf(screen.getByTestId("trial-panel")).options).toMatchObject({
      block: "start",
    });
    expect(screen.getByTestId("trial-panel")).toHaveFocus();
  });
});

describe("the reveal respects a reduced-motion preference", () => {
  /** jsdom ships no `matchMedia` either, so the query is answered here. */
  function withReducedMotion(reduce: boolean) {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("prefers-reduced-motion") ? reduce : false,
      media: query,
    }));
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("travels smoothly when no reduced-motion preference is set", async () => {
    withReducedMotion(false);
    const user = userEvent.setup();
    renderPage();

    await user.click(within(await probeRow()).getAllByTestId("trial-key")[0]!);
    const panel = await screen.findByTestId("trial-panel");

    expect(revealOf(panel).options).toMatchObject({ behavior: "smooth" });
  });

  it("arrives instantly when the operator asked for reduced motion", async () => {
    withReducedMotion(true);
    const user = userEvent.setup();
    renderPage();

    await user.click(within(await probeRow()).getAllByTestId("trial-key")[0]!);
    const panel = await screen.findByTestId("trial-panel");

    expect(
      revealOf(panel).options,
      "a smooth scroll was animated at an operator who asked for none",
    ).toMatchObject({ behavior: "auto" });
  });
});
