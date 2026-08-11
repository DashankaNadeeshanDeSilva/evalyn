import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { RUN_MODES, RUN_STATUSES, VERDICT_HINTS } from "../../api/types";
import { formatUsd, formatUtc } from "../../format";
import { RUN_SUMMARIES, SUMMARY_GATE } from "../../mocks/fixtures";
import { RunStatusChip } from "../RunStatusChip";
import { COLUMNS, RunsTable } from "../RunsTable";

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

/**
 * The column budget, made executable.
 *
 * This budget has now been sized against the wrong worst case **three times** —
 * against the fixtures (all `passed`), then against STATUS while VERDICT and
 * SPEND were the cells that had gained content, then against a `Flatline` while
 * `gate unknown` was the widest thing VERDICT can hold. Each time the comment
 * above `COLUMNS` said the numbers were measured, and each time the next
 * reviewer found a cell overflowing. A comment cannot fail a build.
 *
 * So the worst case is re-derived here from the **types** — `RUN_STATUSES`,
 * `RUN_MODES`, `VERDICT_HINTS` — rather than from the fixtures or from an
 * author's sample, which is the exact substitution that caused all three.
 *
 * jsdom has no layout engine, so this is a *model* of the browser rather than
 * the browser. It is legitimate only because the face is monospace: width is a
 * linear function of character count. Every constant below was calibrated
 * against Chrome, against the built stylesheet, on the real component markup,
 * with the scroller pinned to the table's 78rem floor and `sr-only` nodes
 * removed:
 *
 *   measured 151.86  model 151.6   "failed_to_start" + mark   (STATUS)
 *   measured 125.89  model 125.7   "gate unknown" + mark      (VERDICT)
 *   measured 102.17  model 102.0   "unrecorded" + mark        (SPEND)
 *   measured 168.58  model 168.0   "2026-08-06 09:10:11Z"     (CREATED)
 *   measured  80.52  model  80.4   "unknown" + mark           (PACK)
 *   measured  67.43  model  67.2   "discover"                 (MODE)
 *   measured 320.30  model 319.2   a 38-char run id           (RUN)
 *
 * The model runs up to ~1.1px narrow over a long string, so a column must clear
 * its worst case by `MODEL_SLOP` rather than merely reach it. Re-measure in a
 * browser when the type scale, the icons or the padding change; this test
 * guards the arithmetic, not the typography.
 */
const FLOOR_PX = 78 * 16; // `min-w-[78rem]`, the table's own floor

/** Monospace advance = 0.6em, plus `tracking-legend` (0.12em) where it applies. */
const LEGEND = 12 * 0.6;
const LEGEND_TRACKED = LEGEND + 12 * 0.12;
const READOUT = 14 * 0.6;
/** `h-4 w-4` status/verdict glyph, and `h-4 w-6` flat-line mark, + `gap-1.5`. */
const STATUS_MARK = 16 + 6;
const FLATLINE_MARK = 24 + 6;
/** The model's calibration error against Chrome, rounded up. */
const MODEL_SLOP = 2;

/**
 * Horizontal padding per cell, from the classes the cells actually carry — plus
 * the 1px the user agent gives every `<td>`, which Tailwind's preflight does not
 * reset and which the browser measurement confirmed is really there.
 */
const PADDING_X: Record<string, number> = {
  status: 24 + 12, // `pl-4 sm:pl-6` + `pr-3`
  run: 1 + 12,
  mode: 1 + 12,
  pack: 1 + 12,
  created: 1 + 12,
  verdict: 1 + 12,
  spend: 12 + 24, // `pl-3` + `pr-4 sm:pr-6`
};

const flatline = (word: string) => FLATLINE_MARK + word.length * LEGEND;
const tracked = (word: string) => word.length * LEGEND_TRACKED;

/** The widest content each column can ever hold, derived from its own type. */
const WIDEST: Record<string, { what: string; px: number }> = (() => {
  const max = (candidates: { what: string; px: number }[]) =>
    candidates.reduce((a, b) => (b.px > a.px ? b : a));
  return {
    status: max(
      RUN_STATUSES.map((s) => ({ what: s, px: STATUS_MARK + tracked(s) })),
    ),
    // A run id's trailing slug is unbounded, so this column cannot be sized
    // against a worst case at all — it is `break-all`, and an unusually long id
    // costs a second line rather than a collision. The canonical 38-char stem
    // is asserted to still fit on one line.
    run: { what: "a 38-char run id", px: 38 * READOUT },
    mode: max(RUN_MODES.map((m) => ({ what: m, px: m.length * READOUT }))),
    // `pack_name` is likewise unbounded and likewise wraps; the bounded worst
    // case is the marker shown when the artifact recorded no pack name.
    pack: { what: "flat-lined `unknown`", px: flatline("unknown") },
    created: {
      what: "a formatted UTC stamp",
      px: formatUtc("2026-08-06T09:10:11.123456+00:00").length * READOUT,
    },
    verdict: max([
      ...VERDICT_HINTS.map((h) => ({
        what: `gate ${h}`,
        px: STATUS_MARK + tracked(`gate ${h}`),
      })),
      { what: "flat-lined `no gate`", px: flatline("no gate") },
      { what: "flat-lined `unreadable`", px: flatline("unreadable") },
    ]),
    spend: max([
      { what: "flat-lined `unrecorded`", px: flatline("unrecorded") },
      { what: "a four-decimal figure", px: formatUsd(9999.9999).length * READOUT },
    ]),
  };
})();

describe("the column budget", () => {
  it("still spends exactly the table's width, no more and no less", () => {
    const total = COLUMNS.reduce(
      (sum, column) => sum + Number.parseFloat(column.width),
      0,
    );
    expect(total, "the column widths must sum to 100%").toBeCloseTo(100, 6);
  });

  it("gives every column room for the widest content its own type can hold", () => {
    for (const column of COLUMNS) {
      const box = (Number.parseFloat(column.width) / 100) * FLOOR_PX;
      const avail = box - PADDING_X[column.key]!;
      const worst = WIDEST[column.key]!;
      expect(
        avail,
        `${column.key} at ${column.width} of the 78rem floor leaves ${avail.toFixed(1)}px ` +
          `for ${worst.what}, which needs ${worst.px.toFixed(1)}px — ` +
          `\`table-fixed\` does not clip it, it lets it collide with the next cell`,
      ).toBeGreaterThanOrEqual(worst.px + MODEL_SLOP);
    }
  });

  /**
   * The header is `whitespace-nowrap` too, and "Verdict (hint)" is longer than
   * some of the data beneath it — a column can be wide enough for its values
   * and still overflow its own label.
   */
  it("gives every column room for its own header label", () => {
    for (const column of COLUMNS) {
      const box = (Number.parseFloat(column.width) / 100) * FLOOR_PX;
      const avail = box - PADDING_X[column.key]!;
      // Uppercased in CSS, so the label's own casing does not change its width.
      const label = tracked(column.label);
      expect(
        avail,
        `${column.key}'s header "${column.label}" needs ${label.toFixed(1)}px`,
      ).toBeGreaterThanOrEqual(label + MODEL_SLOP);
    }
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
