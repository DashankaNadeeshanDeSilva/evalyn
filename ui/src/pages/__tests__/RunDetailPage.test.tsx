import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import { RUN_ID_GATE, RUN_ID_RUNNING } from "../../mocks/fixtures";
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
