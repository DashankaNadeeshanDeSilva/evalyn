import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import type { PackListPage } from "../../api/types";
import { META, PACKS, RUN_ID_RUNNING } from "../../mocks/fixtures";
import { server } from "../../mocks/server";
import { onlySocket, useFakeEventSource } from "../../test/fakeEventSource";
import { Launch } from "../Launch";
import { RunDetailPage } from "../RunDetailPage";

// The live window only exists if something can subscribe to a stream, and jsdom
// ships no `EventSource`.
useFakeEventSource();

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

/**
 * Captures the body the page actually sends, and answers the way the real
 * launcher does: a **pending** id, minted before the child process starts.
 */
function captureLaunch(): { body: Record<string, unknown> | null } {
  const captured: { body: Record<string, unknown> | null } = { body: null };
  server.use(
    http.post("/api/runs", async ({ request }) => {
      captured.body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ run_id: RUN_ID_RUNNING }, { status: 202 });
    }),
  );
  return captured;
}

/**
 * A server started **with** `--allow-discover`.
 *
 * `MetaResponse.allow_discover` is `False` in `models.py` and the fixture now
 * says so too, so a discover launch is a deliberate server configuration a test
 * must state — exactly as the operator must state it on the command line. It
 * used to be the fixture's default, which is why the refusal below was the only
 * discover branch anyone had ever seen against a default server.
 */
function allowingDiscover() {
  server.use(
    http.get("/api/meta", () =>
      HttpResponse.json({ ...META, allow_discover: true }),
    ),
  );
}

/** Waits for `/api/meta` to arrive, since unknown is not permission. */
async function selectDiscover(user: ReturnType<typeof userEvent.setup>) {
  const discover = screen.getByRole("button", { name: /^discover/ });
  await waitFor(() => expect(discover).toBeEnabled());
  await user.click(discover);
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

  /**
   * The branch that had never rendered.
   *
   * `TargetSpec` carries no version field, so `pack_rows` sends `null` for
   * every pack a real server can list — but the fixture said `"1.0.0"`, so the
   * only rendition this row ever had was `v1.0.0`, a string no server has ever
   * sent. The same fixture claimed a calibration record that neither shipped
   * pack has.
   */
  it("states a pack with no version as unversioned rather than inventing one", async () => {
    renderLaunch();

    const key = await screen.findByTestId("pack-key");
    expect(key.textContent).toContain("unversioned");
    expect(key.textContent).not.toMatch(/v\d/);
    expect(key.textContent).toContain("no calibration record");
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
    allowingDiscover();
    renderLaunch();

    await armGate(user);
    await selectDiscover(user);

    expect(screen.getByTestId("safety-key")).toBeDisabled();
    expect(screen.getByTestId("launch-refusal").textContent).toContain(
      "may spend",
    );
  });

  it("sends the ceiling the operator chose, and says the server clamps it down", async () => {
    const user = userEvent.setup();
    const captured = captureLaunch();
    allowingDiscover();
    renderLaunch();

    const pack = await armGate(user);
    await selectDiscover(user);
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
    // Stated rather than inherited: this is the default a real server answers,
    // and the test says which server it is talking to either way.
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

  /**
   * The regression the browser caught and nothing held.
   *
   * An input's border is the **only** thing identifying it as a control, so
   * WCAG 1.4.11 applies at 3:1. The first draft used chassis-400, which
   * measures **2.30** on the face — the step `ScenarioTable` already documents
   * as too light for a control's edge. chassis-500 measures **4.03**.
   *
   * This is asserted here rather than in the contrast guard on purpose: that
   * guard reads `text-` and `bg-` prefixes only and structurally cannot see a
   * border, and widening it to a general border axis is a design decision with
   * real cost, not a fix (ruling R4-24, and the same parking as before).
   */
  it("bounds its text fields with an edge that clears the 3:1 bar", async () => {
    const user = userEvent.setup();
    allowingDiscover();
    renderLaunch();

    await armGate(user);
    expect(screen.getByLabelText(/Type example/).getAttribute("class")).toContain(
      "border-chassis-500",
    );

    await selectDiscover(user);
    expect(
      screen
        .getByLabelText(/most this discover run may spend/)
        .getAttribute("class"),
    ).toContain("border-chassis-500");
  });

  /**
   * The wiring pass read this off the screen against a real server: every
   * launch refusal ended in the literal word **`(undefined)`**.
   *
   * `ApiError.detail` is `str | None = None` in `models.py`, and the server
   * renders the envelope with `exclude_none=True` (`ui/redact.py`) — so a
   * refusal with no extra context **omits the key** rather than sending null.
   * The page guarded with `=== null`, which is false for `undefined`, and the
   * MSW handler defaulted the field to `null`, which is why nothing ever
   * caught it. The body below is the real server's, key-for-key.
   */
  it("renders a refusal whose detail the server omitted, without the word undefined", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/runs", () =>
        HttpResponse.json(
          {
            error: {
              code: "launch_refused",
              message: "pack 'example' is not on this server's --target allowlist",
            },
          },
          { status: 400 },
        ),
      ),
    );
    renderLaunch();

    await armGate(user);
    await user.click(screen.getByTestId("safety-key"));

    const alarm = await screen.findByTestId("launch-error");
    expect(alarm.textContent).toContain("not on this server's --target allowlist");
    // This is the sentence the operator reads when a launch fails on stage.
    expect(alarm.textContent).not.toContain("undefined");
    expect(alarm.textContent).not.toContain("()");
  });

  /**
   * The coverage hole the mock dug, and the one the wiring pass fell into.
   *
   * `POST /api/runs` returned the **already-finished** `RUN_ID_GATE`, so every
   * launch this suite has ever performed navigated to a terminal run:
   * `LiveRunPanel` latched `watched = false` and returned `null`, and the one
   * inset window **has never mounted in a launch test**. The real server mints
   * a pending id — the stem of an artifact that does not exist yet — and the
   * panel mounts on arrival, which is the whole shape of the demo's first
   * minute.
   *
   * Nothing is overridden below: the default handler is under test, because the
   * default handler is what lied.
   */
  it("lands on a run that is still on the air, with the live window mounted", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={["/launch"]}>
          <Routes>
            <Route path="/launch" element={<Launch />} />
            {/* The real page, not a stub: the question is whether what the
                launcher hands back is a run this surface can watch. */}
            <Route path="/runs/:runId" element={<RunDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await armGate(user);
    await user.click(screen.getByTestId("safety-key"));

    expect(await screen.findByTestId("live-window")).toBeInTheDocument();
    expect(onlySocket().url).toBe(
      `/api/runs/${encodeURIComponent(RUN_ID_RUNNING)}/events`,
    );
    // And no verdict is demanded of an artifact that does not exist yet.
    expect(screen.getByTestId("gate-banner-pending")).toBeInTheDocument();
  });

  it("renders a refused launch with a glyph, not colour alone", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/runs", () =>
        HttpResponse.json(
          {
            // No `detail` key, the way the server sends it — see the test above.
            error: { code: "busy", message: "another run is already in flight" },
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
