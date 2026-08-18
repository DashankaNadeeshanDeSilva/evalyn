import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { RUN_STATUSES, VERDICT_HINTS } from "../../api/types";
import {
  RUN_SUMMARIES,
  SUMMARY_COMPARE,
  SUMMARY_GATE,
} from "../../mocks/fixtures";
import { RunStatusChip } from "../RunStatusChip";
import { RunsTable } from "../RunsTable";

/*
 * ---------------------------------------------------------------------------
 * DEFERRED VERIFICATION — Task 8, Step 4 ("verify against the real server")
 * ---------------------------------------------------------------------------
 *
 * Task 8's Step 4 asks for the runs list to be confirmed against a live
 * `evalyn ui --no-open` pointed at the real `runs/` directory. That server does
 * not exist yet: Task 6 creates the FastAPI app and Task 7 implements
 * `GET /api/runs`. Everything below therefore runs against the MSW mock layer
 * Task 5 wrote, which is a mock of the frozen contract, not of a server.
 *
 * Nothing in this repository stubs, fakes or simulates that server to make the
 * step look discharged. The verification is deferred, in full, to the first
 * task that has a real server to point at (Task 7 at the earliest), and it must
 * check:
 *
 *   1. The list renders every artifact the index reports, with the row count
 *      DERIVED from the server's own response — never a literal. Ruling R4-6:
 *      the run count changes every time an eval runs (80 indexed / 26 degraded
 *      when last measured), so a hardcoded number reds on a correct build.
 *   2. Degraded rows are present, not omitted, with their `run_id` legible and
 *      `degraded_reason` stated — again counted from the response, not asserted
 *      as a literal.
 *   3. Cursor pagination walks the whole list: each `next_cursor` is handed back
 *      verbatim as `?before=` until the server returns `null`, and the union of
 *      the pages contains no duplicate and no missing `run_id`.
 *   4. The page holds its layout at real width — ~80 rows, long run ids, and the
 *      real `runs_dir` label — without the body scrolling horizontally.
 *
 * The mock's page size (3) is deliberately smaller than its corpus (4), so the
 * pagination *wiring* is exercised here; only the real corpus can exercise its
 * scale.
 * ---------------------------------------------------------------------------
 */

/**
 * Every expectation below is derived from the fixture corpus rather than
 * written as a literal, so growing the corpus cannot silently stop exercising
 * a case — and so no run count is ever hardcoded (ruling R4-6).
 */
const DEGRADED_FIXTURES = RUN_SUMMARIES.filter((r) => r.degraded);
const HEALTHY_FIXTURES = RUN_SUMMARIES.filter((r) => !r.degraded);

function renderTable(runs = RUN_SUMMARIES) {
  return render(
    <MemoryRouter>
      <RunsTable runs={runs} />
    </MemoryRouter>,
  );
}

function rowFor(runId: string): HTMLElement {
  const row = document.querySelector<HTMLElement>(
    `[data-testid="run-row"][data-run-id="${runId}"]`,
  );
  if (!row) throw new Error(`no rendered row for run_id ${runId}`);
  return row;
}

describe("the fixture corpus this suite is derived from", () => {
  it("still covers both a degraded and a healthy run", () => {
    // Without these, the assertions below would pass over an empty set.
    expect(DEGRADED_FIXTURES.length).toBeGreaterThan(0);
    expect(HEALTHY_FIXTURES.length).toBeGreaterThan(0);
  });
});

describe("RunsTable", () => {
  it("renders one row per run, in the order the server sent them", () => {
    renderTable();

    const rows = screen.getAllByTestId("run-row");
    // Derived, never a literal: the count is whatever the corpus holds.
    expect(rows).toHaveLength(RUN_SUMMARIES.length);
    expect(rows.map((r) => r.dataset["runId"])).toEqual(
      RUN_SUMMARIES.map((r) => r.run_id),
    );
  });

  it("makes every run_id legible and openable", () => {
    renderTable();

    for (const run of RUN_SUMMARIES) {
      const link = screen.getByRole("link", { name: run.run_id });
      expect(link).toHaveAttribute("href", `/runs/${run.run_id}`);
    }
  });

  it("carries the status as glyph AND word AND colour, never colour alone", () => {
    renderTable();

    for (const run of RUN_SUMMARIES) {
      const chip = rowFor(run.run_id).querySelector<HTMLElement>(
        '[data-testid="status-chip"]',
      );
      expect(chip, `no status chip in the row for ${run.run_id}`).not.toBeNull();
      // The word is the RunStatus member verbatim — the chip is uppercased in
      // CSS, so the DOM text cannot drift from the enum.
      expect(chip!.textContent).toContain(run.status);
      // The glyph is a drawn icon, not a unicode character standing in for one.
      expect(chip!.querySelector("svg")).not.toBeNull();
    }
  });

  it("flat-lines the metric cells of a degraded row and states the reason", () => {
    renderTable();

    for (const run of DEGRADED_FIXTURES) {
      const row = rowFor(run.run_id);
      expect(row.dataset["degraded"]).toBe("true");

      // The run_id stays legible: a degraded row is shown, never hidden.
      expect(row.textContent).toContain(run.run_id);

      // No metric cell carries a value — the readout is a dead channel.
      expect(row.querySelectorAll("[data-metric]")).toHaveLength(0);
      expect(
        row.querySelectorAll("[data-flatlined]").length,
      ).toBeGreaterThan(0);

      // The reason is both the row's tooltip and visible text: a greyed row
      // with no explanation is the failure mode `degraded_reason` prevents.
      expect(row).toHaveAttribute("title", run.degraded_reason!);
      expect(row.textContent).toContain(run.degraded_reason!);
    }
  });

  it("renders real metric cells for a run that is not degraded", () => {
    renderTable();

    for (const run of HEALTHY_FIXTURES) {
      const row = rowFor(run.run_id);
      expect(row.dataset["degraded"]).toBeUndefined();
      expect(row.querySelectorAll("[data-metric]").length).toBeGreaterThan(0);

      // Tabular figures on every cell whose value is a *figure*, so a column
      // does not jitter between renders. `data-numeric` is the figure subset —
      // the verdict hint is a metric but a word, and setting `tabular-nums` on
      // a word would be cargo cult rather than a guarantee.
      const numerics = row.querySelectorAll("[data-numeric]");
      expect(numerics.length).toBeGreaterThan(0);
      for (const cell of numerics) {
        expect(cell.className).toContain("tabular-nums");
      }
    }
  });

  /**
   * The gate hint is this product's central output, and the finish review found
   * it rendering as colour + word with no glyph. Nothing guarded that fix: the
   * reviewer deleted `<VerdictHintIcon>` and the whole suite stayed green at
   * 156/156. A fix the project paid a design review to find, with no test under
   * it, is a fix with a countdown on it.
   */
  it("carries the gate hint as glyph AND word for every VerdictHint member", () => {
    for (const hint of VERDICT_HINTS) {
      const { unmount } = renderTable([{ ...SUMMARY_GATE, verdict_hint: hint }]);

      const cell = document.querySelector<HTMLElement>(
        '[data-metric="verdict_hint"]',
      );
      expect(cell, `no verdict cell rendered for hint ${hint}`).not.toBeNull();
      expect(cell!.textContent).toContain(hint);
      expect(
        cell!.querySelector("svg"),
        `the ${hint} hint renders without a glyph — colour and word alone`,
      ).not.toBeNull();

      unmount();
    }
  });

  /**
   * THE OLD-API GUARD — and the label is the point, because this shape is no
   * longer one the current server can produce.
   *
   * `verdict_hint_of` reds any probe with `trials == 0`, and a cancelled run's
   * un-run probes satisfy that trivially — so an Evalyn from before the backend
   * fix sends `{status: "cancelled", verdict_hint: "failed"}` for a run nobody
   * let finish. Measured on `20260811T212955379968-abc9a71e-example`. Reading
   * that as a gate failure states, in one row, that the build is broken when
   * all that happened is that an operator pressed Cancel.
   *
   * `verdict_hint_of` now returns `None` for a cancelled artifact, so THIS
   * build's server sends `verdict_hint: null` instead — the shape pinned by the
   * `stopped`-not-`never` test below, which is the one describing current
   * server behaviour. What is left here is a compatibility claim and is written
   * as one: the SPA is served by the API under `evalyn ui`, but `npm run dev`
   * proxies `/api` to whatever `evalyn ui` is listening on 8765, and this
   * column's promise — an approximation is never read as a verdict — must not
   * become conditional on the peer's version.
   */
  it("reads no verdict off a stopped row even when an older API hints one", () => {
    renderTable([
      { ...SUMMARY_GATE, status: "cancelled", verdict_hint: "failed" },
    ]);

    const row = rowFor(SUMMARY_GATE.run_id);
    expect(
      row.querySelector('[data-metric="verdict_hint"]'),
      "a stopped run rendered its hint as a measured verdict",
    ).toBeNull();
    const said = row.textContent?.toLowerCase() ?? "";
    expect(said).not.toContain("gate failed");
    expect(said).not.toContain("gate passed");

    // Blank is not the answer either: the cell states what is absent and why.
    const verdictCell = row.querySelectorAll("td")[5]!;
    expect(verdictCell.querySelector("[data-flatlined]")).not.toBeNull();
    expect(verdictCell.textContent?.toLowerCase()).toContain("stopped");
    // ...and it must not borrow the words that belong to a mode with no gate.
    expect(
      verdictCell.textContent?.toLowerCase(),
      "a stopped gate run has a gate — nobody let it finish",
    ).not.toContain("no gate");

    // The row's own STATUS is correct and keeps rendering.
    expect(said).toContain("cancelled");
  });

  /**
   * The door the stopped check opens, and must not walk through.
   *
   * `compare` and `discover` have no gate at all, so "the gate earned no
   * verdict" is a claim about a thing that never existed. Worse, they are
   * exactly the modes where the cancelled signal is *weakest*: their artifacts
   * carry no `cancelled` field, so `cancelled_by` falls back to the leftover
   * `<stem>.control.json`, which that function's own docstring records as
   * having been measured relabelling a run that had completed all twelve of its
   * trials. So a stopped-claim here could be made about a run that finished.
   *
   * Both failures close on one ordering: a mode with no gate answers first,
   * which also makes the stopped branch unreachable for precisely the modes
   * whose cancelled signal cannot be trusted.
   */
  it("does not claim a gate on a stopped run in a mode that has none", () => {
    renderTable([{ ...SUMMARY_COMPARE, status: "cancelled" }]);

    const cell = rowFor(SUMMARY_COMPARE.run_id).querySelectorAll("td")[5]!;
    const said = cell.textContent?.toLowerCase() ?? "";
    expect(said).toContain("no gate");
    expect(
      said,
      "a compare run was told a gate of its own earned no verdict",
    ).not.toContain("stopped");
    expect(cell.querySelector('[data-flatlined="n/a"]')).not.toBeNull();
  });

  /**
   * And the mirror, which is what stops that ordering over-correcting — and,
   * since the backend fix, THE SHAPE THE SERVER ACTUALLY SENDS for a cancelled
   * gate run.
   *
   * `verdict_hint: null` now reaches this cell on a **gate** row two ways.
   * `_pending_summary` (`ui/index.py`) sets it for a run that exists only as a
   * sidecar, with `degraded: false`, so the *early* cancel — one that lands
   * before the engine writes its artifact — arrives here. And `verdict_hint_of`
   * returns `None` for a cancelled artifact, so the late cancel now arrives
   * with the same pair.
   *
   * Which makes this the test that stops the backend fix being read as a
   * licence to delete the frontend one. Remove the `stopped` branch and a
   * cancelled row falls through to `hint === null`, where it is painted `never`
   * — no false verdict, but no operator either. So `never` is asserted against
   * by name: "contains stopped" alone stays green on a cell that says both, and
   * on one that has dropped the flatline for a rendered hint.
   */
  it("says stopped, never `never`, on a cancelled gate run with no hint", () => {
    renderTable([{ ...SUMMARY_GATE, status: "cancelled", verdict_hint: null }]);

    const cell = rowFor(SUMMARY_GATE.run_id).querySelectorAll("td")[5]!;
    const said = cell.textContent?.toLowerCase() ?? "";
    expect(said).toContain("stopped");
    expect(said, "a gate run was told it has no gate").not.toContain("no gate");
    expect(
      said,
      "a stopped run was told its verdict merely never arrived",
    ).not.toContain("never");
    expect(said, "a stopped run was told to wait for a verdict").not.toContain(
      "not yet",
    );
    expect(
      cell.querySelector('[data-metric="verdict_hint"]'),
      "a stopped run rendered a measured verdict",
    ).toBeNull();
    expect(cell.querySelector("[data-flatlined]")).not.toBeNull();
  });

  /**
   * The third thing `verdict_hint: null` means, now that this branch is
   * reachable only by a gate run: launched, nothing measured yet, nobody
   * stopped it. Before the reordering it shared "no gate" with the modes that
   * genuinely have none; afterwards that copy would have been false in every
   * case that reaches it.
   */
  it("says a gate run has measured nothing yet rather than that it has no gate", () => {
    renderTable([{ ...SUMMARY_GATE, status: "running", verdict_hint: null }]);

    const cell = rowFor(SUMMARY_GATE.run_id).querySelectorAll("td")[5]!;
    const said = cell.textContent?.toLowerCase() ?? "";
    expect(said).not.toContain("no gate");
    expect(said).not.toContain("stopped");
    expect(cell.querySelector("[data-flatlined]")).not.toBeNull();
    expect(said, "a live run is the one case 'yet' is true of").toContain(
      "not yet",
    );
  });

  /**
   * The fourth thing, and the one the copy was wrong about: `verdict_hint` is
   * `null` on a run that ENDED without one. "not yet" is a promise, and a run
   * that failed to start or was interrupted cannot keep it — the operator is
   * told to wait for a verdict that is not coming.
   *
   * Two statuses, so it is not pinned to one branch, and each is asserted
   * against "not yet" rather than merely for "never": a cell that rendered
   * both words, or that dropped the flatline entirely, would pass a weaker
   * version of this.
   */
  it.each(["interrupted", "failed_to_start"] as const)(
    "does not promise a verdict is still coming on a %s run",
    (status) => {
      renderTable([{ ...SUMMARY_GATE, status, verdict_hint: null }]);

      const cell = rowFor(SUMMARY_GATE.run_id).querySelectorAll("td")[5]!;
      const said = cell.textContent?.toLowerCase() ?? "";
      expect(said).toContain("never");
      expect(said, "a run that ended was told to wait").not.toContain("not yet");
      expect(said).not.toContain("no gate");
      expect(cell.querySelector("[data-flatlined]")).not.toBeNull();
    },
  );

  /**
   * THE CONTROL — must stay GREEN.
   *
   * A condition keyed on the wrong thing blanks this column for every row on
   * the corpus, and the demo's whole argument is in this column. Both halves
   * are here: the red the talk is about, and the green that proves the guard
   * is not just "never render anything".
   */
  it("still reads GATE FAILED and GATE PASSED on rows nobody stopped", () => {
    /* One row at a time, on the gate fixture's own id. An earlier revision put
       the passing row on `RUN_ID_LEGACY` purely to have a second id to look up
       — a legacy artifact is a pre-round-2 run that reports no per-probe
       trials, so the row was a state that fixture cannot be in, asserting
       something it has nothing to do with. */
    for (const [status, hint, word] of [
      ["gate_failed", "failed", "gate failed"],
      ["passed", "passed", "gate passed"],
    ] as const) {
      const { unmount } = renderTable([
        { ...SUMMARY_GATE, status, verdict_hint: hint },
      ]);

      const row = rowFor(SUMMARY_GATE.run_id);
      const cell = row.querySelector<HTMLElement>('[data-metric="verdict_hint"]');
      expect(cell, `the verdict cell went missing on a ${word} row`).not.toBeNull();
      expect(cell!.textContent?.toLowerCase()).toContain(word);
      expect(cell!.querySelector("svg")).not.toBeNull();
      expect(
        row.querySelectorAll("td")[5]!.querySelector("[data-flatlined]"),
        `a ${word} row had its verdict flat-lined`,
      ).toBeNull();

      unmount();
    }
  });

  /**
   * The other unguarded finish-review fix: a degraded row was showing a
   * saturated green check, which the report calls "the single most misreadable
   * thing this page could show". Dropping `unverified` also stayed green.
   */
  it("withdraws the status colour on a degraded row, and only there", () => {
    renderTable();

    for (const run of DEGRADED_FIXTURES) {
      const chip = rowFor(run.run_id).querySelector<HTMLElement>(
        '[data-testid="status-chip"]',
      )!;
      // The word and glyph still state the status; only the colour claim goes.
      expect(chip.textContent).toContain(run.status);
      expect(chip.querySelector("svg")).not.toBeNull();
      expect(
        chip.className,
        "a degraded row must not assert a status colour it could not verify",
      ).not.toContain("text-status-");
    }

    for (const run of HEALTHY_FIXTURES) {
      const chip = rowFor(run.run_id).querySelector<HTMLElement>(
        '[data-testid="status-chip"]',
      )!;
      expect(chip.className).toContain(`text-status-${run.status}`);
    }
  });

  /**
   * Every absence marker states its own size rather than inheriting one.
   *
   * The verdict and spend `<td>`s carry no size token, so before this the word
   * fell through to the user agent's 16px and rendered larger than the 12px
   * chips and 14px readouts beside it — a visible break in a table whose whole
   * argument is a fixed four-step scale, and the direct cause of the spend
   * column overflowing its budget.
   *
   * jsdom has no layout engine, so this asserts the token rather than the
   * computed pixels; the pixel check lives in the browser measurement recorded
   * in `RunsTable`'s column-budget comment.
   */
  it("gives every flat-lined cell its own size token, never an inherited one", () => {
    renderTable();

    const markers = document.querySelectorAll('[data-flatlined]');
    expect(markers.length).toBeGreaterThan(0);
    for (const marker of markers) {
      expect(
        marker.className,
        "a flat-lined cell without a size token inherits the browser default",
      ).toContain("text-legend");
    }
  });

  it("says the list is empty rather than rendering an empty frame", () => {
    renderTable([]);

    expect(screen.queryAllByTestId("run-row")).toHaveLength(0);
    expect(screen.getByTestId("runs-empty")).toBeInTheDocument();
  });
});

describe("RunStatusChip", () => {
  it("renders a glyph, the enum member, and a status-keyed colour for every RunStatus", () => {
    // Iterated from the enum, so a new RunStatus member cannot ship unstyled.
    for (const status of RUN_STATUSES) {
      const { unmount } = render(<RunStatusChip status={status} />);

      const chip = screen.getByTestId("status-chip");
      expect(chip.textContent).toContain(status);
      expect(chip.querySelector("svg")).not.toBeNull();
      // Keyed to the enum member, so a component cannot drift from RunStatus.
      expect(chip.className).toContain(`text-status-${status}`);

      unmount();
    }
  });
});
