import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import { server } from "../../mocks/server";
import { RunsPage } from "../RunsPage";

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/runs"]}>
        <RunsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RunsPage", () => {
  /**
   * The failed-read branch had no test at all: deleting `<IconAlert>` — the
   * glyph that stops "the index could not be read" being colour alone — left
   * the suite green at 174/174. `tsc` catches the crude deletion through the
   * unused import, but a subtler change (a non-alarm glyph, `h-0`, an
   * aria-hidden with no text) passes both. Fix round 1 set the standard that a
   * design-review fix ships with a test under it; this one did not.
   */
  it("says the index could not be read with a glyph, not colour alone", async () => {
    server.use(http.get("/api/runs", () => HttpResponse.error()));

    renderPage();

    const message = await screen.findByText(/could not reach its server/i);
    // The word is present...
    expect(message.textContent).toMatch(/could not reach its server/i);
    // ...and so is the mark, because red-on-grey alone is not a message.
    expect(
      message.querySelector("svg"),
      "the failed-read branch renders without a glyph — colour and word alone",
    ).not.toBeNull();
  });
});
