import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import type { PackRow, TrustReport } from "../../api/types";
import { PACKS, TRUST_NEVER_CALIBRATED, TRUST_REPORT } from "../../mocks/fixtures";
import { server } from "../../mocks/server";
import { Trust } from "../Trust";

/**
 * The judge-trust page.
 *
 * Two facts about the real data drive almost everything below.
 *
 * **The uncalibrated state is not an edge case — it is what the demo shows.**
 * `packs/twincore` is the only pack in this repository carrying a
 * `calibration.json`; `packs/twincore-injection` (the demo pack) and
 * `packs/example` have none, and `/api/trust` answers for them with a
 * legitimate **200 and `agreement: null`**, never a 404. So the never-calibrated
 * rendition is the ordinary one and it has to read as deliberate rather than as
 * a page that failed to load.
 *
 * **`stale` defaults to `true`.** A record can carry a healthy-looking 93% and
 * still be one the gate refuses, and the difference is invisible unless the page
 * says so where the operator is already looking.
 *
 * Two things the page may never do, both asserted here:
 *
 * 1. Call the number `kappa`, or imply Cohen's κ. It is ±1-point agreement as
 *    shipped; nothing computed a κ and the label must not claim a certification
 *    nobody performed.
 * 2. Render `stale: true` as though it were fresh.
 */

function renderTrust() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Trust />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Serve one body for whatever pack is asked for. */
function withReport(patch: Partial<TrustReport>) {
  server.use(
    http.get("/api/trust", () =>
      HttpResponse.json({ ...TRUST_REPORT, ...patch }),
    ),
  );
}

function withPacks(names: string[]) {
  const items: PackRow[] = names.map((name, index) => ({
    ...PACKS[0]!,
    id: `pack-0000000${index}`,
    name,
    path: `~/packs/${name}`,
  }));
  server.use(
    http.get("/api/packs", () =>
      HttpResponse.json({ items, next_cursor: null }),
    ),
  );
}

/** The page, once the calibration read has landed. */
async function settled() {
  return await screen.findByTestId("trust-verdict");
}

/** One rubric group of the record table, by the rubric it carries. */
function groupFor(rubric: string): HTMLElement {
  const group = screen
    .getAllByTestId("rubric-group")
    .find((candidate) => candidate.dataset["rubric"] === rubric);
  if (!group) throw new Error(`no group for rubric ${rubric}`);
  return group;
}

function rowFor(criterionId: string): HTMLElement {
  const row = screen
    .getAllByTestId("criterion-row")
    .find((candidate) => candidate.dataset["criterion"] === criterionId);
  if (!row) throw new Error(`no row for criterion ${criterionId}`);
  return row;
}

describe("a pack that was never calibrated is a state, not a failure", () => {
  it("says there is no calibration record rather than reporting zero", async () => {
    withPacks(["twincore-injection"]);
    renderTrust();

    const verdict = await settled();
    expect(verdict.dataset["record"]).toBe("absent");
    expect(verdict.textContent?.toLowerCase()).toContain("not calibrated");
    // Zero is a measurement and nobody made one.
    expect(
      document.body.textContent,
      "a figure was invented for a pack nothing has ever measured",
    ).not.toMatch(/\b0\s*%/);
  });

  it("names the command that would write the record", async () => {
    withPacks(["twincore-injection"]);
    renderTrust();
    await settled();

    expect(screen.getByTestId("trust-absent").textContent).toContain(
      "evalyn calibrate",
    );
  });

  /**
   * Not an empty table with a header and no rows, and not an axis frame with
   * nothing on it: there is no record, so there is nothing to draw a frame for.
   */
  it("draws no record table at all", async () => {
    withPacks(["twincore-injection"]);
    renderTrust();
    await settled();

    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByTestId("trust-error")).toBeNull();
  });

  it("states the server's own reason for the absence", async () => {
    withPacks(["twincore-injection"]);
    renderTrust();
    await settled();

    expect(document.body.textContent).toContain(
      TRUST_NEVER_CALIBRATED.stale_reason,
    );
  });
});

describe("a stale record is never presented as a live one", () => {
  it("carries the staleness in the headline, not in the fine print", async () => {
    withPacks(["twincore"]);
    withReport({ stale: true, stale_reason: "rubric 'persona' changed since calibration" });
    renderTrust();

    const verdict = await settled();
    expect(verdict.dataset["record"]).toBe("stale");
    expect(
      verdict.textContent?.toLowerCase(),
      "the headline read as calibrated while the gate was refusing the record",
    ).toContain("stale");
  });

  it("quotes the server's reason verbatim", async () => {
    withPacks(["twincore"]);
    withReport({ stale: true, stale_reason: "rubric 'persona' changed since calibration" });
    renderTrust();
    await settled();

    expect(document.body.textContent).toContain(
      "rubric 'persona' changed since calibration",
    );
  });

  it("says the gate refuses this pack's rubric checks while it is stale", async () => {
    withPacks(["twincore"]);
    withReport({ stale: true, stale_reason: "judge model changed" });
    renderTrust();
    await settled();

    expect(document.body.textContent?.toLowerCase()).toContain(
      "refuses this pack's rubric checks",
    );
  });

  it("says the opposite when the record is in force", async () => {
    withPacks(["twincore"]);
    renderTrust();

    const verdict = await settled();
    expect(verdict.dataset["record"]).toBe("calibrated");
    expect(verdict.textContent?.toLowerCase()).not.toContain("stale");
    expect(document.body.textContent?.toLowerCase()).not.toContain(
      "refuses this pack's rubric checks",
    );
  });
});

describe("the number says what it is", () => {
  /**
   * Nothing in the engine computes Cohen's κ. Labelling the figure as one
   * claims a certification that was not performed, on a page whose entire
   * subject is whether a measurement can be believed.
   */
  it("never calls the agreement kappa", async () => {
    withPacks(["twincore"]);
    renderTrust();
    await settled();

    const text = document.body.textContent ?? "";
    expect(text.toLowerCase()).not.toContain("kappa");
    expect(text).not.toContain("κ");
  });

  it("names it as ±1-point agreement against the human labels", async () => {
    withPacks(["twincore"]);
    renderTrust();
    await settled();

    const text = document.body.textContent ?? "";
    expect(text).toContain("±1-point agreement");
    expect(
      text.toLowerCase(),
      "the figure is named but never explained, so it reads as a score",
    ).toContain("within one point");
  });

  it("shows the threshold the gate holds the record to", async () => {
    withPacks(["twincore"]);
    renderTrust();
    await settled();

    expect(screen.getByTestId("trust-threshold").textContent).toContain("85%");
  });
});

describe("the record reads weakest first, grouped by what the threshold gates", () => {
  it("orders the rubric groups weakest first", async () => {
    withPacks(["twincore"]);
    renderTrust();
    await settled();

    expect(
      screen.getAllByTestId("rubric-group").map((g) => g.dataset["rubric"]),
    ).toEqual(["completeness", "persona", "groundedness", "honesty"]);
  });

  it("files each criterion under its own rubric", async () => {
    withPacks(["twincore"]);
    renderTrust();
    await settled();

    const persona = groupFor("persona");
    expect(
      within(persona)
        .getAllByTestId("criterion-row")
        .map((r) => r.dataset["criterion"]),
    ).toEqual(["persona:Tone under refusal", "persona:First-person fidelity"]);
  });

  /**
   * `100%` over eleven pairs and `100%` over four hundred are different claims,
   * and the wire reports them identically. Every figure is shown beside the
   * count it came from so nobody reads a small sample as certainty.
   */
  it("shows the matched pairs behind every figure", async () => {
    withPacks(["twincore"]);
    renderTrust();
    await settled();

    expect(rowFor("persona:Tone under refusal").textContent).toContain("9 / 11");
    expect(groupFor("persona").textContent).toContain("20 / 22");
    expect(screen.getByTestId("trust-agreement").textContent).toContain(
      "82 of 88",
    );
  });

  it("counts what the record holds rather than a written-down number", async () => {
    withPacks(["twincore"]);
    withReport({
      per_criterion_agreement: { "honesty:Calibration": 0.5 },
      per_criterion_counts: { "honesty:Calibration": { hits: 1, total: 2 } },
      per_rubric_agreement: { honesty: 0.5 },
    });
    renderTrust();
    await settled();

    const readout = screen.getByTestId("trust-readout").textContent ?? "";
    expect(readout).toContain("1 criterion");
    expect(readout).toContain("1 of 2");
  });

  /** The page's noun for a row is `criterion`. A probe is a different thing. */
  it("calls a row a criterion and never a probe", async () => {
    withPacks(["twincore"]);
    renderTrust();
    await settled();

    expect(screen.getByRole("columnheader", { name: /criterion/i })).toBeInTheDocument();
    expect(document.body.textContent?.toLowerCase()).not.toContain("probe");
  });
});

describe("the threshold is marked exactly where it applies", () => {
  it("marks a rubric under the bar, in words", async () => {
    withPacks(["twincore"]);
    withReport({
      stale: true,
      stale_reason: "per-rubric agreement below the 85% threshold for 'persona' at 60%",
      per_rubric_agreement: { ...TRUST_REPORT.per_rubric_agreement, persona: 0.6 },
    });
    renderTrust();
    await settled();

    const persona = groupFor("persona");
    expect(persona.dataset["belowThreshold"]).toBe("true");
    expect(
      persona.textContent?.toLowerCase(),
      "the shortfall travelled as colour alone",
    ).toContain("below the bar");
    // ...and only there.
    expect(groupFor("honesty").dataset["belowThreshold"]).toBe("false");
    expect(groupFor("honesty").textContent?.toLowerCase()).not.toContain(
      "below the bar",
    );
  });

  /**
   * `is_stale` gates on the overall figure and on each **rubric's** own figure.
   * It does not gate on a criterion. `persona:Tone under refusal` sits at 82%,
   * under the 85% bar, in a record the gate accepts — marking it as a shortfall
   * would report a failure the engine never declared.
   */
  it("does not hold a single criterion to the threshold", async () => {
    withPacks(["twincore"]);
    renderTrust();
    await settled();

    const row = rowFor("persona:Tone under refusal");
    expect(row.textContent).toContain("82%");
    expect(
      row.textContent?.toLowerCase(),
      "a criterion was failed against a bar the gate does not apply to it",
    ).not.toContain("below the bar");
  });

  it("marks the overall figure when it is the one under the bar", async () => {
    withPacks(["twincore"]);
    withReport({
      agreement: 0.5,
      stale: true,
      stale_reason: "recorded agreement 50% is below the 85% threshold",
    });
    renderTrust();
    await settled();

    expect(
      screen.getByTestId("trust-agreement").textContent?.toLowerCase(),
    ).toContain("below the bar");
  });
});

describe("criteria the record never matched are named, not dropped", () => {
  it("lists them and says why nothing above measures them", async () => {
    withPacks(["twincore"]);
    withReport({ unmatched: ["persona:Brevity", "honesty:Hedging"] });
    renderTrust();
    await settled();

    const block = screen.getByTestId("trust-unmatched");
    expect(block.textContent).toContain("persona:Brevity");
    expect(block.textContent).toContain("honesty:Hedging");
    expect(screen.getByTestId("trust-readout").textContent).toContain(
      "2 unmatched",
    );
  });

  it("says nothing at all when every criterion was matched", async () => {
    withPacks(["twincore"]);
    renderTrust();
    await settled();

    expect(screen.queryByTestId("trust-unmatched")).toBeNull();
    expect(screen.getByTestId("trust-readout").textContent).not.toContain(
      "unmatched",
    );
  });
});

describe("the pack is chosen, and the choice reaches the server", () => {
  it("asks for the pack the operator selected", async () => {
    const asked: string[] = [];
    withPacks(["twincore-injection", "twincore"]);
    server.use(
      http.get("/api/trust", ({ request }) => {
        const pack = new URL(request.url).searchParams.get("pack") ?? "";
        asked.push(pack);
        return HttpResponse.json(
          pack === TRUST_REPORT.pack_name
            ? TRUST_REPORT
            : { ...TRUST_NEVER_CALIBRATED, pack_name: pack },
        );
      }),
    );
    const user = userEvent.setup();
    renderTrust();

    expect((await settled()).dataset["record"]).toBe("absent");
    expect(asked).toContain("twincore-injection");

    await user.click(screen.getByRole("button", { name: /twincore$/i }));
    await waitFor(() =>
      expect(screen.getByTestId("trust-verdict").dataset["record"]).toBe(
        "calibrated",
      ),
    );
    expect(asked).toContain("twincore");
  });

  it("says so rather than counting to zero when the server has no allowlist", async () => {
    server.use(
      http.get("/api/packs", () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    );
    renderTrust();

    await screen.findByText(/started with no pack allowlist/i);
    expect(screen.queryByTestId("trust-verdict")).toBeNull();
  });
});

describe("a read that fails degrades visibly", () => {
  it("says the record could not be read instead of reporting nothing measured", async () => {
    withPacks(["twincore"]);
    server.use(
      http.get("/api/trust", () =>
        HttpResponse.json(
          { error: { code: "read_error", message: "calibration.json is not readable" } },
          { status: 500 },
        ),
      ),
    );
    renderTrust();

    const failure = await screen.findByTestId("trust-error");
    expect(failure.textContent).toContain("calibration.json is not readable");
    expect(
      failure.querySelector("svg"),
      "the failure rendered without a glyph — colour and words alone",
    ).not.toBeNull();
    expect(screen.queryByTestId("trust-verdict")).toBeNull();
    expect(screen.getByTestId("trust-readout").textContent).not.toMatch(/\d/);
  });
});
