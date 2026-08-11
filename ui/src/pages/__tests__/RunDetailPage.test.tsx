import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import type { RunDetail } from "../../api/types";
import {
  DETAIL_RUNNING,
  RUN_ID_GATE,
  RUN_ID_RUNNING,
} from "../../mocks/fixtures";
import { server } from "../../mocks/server";
import {
  onlySocket,
  useFakeEventSource,
} from "../../test/fakeEventSource";
import { RunDetailPage } from "../RunDetailPage";

useFakeEventSource();

function renderPage(runId: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/runs/${runId}`]}>
        <Routes>
          <Route path="/runs/:runId" element={<RunDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Both of this page's error branches carry an alarm glyph so the failure is
 * never colour alone, and neither had a test: deleting `<IconAlert>` from both
 * left the suite green at 174/174, caught only by `tsc`'s unused import.
 */
describe("RunDetailPage", () => {
  it("says the artifact could not be read with a glyph, not colour alone", async () => {
    server.use(http.get("/api/runs/:runId", () => HttpResponse.error()));

    renderPage(RUN_ID_GATE);

    const message = await screen.findByText(/could not reach its server/i);
    expect(message.textContent).toMatch(/could not reach its server/i);
    expect(
      message.querySelector("svg"),
      "the unreadable-artifact branch renders without a glyph — colour and word alone",
    ).not.toBeNull();
  });

  it("refuses a malformed run id with a glyph, not colour alone", async () => {
    renderPage("not-a-run-id");

    const message = await screen.findByText(/that is not a run id/i);
    expect(message.textContent).toMatch(/that is not a run id/i);
    expect(
      message.querySelector("svg"),
      "the malformed-id branch renders without a glyph — colour and word alone",
    ).not.toBeNull();
  });
});

/**
 * The seam between the page and the one inset window, which nothing exercised
 * until review pointed it out.
 *
 * `LiveBanner` and `ControlButtons` were covered, and `LiveRunPanel` was
 * covered — but no fixture carried `running`, so `live` was never once passed
 * as `true` from this page. Deleting `enabled: !live` from `GateRunDetail` left
 * the whole suite green: a live run would have fired `evaluate_gate` at an
 * artifact that does not exist yet, and rendered "the gate verdict could not be
 * evaluated" over a perfectly healthy run — in front of the room.
 */
describe("a run that is still on the air", () => {
  it("shows the live window and refuses to ask for a verdict that cannot exist", async () => {
    let gateAsked = false;
    server.use(
      http.get("/api/runs/:runId/gate", () => {
        gateAsked = true;
        return HttpResponse.json({
          run_id: RUN_ID_RUNNING,
          exit_code: 0,
          failures: [],
          quarantined: [],
          report_md: "",
          baseline_run_id: null,
          redacted: false,
        });
      }),
    );

    renderPage(RUN_ID_RUNNING);

    // The one dark field appears, and it subscribed to this run's own stream.
    expect(await screen.findByTestId("live-window")).toBeInTheDocument();
    expect(onlySocket().url).toBe(
      `/api/runs/${encodeURIComponent(RUN_ID_RUNNING)}/events`,
    );

    // The verdict is stated as absent rather than fetched, failed, or faked.
    expect(await screen.findByTestId("gate-banner-pending")).toBeInTheDocument();
    expect(screen.queryByTestId("gate-banner")).toBeNull();
    expect(screen.queryByTestId("gate-banner-error")).toBeNull();
    expect(
      gateAsked,
      "a live run has no artifact, so asking evaluate_gate about it is the bug",
    ).toBe(false);
  });

  it("keeps one spend readout on screen, not two that disagree", async () => {
    renderPage(RUN_ID_RUNNING);

    await screen.findByTestId("live-window");
    // The artifact-derived field would flat-line "unrecorded" directly beneath
    // a window reporting real streaming spend — two readouts disagreeing about
    // money, on the screen that carries the Cancel key.
    expect(screen.queryByTestId("cost-chip")).toBeNull();

    // The live figure arrives, against the pack ceiling read from the allowlist.
    onlySocket().emit(1, "run.started", { run_id: RUN_ID_RUNNING });
    onlySocket().emit(2, "spend.updated", { judge_usd: 0.5 });

    const window = screen.getByTestId("live-window");
    expect(window.querySelector('[data-numeric="judge_usd"]')?.textContent).toBe(
      "$0.5000",
    );
    await waitFor(() => expect(window.textContent).toContain("of $2.0000"));
  });

  it("hands the finished run back to the artifact", async () => {
    renderPage(RUN_ID_RUNNING);
    await screen.findByTestId("live-window");

    onlySocket().emit(1, "run.finished", {
      run_id: RUN_ID_RUNNING,
      exit_code: 3,
    });

    // The window stays — "or has just finished" — and carries the exit code...
    const window = screen.getByTestId("live-window");
    expect(window.getAttribute("data-phase")).toBe("finished");
    expect(window.querySelector('[data-numeric="exit_code"]')?.textContent).toBe(
      "3",
    );
    // ...and the socket is closed rather than left replaying the run forever.
    expect(onlySocket().closed).toBe(true);
  });
});

/**
 * The transition, which no fixture could reach.
 *
 * `RUN_DETAILS[RUN_ID_RUNNING]` answers `running` forever, so every test above
 * watches a run that never settles — and the state that arrives about three and
 * a half minutes into the demo, when the artifact lands and the status flips,
 * was covered by nothing at all. It was also broken: two signals answered "is
 * this live", one recomputed on the page and one latched in the panel, and they
 * diverged in exactly this frame.
 *
 * The handler below is the minimum needed to let a run actually finish: a
 * mutable body the test advances between renders, the way the real server's
 * index does when `derive_status` starts seeing an artifact instead of a
 * sidecar.
 */
function servingRun(): { settle: (patch: Partial<RunDetail>) => void } {
  let body: RunDetail = DETAIL_RUNNING;
  server.use(http.get("/api/runs/:runId", () => HttpResponse.json(body)));
  return {
    settle: (patch) => {
      body = { ...DETAIL_RUNNING, ...patch };
    },
  };
}

/**
 * Every component reporting spend, from either side. Must always be exactly one.
 *
 * Counted by reporter rather than by figure on purpose: `CostChip` renders no
 * numeral at all when the artifact recorded nothing, and "unrecorded" beside a
 * streamed figure is precisely the state this must catch.
 */
function spendReporters(): Element[] {
  return [
    ...document.querySelectorAll(
      '[data-testid="cost-chip"], [data-testid="live-spend"]',
    ),
  ];
}

describe("a run that finishes while the operator is watching", () => {
  it("hands the spend readout to the artifact without ever showing two", async () => {
    const artifact = servingRun();
    renderPage(RUN_ID_RUNNING);
    await screen.findByTestId("live-window");

    onlySocket().emit(1, "run.started", { run_id: RUN_ID_RUNNING });
    onlySocket().emit(2, "spend.updated", { judge_usd: 0.5 });

    // While it runs, the stream reports — one figure, and it carries the
    // ceiling the pack allows.
    expect(spendReporters()).toHaveLength(1);
    expect(screen.getByTestId("live-window").textContent).toContain("$0.5000");
    await waitFor(() =>
      expect(screen.getByTestId("live-window").textContent).toContain(
        "of $2.0000",
      ),
    );

    // The artifact lands, and the refetch this panel fires brings it back.
    artifact.settle({ status: "gate_failed", judge_usd: 0.5137 });
    onlySocket().emit(3, "run.finished", {
      run_id: RUN_ID_RUNNING,
      exit_code: 1,
    });

    await waitFor(() => expect(screen.getByTestId("cost-chip")).toBeInTheDocument());
    // Still exactly one, and now it is the authoritative figure rather than the
    // streamed one — they are not the same number.
    expect(spendReporters()).toHaveLength(1);
    expect(screen.getByTestId("cost-chip").textContent).toContain("$0.5137");
    expect(screen.getByTestId("cost-chip").textContent).toContain("$2.0000");

    // ...and the window survived the transition with its exit code, which is
    // the whole reason the presence decision is latched separately.
    const window = screen.getByTestId("live-window");
    expect(window.getAttribute("data-phase")).toBe("finished");
    expect(window.querySelector('[data-numeric="exit_code"]')?.textContent).toBe(
      "1",
    );
  });

  /**
   * The worse case, and the one the invariant comment names by hand: an
   * artifact that recorded no spend. Divergence here put the word "unrecorded"
   * on screen beside a real figure from the stream.
   */
  it("never puts an unrecorded spend beside a real one", async () => {
    const artifact = servingRun();
    renderPage(RUN_ID_RUNNING);
    await screen.findByTestId("live-window");

    onlySocket().emit(1, "spend.updated", { judge_usd: 0.5 });
    artifact.settle({ status: "gate_failed", judge_usd: null });
    onlySocket().emit(2, "run.finished", {
      run_id: RUN_ID_RUNNING,
      exit_code: 1,
    });

    await waitFor(() => expect(screen.getByTestId("cost-chip")).toBeInTheDocument());
    expect(spendReporters()).toHaveLength(1);
    expect(screen.getByTestId("cost-chip").textContent).toContain("unrecorded");
    // The streamed figure is gone rather than contradicting it.
    expect(document.body.textContent).not.toContain("$0.5000");
  });
});
