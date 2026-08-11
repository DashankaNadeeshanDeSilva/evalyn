import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import { RUN_ID_GATE } from "../../mocks/fixtures";
import { server } from "../../mocks/server";
import { RunDetailPage } from "../RunDetailPage";

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
