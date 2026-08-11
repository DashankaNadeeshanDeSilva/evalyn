import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import type { PackListPage } from "../../api/types";
import { META, PACKS, RUN_ID_GATE } from "../../mocks/fixtures";
import { server } from "../../mocks/server";
import { Launch } from "../Launch";

/**
 * The launch console — the one page that spends money.
 *
 * ---------------------------------------------------------------------------
 * DEFERRED VERIFICATION — owed to Task 20 (the launcher and control endpoints)
 * ---------------------------------------------------------------------------
 *
 * `POST /api/runs` does not exist yet; every test below runs against Task 5's
 * MSW handler, which mirrors the two refusals that matter but is otherwise
 * thinner than the real launcher. Nothing here is stubbed to make a deferred
 * step look done. Against a real `evalyn ui`, the wiring pass must verify:
 *
 * 1. The 202's `run_id` is the stem of the artifact that later appears, so the
 *    navigation this page performs lands on the run that actually started.
 * 2. `GET /api/runs/{id}` answers for that run **before** its artifact exists —
 *    otherwise this page navigates straight into a "could not be read" alarm.
 * 3. A second concurrent launch answers 409 `busy` and renders as a sentence.
 * 4. A `discover` request above the pack's ceiling is clamped **down** by the
 *    server, never up, and the started run reports the clamped figure.
 * 5. A body carrying a pack **path** is rejected by `extra="forbid"` upstream
 *    of any handler. This page only ever sends `pack_id`, and that is the
 *    property to re-check after any edit here.
 * 6. `baseline_run_id` is absent from every request this page builds, so a gate
 *    launched from the browser diffs against nothing. The demo's red-diff beat
 *    needs a baseline picker *and* a committed baseline; neither exists.
 */

function renderLaunch() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/launch"]}>
        <Routes>
          <Route path="/launch" element={<Launch />} />
          <Route
            path="/runs/:runId"
            element={<div data-testid="landed">run detail</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Captures the body the page actually sends, and answers the way Task 20 will. */
function captureLaunch(): { body: Record<string, unknown> | null } {
  const captured: { body: Record<string, unknown> | null } = { body: null };
  server.use(
    http.post("/api/runs", async ({ request }) => {
      captured.body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ run_id: RUN_ID_GATE }, { status: 202 });
    }),
  );
  return captured;
}

async function armGate(user: ReturnType<typeof userEvent.setup>) {
  const pack = PACKS[0]!;
  await user.click(await screen.findByTestId("pack-key"));
  await user.type(screen.getByLabelText(/Type example/), pack.name);
  return pack;
}

describe("the launch console", () => {
  /**
   * `GET /api/packs` is the `{items, next_cursor}` envelope, not a bare array —
   * a frozen top-level array could never grow a field. Reading it as an array
   * has already cost this branch a merge repair, so this asserts the row
   * actually renders: an array read would map over an object and throw.
   */
  it("reads the pack allowlist out of the envelope", async () => {
    renderLaunch();

    const key = await screen.findByTestId("pack-key");
    expect(key.getAttribute("data-pack-id")).toBe(PACKS[0]!.id);
    expect(key.textContent).toContain(PACKS[0]!.name);
    // The display-safe label is rendered as sent, `~`-collapsed. A real home
    // path here would mean something reconstructed it client-side.
    expect(key.textContent).toContain(PACKS[0]!.path);
    expect(key.textContent).not.toMatch(/\/(Users|home)\//);
  });

  it("refuses to arm until the pack's name is typed exactly", async () => {
    const user = userEvent.setup();
    renderLaunch();

    await user.click(await screen.findByTestId("pack-key"));
    const key = screen.getByTestId("safety-key");
    expect(key).toBeDisabled();
    expect(screen.getByTestId("launch-refusal").textContent).toContain(
      PACKS[0]!.name,
    );

    await user.type(screen.getByLabelText(/Type example/), "exampl");
    expect(screen.getByTestId("safety-key")).toBeDisabled();

    await user.type(screen.getByLabelText(/Type example/), "e");
    expect(screen.getByTestId("safety-key")).toBeEnabled();
    expect(screen.queryByTestId("launch-refusal")).toBeNull();
  });

  it("names the pack by id and echoes its name, then follows the run it started", async () => {
    const user = userEvent.setup();
    const captured = captureLaunch();
    renderLaunch();

    const pack = await armGate(user);
    await user.click(screen.getByTestId("safety-key"));

    await waitFor(() => expect(screen.getByTestId("landed")).toBeInTheDocument());
    expect(captured.body).toEqual({
      mode: "gate",
      pack_id: pack.id,
      confirm: pack.name,
    });
    // Never a path: `id` indexes the start-time allowlist, and it is the only
    // thing that may name a pack on the wire.
    expect(JSON.stringify(captured.body)).not.toContain(pack.path);
  });

  it("will not launch a discover run without a stated ceiling", async () => {
    const user = userEvent.setup();
    renderLaunch();

    await armGate(user);
    await user.click(screen.getByRole("button", { name: /^discover/ }));

    expect(screen.getByTestId("safety-key")).toBeDisabled();
    expect(screen.getByTestId("launch-refusal").textContent).toContain(
      "may spend",
    );
  });

  it("sends the ceiling the operator chose, and says the server clamps it down", async () => {
    const user = userEvent.setup();
    const captured = captureLaunch();
    renderLaunch();

    const pack = await armGate(user);
    await user.click(screen.getByRole("button", { name: /^discover/ }));
    await user.type(screen.getByLabelText(/most this discover run may spend/), "1.5");

    await waitFor(() =>
      expect(screen.getByText(/clamps this figure down/)).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("safety-key"));

    await waitFor(() => expect(screen.getByTestId("landed")).toBeInTheDocument());
    expect(captured.body).toEqual({
      mode: "discover",
      pack_id: pack.id,
      confirm: pack.name,
      max_usd: 1.5,
    });
  });

  /**
   * The same rule the legend strip follows for unshipped destinations: a
   * control that cannot do what it says reads as broken hardware. Compare pairs
   * two existing artifacts and this console has no picker for them, so the
   * detent is present, refused, and says why.
   */
  it("shows the mode it cannot launch, disabled, with the reason stated", async () => {
    renderLaunch();

    const compare = await screen.findByRole("button", { name: /^compare/ });
    expect(compare).toBeDisabled();
    expect(screen.getByTestId("mode-refusal-compare").textContent).toContain(
      "no picker for them yet",
    );
  });

  it("refuses discover outright when the server was not started for it", async () => {
    server.use(
      http.get("/api/meta", () =>
        HttpResponse.json({ ...META, allow_discover: false }),
      ),
    );
    renderLaunch();

    // Refused before `/api/meta` answers too, and for a different stated
    // reason: unknown is not permission on the one page that spends money.
    expect(screen.getByTestId("mode-refusal-discover").textContent).toContain(
      "has not reported",
    );

    await waitFor(() =>
      expect(screen.getByTestId("mode-refusal-discover").textContent).toContain(
        "--allow-discover",
      ),
    );
    expect(screen.getByRole("button", { name: /^discover/ })).toBeDisabled();
  });

  it("says what to do when the server was started with no allowlist at all", async () => {
    server.use(
      http.get("/api/packs", () => {
        const body: PackListPage = { items: [], next_cursor: null };
        return HttpResponse.json(body);
      }),
    );
    renderLaunch();

    // The problem and the recovery, not an empty list.
    expect(
      await screen.findByText(/no pack allowlist/),
    ).toBeInTheDocument();
    expect(screen.getByText(/evalyn ui --target/)).toBeInTheDocument();
  });

  it("renders a refused launch with a glyph, not colour alone", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/runs", () =>
        HttpResponse.json(
          {
            error: {
              code: "busy",
              message: "another run is already in flight",
              detail: null,
            },
          },
          { status: 409 },
        ),
      ),
    );
    renderLaunch();

    await armGate(user);
    await user.click(screen.getByTestId("safety-key"));

    const alarm = await screen.findByTestId("launch-error");
    expect(alarm.textContent).toContain("another run is already in flight");
    expect(alarm.querySelector("svg")).not.toBeNull();
    // It stayed put: a refused launch must not navigate anywhere.
    expect(screen.queryByTestId("landed")).toBeNull();
  });
});
