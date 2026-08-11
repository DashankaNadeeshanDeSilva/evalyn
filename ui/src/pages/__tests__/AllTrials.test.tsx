import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import type { RunDetail, TrialView } from "../../api/types";
import {
  DETAIL_GATE,
  EXFIL_EPOCHS,
  EXFIL_DEVIATING_EPOCH,
  EXFIL_TRIALS,
  PROBE_ID_EXFIL,
  RUN_ID_GATE,
  RUN_ID_LEGACY,
} from "../../mocks/fixtures";
import { server } from "../../mocks/server";
import { RunDetailPage } from "../RunDetailPage";

/**
 * "All trials at a glance" — every trial of one probe, side by side.
 *
 * The claim the panel has to let a room verify **by looking** is *"six times in
 * seven it says the approved line, and once it doesn't."* So the tests that
 * matter here are not "a panel rendered": they are that all seven replies are
 * on screen, that they are the seven *different* bodies rather than one body
 * seven times, and that whatever marking exists follows the data instead of a
 * position.
 *
 * ## Two data states, both real, both tested
 *
 * `TrialView.checks` is `[]` on **every artifact in `runs/` today**. Task 22
 * makes the server populate it; 87 existing artifacts will never have it. So
 * the panel is required to be fully useful with no check data at all — the
 * replies together are the value — and marking is an enhancement layered on
 * top. Both states are exercised below against the same seven trials.
 *
 * ## Nothing may key off a position
 *
 * Measured: the deviating trial was epoch 2 of 7 in one real run and epoch 6 of
 * 7 in another. `moves the mark when the failure moves` is the discriminator —
 * it drives the same fixture with the failure on three different epochs,
 * including two deviations at once, and an implementation that assumes "the
 * odd one out is first", "…is last" or "…is exactly one" fails at least one.
 */

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

function withDetail(detail: RunDetail) {
  server.use(http.get("/api/runs/:runId", () => HttpResponse.json(detail)));
}

/** Serve the seven exfil trials, transformed. `null` ⇒ that epoch errors. */
function withTrials(patch: (trial: TrialView) => TrialView | null) {
  server.use(
    http.get("/api/runs/:runId/trials/:probeId/:epoch", ({ params }) => {
      const epoch = Number(params["epoch"]);
      const base = EXFIL_TRIALS[epoch];
      if (!base) return HttpResponse.json({ error: {} }, { status: 404 });
      const patched = patch(base);
      if (patched === null) return HttpResponse.error();
      return HttpResponse.json(patched);
    }),
  );
}

/** Put the required check's failure on exactly these epochs, and nowhere else. */
function failingOn(epochs: readonly number[]) {
  return (trial: TrialView): TrialView => ({
    ...trial,
    checks: trial.checks.map((check) =>
      check.required
        ? { ...check, passed: !epochs.includes(trial.epoch), score: 1 }
        : check,
    ),
  });
}

/** Open the all-trials panel for the seven-trial probe. */
async function openAllTrials(probeId: string = PROBE_ID_EXFIL) {
  const user = userEvent.setup();
  const row = await screen.findByTestId(`probe-row-${probeId}`);
  await user.click(within(row).getByTestId("all-trials-key"));
  return { user, panel: await screen.findByTestId("all-trials-panel") };
}

async function rowsOf(panel: HTMLElement) {
  return await within(panel).findAllByTestId("all-trials-row");
}

/** One row by the epoch it carries — never by its position in the list. */
function rowFor(panel: HTMLElement, epoch: number): HTMLElement {
  const row = within(panel)
    .getAllByTestId("all-trials-row")
    .find((candidate) => candidate.dataset["epoch"] === String(epoch));
  if (!row) throw new Error(`no row for trial ${epoch}`);
  return row;
}

describe("every trial of the probe is on screen together", () => {
  it("renders one row per recorded epoch, in order", async () => {
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    expect(rows.map((r) => r.dataset["epoch"])).toEqual(
      EXFIL_EPOCHS.map(String),
    );
    expect(panel.dataset["probe"]).toBe(PROBE_ID_EXFIL);
  });

  /**
   * `trial_epochs` is the authority on *which* trials exist, and the panel
   * follows it rather than counting to `probe.trials`. Six recorded epochs out
   * of a seven-trial probe is exactly what a partially-captured artifact looks
   * like, and inventing the seventh row would claim a record that is not there.
   */
  it("follows trial_epochs rather than the trial count", async () => {
    withDetail({
      ...DETAIL_GATE,
      probes: DETAIL_GATE.probes.map((probe) =>
        probe.id === PROBE_ID_EXFIL
          ? { ...probe, trial_epochs: [2, 5, 7] }
          : probe,
      ),
    });
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    expect(rows.map((r) => r.dataset["epoch"])).toEqual(["2", "5", "7"]);
  });

  /**
   * The discriminator against a panel that renders one trial seven times — the
   * exact bug a single-body mock handler cannot catch, and the reason the mock
   * corpus answers per epoch.
   */
  it("shows each trial's own reply, not one reply repeated", async () => {
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const replies = await within(panel).findAllByTestId("trial-reply");
    expect(replies).toHaveLength(EXFIL_EPOCHS.length);
    for (const epoch of EXFIL_EPOCHS) {
      const expected = EXFIL_TRIALS[epoch]!.turns.at(-1)!.text;
      const row = rowFor(panel, epoch);
      expect(
        within(row).getByTestId("trial-reply").textContent,
        `trial ${epoch} did not show its own reply`,
      ).toContain(expected);
    }
    // ...and the room can see that six of the seven are word-for-word identical
    // while one is not, which is the whole claim being made on stage.
    const texts = replies.map((r) => r.textContent);
    const odd = texts.filter((t) => t !== texts[0]);
    expect(odd).toHaveLength(1);
  });

  it("shows the reply the target gave, not the prompt it was given", async () => {
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const row = rowFor(panel, 1);
    const trial = EXFIL_TRIALS[1]!;
    expect(within(row).getByTestId("trial-reply").textContent).not.toContain(
      trial.turns[0]!.text,
    );
    // The panel still states the opening turn once, attributed to the trial it
    // was read from — the room is being told these are answers to one question.
    expect(panel.textContent).toContain(trial.turns[0]!.text);
  });
});

describe("the panel is fully useful with no check data at all", () => {
  /**
   * Today's real data: `checks: []` on every artifact in `runs/`. The replies
   * are the value; the marking is the enhancement.
   */
  it("still shows all seven replies when no trial carries a check", async () => {
    withTrials((trial) => ({ ...trial, checks: [] }));
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    expect(rows).toHaveLength(EXFIL_EPOCHS.length);
    for (const row of rows) {
      expect(within(row).getByTestId("trial-reply").textContent).not.toBe("");
    }
  });

  it("marks nothing, and says why, rather than guessing", async () => {
    withTrials((trial) => ({ ...trial, checks: [] }));
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    for (const row of rows) expect(row.dataset["mark"]).toBe("unmarked");
    // Not silence: a panel that simply omits the mark leaves the operator
    // unable to tell "nothing failed" from "nothing was recorded".
    expect(panel.textContent?.toLowerCase()).toContain(
      "no per-check results",
    );
  });

  /**
   * The trap under this whole feature: the approved refusal lives in the pack,
   * not on the wire. A panel that recovers the marking by noticing six replies
   * agree and one does not is making up a verdict, and it would be right often
   * enough to be believed.
   */
  it("does not infer a deviation by comparing the replies to each other", async () => {
    withTrials((trial) => ({ ...trial, checks: [] }));
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    const deviating = rows.find(
      (r) => r.dataset["epoch"] === String(EXFIL_DEVIATING_EPOCH),
    );
    // Its reply genuinely is the odd one out, and the panel still refuses to
    // call it one, because nothing on the wire said so.
    expect(deviating?.dataset["mark"]).toBe("unmarked");
  });
});

describe("when checks are present, the mark follows the data", () => {
  it("marks the trial whose required check failed, and only that one", async () => {
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    const marked = rows.filter((r) => r.dataset["mark"] === "deviated");
    expect(marked.map((r) => r.dataset["epoch"])).toEqual([
      String(EXFIL_DEVIATING_EPOCH),
    ]);
    for (const row of rows) {
      if (row.dataset["epoch"] !== String(EXFIL_DEVIATING_EPOCH)) {
        expect(row.dataset["mark"]).toBe("conformed");
      }
    }
    // Glyph AND word AND colour: the mark survives a monochrome projector and
    // a colourblind reading.
    const deviating = rowFor(panel, EXFIL_DEVIATING_EPOCH);
    expect(deviating.textContent?.toLowerCase()).toContain("deviated");
    expect(
      deviating.querySelector("svg"),
      "the deviation mark rendered without a glyph — colour and word alone",
    ).not.toBeNull();
    // ...and it names the check that said so, rather than asserting it alone.
    expect(deviating.textContent).toContain("contains:approved-refusal");
  });

  /** Epoch 2 in one real run, epoch 6 in another. Neither is ever assumed. */
  it.each([[1], [2], [4], [7]])(
    "moves the mark when the failure moves to epoch %i",
    async (epoch) => {
      withTrials(failingOn([epoch]));
      renderPage(RUN_ID_GATE);
      const { panel } = await openAllTrials();

      const rows = await rowsOf(panel);
      const marked = rows
        .filter((r) => r.dataset["mark"] === "deviated")
        .map((r) => r.dataset["epoch"]);
      expect(marked).toEqual([String(epoch)]);
    },
  );

  it("marks every deviating trial when more than one deviates", async () => {
    withTrials(failingOn([2, 5]));
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    expect(
      rows.filter((r) => r.dataset["mark"] === "deviated").map((r) => r.dataset["epoch"]),
    ).toEqual(["2", "5"]);
  });

  it("marks nothing when nothing deviates", async () => {
    withTrials(failingOn([]));
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    expect(rows.every((r) => r.dataset["mark"] === "conformed")).toBe(true);
  });

  /**
   * `required: false` is the check that can fail without moving the gate.
   * Marking it as a deviation would put a red mark beside a trial the gate
   * itself passed — a claim the run never made.
   */
  it("ignores a failure on a check that was not required", async () => {
    withTrials((trial) => ({
      ...trial,
      checks: trial.checks.map((check) =>
        check.required
          ? { ...check, passed: true, score: 1 }
          : { ...check, passed: false, score: 0 },
      ),
    }));
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    expect(rows.every((r) => r.dataset["mark"] === "conformed")).toBe(true);
  });

  /**
   * `passed: null` is "no score", never "failed" — the rule `VerdictBadge` and
   * the contract both hold. An unscored required check cannot be called a
   * deviation, and it cannot be called conformance either.
   */
  it("does not read an unscored required check as either verdict", async () => {
    withTrials((trial) => ({
      ...trial,
      checks: trial.checks.map((check) =>
        check.required ? { ...check, passed: null, score: null } : check,
      ),
    }));
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    for (const row of rows) expect(row.dataset["mark"]).toBe("unmarked");
  });

  /** The count is read off the data, never off the fixture's shape. */
  it("counts the deviations it found in words", async () => {
    withTrials(failingOn([3, 4, 6]));
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    await rowsOf(panel);
    const tally = within(panel).getByTestId("all-trials-tally");
    expect(tally.textContent).toContain("3 of 7");
  });
});

describe("a trial that fails to load does not take the others with it", () => {
  it("keeps the other six readable and states which one failed", async () => {
    withTrials((trial) => (trial.epoch === 3 ? null : trial));
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    const rows = await rowsOf(panel);
    expect(rows).toHaveLength(EXFIL_EPOCHS.length);

    const broken = rowFor(panel, 3);
    await within(broken).findByText(/could not reach its server/i);
    expect(
      broken.querySelector("svg"),
      "the failed-trial branch rendered without a glyph",
    ).not.toBeNull();
    expect(within(broken).queryByTestId("trial-reply")).toBeNull();

    // The other six still carry their replies — the panel degraded in one row,
    // not as a whole.
    for (const epoch of EXFIL_EPOCHS.filter((e) => e !== 3)) {
      const row = rowFor(panel, epoch);
      await waitFor(() =>
        expect(within(row).getByTestId("trial-reply").textContent).toContain(
          EXFIL_TRIALS[epoch]!.turns.at(-1)!.text,
        ),
      );
    }
  });

  it("says a trial captured no reply rather than rendering a blank row", async () => {
    withTrials((trial) =>
      trial.epoch === 4 ? { ...trial, turns: [] } : trial,
    );
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    await rowsOf(panel);
    const empty = rowFor(panel, 4);
    expect(empty.textContent?.toLowerCase()).toContain("captured no");
    expect(within(empty).queryByTestId("trial-reply")).toBeNull();
  });
});

describe("the panel is not offered when the drill-down cannot answer", () => {
  /**
   * `capabilities.trial_records` is the authority, never `trial_epochs.length`.
   * This artifact carries seven epochs — truthy, non-empty, exactly what a
   * naive implementation keys off — while the capability says no, and the
   * server would 404 all seven requests.
   */
  it("disables the key when capabilities say no, though trial_epochs is full", async () => {
    withDetail({
      ...DETAIL_GATE,
      capabilities: {
        transcripts: false,
        trial_records: false,
        hard_metrics: false,
      },
    });
    const user = userEvent.setup();
    renderPage(RUN_ID_GATE);

    const row = await screen.findByTestId(`probe-row-${PROBE_ID_EXFIL}`);
    const key = within(row).getByTestId("all-trials-key");
    expect(
      key,
      "the panel was offered off trial_epochs instead of capabilities.trial_records",
    ).toBeDisabled();
    // Degrade visibly rather than hide: present, disabled, and explained.
    expect(key.title.toLowerCase()).toContain("no trial records");

    await user.click(key);
    expect(screen.queryByTestId("all-trials-panel")).toBeNull();
  });

  it("is disabled on a legacy artifact, for the artifact's own reason", async () => {
    renderPage(RUN_ID_LEGACY);

    const row = await screen.findByTestId("probe-row-grounding-work-history");
    const key = within(row).getByTestId("all-trials-key");
    expect(key).toBeDisabled();
    expect(
      key.querySelector(".sr-only")?.textContent?.toLowerCase(),
    ).toContain("no trial records");
    expect(screen.queryByTestId("all-trials-panel")).toBeNull();
  });

  it("is disabled for a probe that recorded no trial of its own", async () => {
    withDetail({
      ...DETAIL_GATE,
      probes: DETAIL_GATE.probes.map((probe) =>
        probe.id === PROBE_ID_EXFIL ? { ...probe, trial_epochs: [] } : probe,
      ),
    });
    renderPage(RUN_ID_GATE);

    const row = await screen.findByTestId(`probe-row-${PROBE_ID_EXFIL}`);
    const key = within(row).getByTestId("all-trials-key");
    expect(key).toBeDisabled();
    expect(key.title.toLowerCase()).toContain("this probe");
  });
});

describe("long replies are truncated visibly and reversibly", () => {
  const LONG = `${"the same refusal, at length. ".repeat(40)}TAIL-MARKER`;

  it("hides nothing silently: the cut is stated and undoable", async () => {
    withTrials((trial) =>
      trial.epoch === 1
        ? {
            ...trial,
            turns: [trial.turns[0]!, { role: "assistant", text: LONG, redacted: false }],
          }
        : trial,
    );
    renderPage(RUN_ID_GATE);
    const { user, panel } = await openAllTrials();

    await rowsOf(panel);
    const row = rowFor(panel, 1);
    // Cut, and saying so — with the amount, so "…" is never the whole story.
    expect(within(row).getByTestId("trial-reply").textContent).not.toContain(
      "TAIL-MARKER",
    );
    const expand = within(row).getByTestId("reply-expand");
    expect(expand.textContent).toMatch(/\d+/);

    await user.click(expand);
    expect(within(row).getByTestId("trial-reply").textContent).toContain(
      "TAIL-MARKER",
    );

    // Reversible.
    await user.click(within(row).getByTestId("reply-expand"));
    expect(within(row).getByTestId("trial-reply").textContent).not.toContain(
      "TAIL-MARKER",
    );
  });

  it("offers no expander for a reply that was shown whole", async () => {
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();

    await rowsOf(panel);
    const row = rowFor(panel, 1);
    expect(within(row).queryByTestId("reply-expand")).toBeNull();
  });
});

describe("the two trial views are one selection", () => {
  /**
   * Both panels answer "what did the model say", at two zoom levels. Showing
   * them at once puts one transcript underneath seven of them, which reads as
   * an eighth trial.
   */
  it("replaces the single-trial panel rather than stacking under it", async () => {
    const user = userEvent.setup();
    renderPage(RUN_ID_GATE);

    const row = await screen.findByTestId(`probe-row-${PROBE_ID_EXFIL}`);
    await user.click(within(row).getAllByTestId("trial-key")[0]!);
    await screen.findByTestId("trial-panel");

    await user.click(within(row).getByTestId("all-trials-key"));
    await screen.findByTestId("all-trials-panel");
    expect(screen.queryByTestId("trial-panel")).toBeNull();

    await user.click(within(row).getAllByTestId("trial-key")[0]!);
    await screen.findByTestId("trial-panel");
    expect(screen.queryByTestId("all-trials-panel")).toBeNull();
  });

  it("marks the pressed key so the operator knows the panel is open", async () => {
    renderPage(RUN_ID_GATE);
    const { panel } = await openAllTrials();
    expect(panel).toBeInTheDocument();

    const row = screen.getByTestId(`probe-row-${PROBE_ID_EXFIL}`);
    expect(
      within(row).getByTestId("all-trials-key").getAttribute("aria-pressed"),
    ).toBe("true");
  });
});
