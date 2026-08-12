import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import type { RunDetail, RunListPage, RunSummary, Scoreboard } from "../../api/types";
import { DETAIL_COMPARE, RUN_ID_COMPARE, SCOREBOARD } from "../../mocks/fixtures";
import { server } from "../../mocks/server";
import { Compare } from "../Compare";

/**
 * The compare board.
 *
 * Two things are pinned here that no amount of green in the rest of the suite
 * would establish:
 *
 * 1. **The wire path.** `handlers.ts` mocks `GET /api/compare/:runId`, a route
 *    the real server has never had — `grep -c 'api/compare' src/evalyn/ui/server.py`
 *    is 0. A page built against it is green in vitest and dead in `evalyn ui`.
 *    The last test in this file asserts what the page actually asked for.
 * 2. **The half-empty board.** The only compare artifact in `runs/` has an
 *    empty `categories` and a fully measured `hard_metrics`, because
 *    `packs/twincore-injection` carries no rubric check and `run_compare`
 *    judges only rubric-checked probes. That is a correct result. The empty
 *    half must say *why* it is empty and must not read as a failure.
 */

const REAL_BOARD: Scoreboard = {
  ...SCOREBOARD,
  run_id: "20260812T164746520652-9ec23a3d-twincore-injection-compare",
  pack_name: "twincore-injection",
  created_at: "2026-08-12T16:47:46.520170+00:00",
  label_a: "2026-08-11 run",
  label_b: "2026-08-12 run",
  source_a: "runs/20260811T142601440952-ddfc322c-twincore-injection.json",
  source_b: "runs/20260812T103632337028-bed5f950-twincore-injection.json",
  created_at_a: "2026-08-11T14:26:01.439309+00:00",
  created_at_b: "2026-08-12T10:39:26.130197+00:00",
  // Verbatim from the artifact produced 2026-08-12 at $0.0000.
  categories: {},
  hard_metrics: {
    injection: {
      latency_mean_a: 2.814908505967697,
      latency_mean_b: 2.274650753461375,
      latency_p95_a: 13.109940875001485,
      latency_p95_b: 10.235264917006134,
      invariant_failures_a: 0,
      invariant_failures_b: 0,
      trials_a: 217,
      trials_b: 217,
    },
  },
  excluded_pairs: 0,
  judge_usd: 0,
  rubric_scores_untrusted: false,
};

const REAL_DETAIL: RunDetail = {
  ...DETAIL_COMPARE,
  run_id: REAL_BOARD.run_id,
  pack_name: "twincore-injection",
  created_at: REAL_BOARD.created_at,
  judge_usd: 0,
  rubric_scores_untrusted: false,
  compare: REAL_BOARD,
};

function summaryOf(detail: RunDetail): RunSummary {
  return {
    run_id: detail.run_id,
    mode: detail.mode,
    pack_name: detail.pack_name,
    created_at: detail.created_at,
    status: detail.status,
    degraded: detail.degraded,
    degraded_reason: detail.degraded_reason,
    capabilities: detail.capabilities,
    judge_usd: detail.judge_usd,
    verdict_hint: detail.verdict_hint,
  };
}

/**
 * A board on which no two figures coincide.
 *
 * The shipped fixture carries `wins_a: 1, ties: 1, flips: 1` and `217/217`
 * trials, so a full-object `toEqual` over it cannot say **which** field was
 * read: swapping two of them is invisible. Every number below is distinct
 * within its row and from its neighbours, which is what makes the same
 * assertion discriminating. Built here rather than in `mocks/fixtures.ts`,
 * which belongs to a parallel agent.
 */
const DISTINCT_BOARD: Scoreboard = {
  ...SCOREBOARD,
  run_id: "20260812T010203000000-abcdabcd-example-compare",
  pack_name: "twincore-injection",
  created_at: "2026-08-12T01:02:03.000000+00:00",
  label_a: "left candidate",
  label_b: "right candidate",
  source_a: "runs/20260801T010101000000-aaaaaaaa-example.json",
  source_b: "runs/20260802T020202000000-bbbbbbbb-example.json",
  created_at_a: "2026-08-01T01:01:01.000000+00:00",
  created_at_b: "2026-08-02T02:02:02.000000+00:00",
  categories: {
    boundary: {
      wins_a: 2,
      wins_b: 3,
      ties: 5,
      unsure: 7,
      flips: 11,
      criteria_judged: 13,
      flip_rate: 0.5,
    },
  },
  hard_metrics: {
    boundary: {
      latency_mean_a: 1.11,
      latency_mean_b: 2.75,
      latency_p95_a: 3.3,
      latency_p95_b: 4.95,
      invariant_failures_a: 5,
      invariant_failures_b: 6,
      trials_a: 7,
      trials_b: 10,
    },
  },
  excluded_pairs: 17,
  judge_usd: 1.2345,
  rubric_scores_untrusted: false,
  // The state no shipped fixture carries: a board the redactor touched.
  redacted: true,
};

const DISTINCT_DETAIL: RunDetail = {
  ...DETAIL_COMPARE,
  run_id: DISTINCT_BOARD.run_id,
  pack_name: DISTINCT_BOARD.pack_name,
  created_at: DISTINCT_BOARD.created_at,
  judge_usd: DISTINCT_BOARD.judge_usd,
  rubric_scores_untrusted: false,
  redacted: true,
  compare: DISTINCT_BOARD,
};

/** Serve exactly these boards, newest first, on the two routes that exist. */
function serveBoards(details: RunDetail[], nextCursor: string | null = null) {
  const asked: string[] = [];
  server.use(
    http.get("/api/runs", ({ request }) => {
      const url = new URL(request.url);
      asked.push(url.search);
      const rows =
        url.searchParams.get("mode") === "compare" ? details.map(summaryOf) : [];
      return HttpResponse.json({
        items: rows,
        next_cursor: nextCursor,
      } satisfies RunListPage);
    }),
    http.get("/api/runs/:runId", ({ params }) => {
      const detail = details.find((d) => d.run_id === String(params["runId"]));
      if (!detail) {
        return HttpResponse.json(
          { error: { code: "not_found", message: `no such run: ${String(params["runId"])}` } },
          { status: 404 },
        );
      }
      return HttpResponse.json(detail);
    }),
  );
  return asked;
}

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/compare"]}>
        <Compare />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Waits for a board to land, whichever half of it carries content. */
async function board() {
  return await screen.findByTestId("compare-board");
}

afterEach(() => server.events.removeAllListeners());

describe("the board", () => {
  it("opens on the newest compare run and names both sides", async () => {
    renderPage();
    await board();

    const sides = screen.getByTestId("compare-sides");
    expect(sides.textContent).toContain("baseline");
    expect(sides.textContent).toContain("candidate");
    // The two runs the board was built from, stamped, so "which candidate?" is
    // answerable without opening the artifact.
    expect(sides.textContent).toContain("2026-08-04 08:15:44Z");
    expect(sides.textContent).toContain("2026-08-05 09:00:00Z");
    expect(screen.getByTestId("compare-readout").textContent).toContain(
      RUN_ID_COMPARE,
    );
  });

  it("tallies every category the judge scored, and totals nothing else", async () => {
    renderPage();
    await board();

    const grounding = screen.getByTestId("verdict-row-grounding");
    const cells = within(grounding)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    // wins A · wins B · ties · unsure · flips · flip rate · criteria judged
    expect(cells).toEqual(["grounding", "1", "4", "1", "0", "1", "16.7%", "6"]);

    expect(screen.getByTestId("compare-verdicts").textContent).toContain(
      "1 pair was excluded from judging.",
    );
  });

  it("reports hard metrics beside the verdicts, both sides and the difference", async () => {
    serveBoards([REAL_DETAIL]);
    renderPage();
    await board();

    const mean = screen.getByTestId("metric-row-injection-latency_mean");
    expect(
      within(mean)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["Latency mean", "2.81s", "2.27s", "-0.54s"]);

    const p95 = screen.getByTestId("metric-row-injection-latency_p95");
    expect(
      within(p95)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["Latency p95", "13.11s", "10.24s", "-2.87s"]);

    const trials = screen.getByTestId("metric-row-injection-trials");
    expect(
      within(trials)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["Trials", "217", "217", "0"]);
  });

  it("flat-lines an unrecorded latency instead of reading it as zero", async () => {
    renderPage();
    await board();

    // The `injection` category of the shipped fixture never recorded latency.
    const mean = screen.getByTestId("metric-row-injection-latency_mean");
    const flatlined = [...mean.querySelectorAll("[data-flatlined]")];
    // Both sides and the difference: three empty cells, each of which says so.
    expect(flatlined).toHaveLength(3);
    expect(mean.textContent).toContain("unrecorded");
    expect(mean.textContent).not.toMatch(/\b0\.00s\b/);

    // Each empty cell states WHY it is empty — the mark and the short word are
    // the summary, and a blank reason leaves a keyboard and a screen reader
    // with a hairline and nothing else.
    expect(flatlined[0]?.getAttribute("title")).toContain(
      "latency was not recorded",
    );
    expect(flatlined[1]?.getAttribute("title")).toContain(
      "latency was not recorded",
    );
    expect(flatlined[2]?.getAttribute("title")).toContain(
      "a difference needs both sides",
    );
    expect(flatlined[2]?.getAttribute("data-flatlined")).toBe("n/a");
    // ...and the reason travels as text, not only as a tooltip.
    for (const cell of flatlined) {
      expect(cell.textContent).toContain(cell.getAttribute("title"));
    }
  });
});

/**
 * Which side is which.
 *
 * The whole purpose of this page is telling two candidates apart, and every
 * assertion above this block was **membership**, not identity: "the sides
 * region contains 'baseline' and 'candidate'" stays true with A and B
 * transposed. Five independent transpositions shipped green — the two side
 * blocks, the two verdict headers, the two metric headers, and the accessors
 * behind them — because the fixtures are symmetric and no assertion read a
 * column header at all. These bind the letter to the value.
 */
describe("which side is which", () => {
  /** The two side blocks, in the order the page lays them out. */
  function sideBlocks(): [Element, Element] {
    const children = [...screen.getByTestId("compare-sides").children];
    expect(children).toHaveLength(2);
    return [children[0]!, children[1]!];
  }

  /** Every `<th>` of every table inside a region, one array per table. */
  function headerRows(region: string): string[][] {
    return within(screen.getByTestId(region))
      .getAllByRole("table")
      .map((table) =>
        [...table.querySelectorAll("thead th")].map((th) => th.textContent ?? ""),
      );
  }

  it("binds each side letter to its own label, stamp and source", async () => {
    renderPage();
    await board();
    const [first, second] = sideBlocks();
    const letter = (block: Element) =>
      within(block as HTMLElement).getByRole("heading").textContent;

    // A is first, and everything in that block belongs to the A run.
    expect(letter(first)).toBe("A");
    expect(first.textContent).toContain("baseline");
    expect(first.textContent).toContain("2026-08-04 08:15:44Z");
    expect(first.textContent).toContain("20260804T081544953468-53e4125b-example.json");
    // ...and nothing from the B run leaked into it.
    expect(first.textContent).not.toContain("candidate");
    expect(first.textContent).not.toContain("2026-08-05 09:00:00Z");
    expect(first.textContent).not.toContain("0badc0de");

    expect(letter(second)).toBe("B");
    expect(second.textContent).toContain("candidate");
    expect(second.textContent).toContain("2026-08-05 09:00:00Z");
    expect(second.textContent).toContain("20260805T090000000000-0badc0de-example.json");
    expect(second.textContent).not.toContain("baseline");
    expect(second.textContent).not.toContain("2026-08-04 08:15:44Z");
  });

  it("heads the verdict columns in the order its cells are read", async () => {
    renderPage();
    await board();

    expect(headerRows("compare-verdicts")).toEqual([
      [
        "Category",
        "A wins",
        "B wins",
        "Ties",
        "Unsure",
        "Flips",
        "Flip rate",
        "Criteria judged",
      ],
    ]);
  });

  it("heads the metric columns A, B, and the difference as B − A", async () => {
    renderPage();
    await board();

    // Every category's table, so a second block cannot drift from the first.
    for (const row of headerRows("compare-metrics")) {
      expect(row).toEqual(["Measurement", "A", "B", "B − A"]);
    }
    expect(headerRows("compare-metrics").length).toBeGreaterThan(0);
  });

  it("reads every tally field into its own column, on a board with no two figures alike", async () => {
    serveBoards([DISTINCT_DETAIL]);
    renderPage();
    await board();

    expect(
      within(screen.getByTestId("verdict-row-boundary"))
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
      // wins_a 2 · wins_b 3 · ties 5 · unsure 7 · flips 11 · rate 0.5 · judged 13
    ).toEqual(["boundary", "2", "3", "5", "7", "11", "50.0%", "13"]);
  });

  it("reads every hard-metric field into its own side, on the same board", async () => {
    serveBoards([DISTINCT_DETAIL]);
    renderPage();
    await board();

    const cells = (key: string) =>
      within(screen.getByTestId(`metric-row-boundary-${key}`))
        .getAllByRole("cell")
        .map((cell) => cell.textContent);

    expect(cells("latency_mean")).toEqual(["Latency mean", "1.11s", "2.75s", "+1.64s"]);
    expect(cells("latency_p95")).toEqual(["Latency p95", "3.30s", "4.95s", "+1.65s"]);
    expect(cells("invariant_failures")).toEqual(["Invariant failures", "5", "6", "+1"]);
    expect(cells("trials")).toEqual(["Trials", "7", "10", "+3"]);
  });

  it("distinguishes ties from flips on the shipped board too", async () => {
    renderPage();
    await board();

    // `injection` is the discriminating shipped row: 2/1/0/1/0 tells wins_a
    // from wins_b and ties from unsure, where `grounding` (1/4/1/0/1) cannot
    // tell ties from flips.
    expect(
      within(screen.getByTestId("verdict-row-injection"))
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["injection", "2", "1", "0", "1", "0", "0.0%", "4"]);
  });
});

describe("the readout", () => {
  it("states this board's own pack, stamp, spend and criteria count", async () => {
    renderPage();
    await board();

    const readout = screen.getByTestId("compare-readout").textContent ?? "";
    expect(readout).toContain("example");
    // The BOARD's stamp, not either side's run stamp.
    expect(readout).toContain("2026-08-06 09:10:11Z");
    expect(readout).not.toContain("2026-08-04 08:15:44Z");
    expect(readout).toContain("$0.0421");
    expect(readout).toMatch(/\b10 criteria judged\b/);
  });

  it("states a different board's figures, so none of them is a constant", async () => {
    serveBoards([DISTINCT_DETAIL]);
    renderPage();
    await board();

    const readout = screen.getByTestId("compare-readout").textContent ?? "";
    expect(readout).toContain("twincore-injection");
    expect(readout).toContain("2026-08-12 01:02:03Z");
    expect(readout).not.toContain("2026-08-01 01:01:01Z");
    expect(readout).toContain("$1.2345");
    expect(readout).toMatch(/\b13 criteria judged\b/);
  });

  it("says a board passed through the redactor, and only when it did", async () => {
    serveBoards([DISTINCT_DETAIL]);
    renderPage();
    await board();
    expect(screen.getByTestId("compare-readout").textContent).toContain(
      "passed through the redactor",
    );
    cleanup();

    server.resetHandlers();
    renderPage();
    await board();
    expect(screen.getByTestId("compare-readout").textContent).not.toContain(
      "passed through the redactor",
    );
  });
});

describe("the board selector", () => {
  it("says older boards exist only when the index says there are more", async () => {
    serveBoards([REAL_DETAIL], "2026-08-01T00:00:00+00:00|20260801T000000000000-deadbeef-x");
    renderPage();
    await board();

    expect(screen.getByTestId("compare-boards").textContent).toContain(
      "older boards exist and are not listed here",
    );
  });

  it("claims nothing about older boards when the page is the whole list", async () => {
    serveBoards([REAL_DETAIL]);
    renderPage();
    await board();

    // A false completeness claim is worse than none: this directory's list is
    // complete, and saying otherwise sends the operator looking for runs that
    // are not there.
    expect(screen.getByTestId("compare-boards").textContent).not.toContain(
      "older boards",
    );
  });
});

describe("the empty verdict half", () => {
  it("says no rubric-checked probes were judged, beside a fully measured metric half", async () => {
    serveBoards([REAL_DETAIL]);
    renderPage();
    await board();

    const empty = screen.getByTestId("compare-verdicts-empty");
    expect(empty.textContent).toContain("No rubric-checked probes were judged");
    expect(empty.textContent).toContain("rubric check");

    // Not an error, not a skip, not a load in flight — and the operator can
    // see for themselves, because the other half is on screen with real
    // numbers in it.
    expect(empty.textContent).not.toMatch(
      /fail|error|could not|unable|skip|refus|loading|pending|unavailable|missing|no data|yet/i,
    );
    expect(screen.getByTestId("compare-metrics").textContent).toContain("2.81s");
    // Nothing is offered to retry, because nothing went wrong.
    expect(screen.queryByRole("button", { name: /retry|try again|reload/i })).toBeNull();
  });

  it("carries no exclusion note when no pair was excluded", async () => {
    serveBoards([REAL_DETAIL]);
    renderPage();
    await board();

    expect(screen.getByTestId("compare-verdicts").textContent).not.toMatch(
      /excluded from judging/,
    );
  });
});

describe("what the board refuses to say", () => {
  it("computes no winner and ranks nothing, on either shape of board", async () => {
    serveBoards([REAL_DETAIL]);
    const { unmount } = renderPage();
    await board();
    expect(document.body.textContent).not.toMatch(
      /better|worse|faster|slower|improve|regress|recommend/i,
    );
    expect(screen.getByTestId("compare-advisory").textContent).toContain(
      "no combined winner is computed",
    );
    unmount();

    server.resetHandlers();
    renderPage();
    await board();
    expect(document.body.textContent).not.toMatch(
      /better|worse|faster|slower|improve|regress|recommend/i,
    );
  });

  it("warns that rubric scores are untrusted with a glyph, not colour alone", async () => {
    renderPage();
    await board();

    const banner = screen.getByTestId("compare-untrusted");
    expect(banner.textContent).toMatch(/untrusted/i);
    expect(
      banner.querySelector("svg"),
      "the untrusted-rubric warning renders without a glyph",
    ).not.toBeNull();
  });

  it("shows no untrusted warning on a board the calibration did not flag", async () => {
    serveBoards([REAL_DETAIL]);
    renderPage();
    await board();

    expect(screen.queryByTestId("compare-untrusted")).toBeNull();
  });
});

describe("choosing a board", () => {
  it("lists the compare runs and re-reads the board when one is chosen", async () => {
    const older: RunDetail = {
      ...REAL_DETAIL,
      run_id: "20260810T090000000000-11112222-twincore-injection-compare",
      created_at: "2026-08-10T09:00:00.000000+00:00",
      compare: {
        ...REAL_BOARD,
        run_id: "20260810T090000000000-11112222-twincore-injection-compare",
        label_a: "older A",
        label_b: "older B",
      },
    };
    serveBoards([REAL_DETAIL, older]);
    const user = userEvent.setup();
    renderPage();
    await board();

    // Newest first, and the newest is the one already open.
    const keys = within(screen.getByTestId("compare-boards")).getAllByTestId("detent");
    expect(keys).toHaveLength(2);
    expect(keys[0]).toHaveAttribute("aria-pressed", "true");

    await user.click(keys[1]!);
    await waitFor(() =>
      expect(screen.getByTestId("compare-sides").textContent).toContain("older A"),
    );
  });

  it("says the directory holds no compare run rather than drawing an empty board", async () => {
    serveBoards([]);
    renderPage();

    const empty = await screen.findByTestId("compare-none");
    expect(empty.textContent).toMatch(/no compare runs/i);
    // The operator is told how one gets here. `evalyn compare` is the only way.
    expect(empty.textContent).toContain("evalyn compare");
    expect(screen.queryByTestId("compare-board")).toBeNull();
  });

  it("says the read failed, with a glyph, when the server refuses", async () => {
    server.use(
      http.get("/api/runs", () =>
        HttpResponse.json(
          { error: { code: "internal", message: "the index is unreadable" } },
          { status: 500 },
        ),
      ),
    );
    renderPage();

    const failure = await screen.findByTestId("compare-error");
    expect(failure.textContent).toContain("the index is unreadable");
    expect(failure.querySelector("svg")).not.toBeNull();
  });

  it("states the absence rather than crashing when a compare run carries no scoreboard", async () => {
    serveBoards([{ ...REAL_DETAIL, compare: null }]);
    renderPage();

    const empty = await screen.findByTestId("compare-unreadable");
    expect(empty.textContent).toMatch(/no scoreboard/i);
  });
});

describe("the wire", () => {
  /**
   * The trap this page was briefed around.
   *
   * `handlers.ts:438` serves `GET /api/compare/:runId`, which the real server
   * does not have and never had. Because it *is* mocked, a page written against
   * it passes every other test in this file. This one reads back the URLs the
   * page actually requested.
   */
  it("reads the board off the run detail, never off a compare route", async () => {
    const seen: string[] = [];
    server.events.on("request:start", ({ request }) => {
      seen.push(new URL(request.url).pathname);
    });

    renderPage();
    await board();

    expect(seen).toContain(`/api/runs/${RUN_ID_COMPARE}`);
    expect(
      seen.filter((path) => path.startsWith("/api/compare")),
      "the compare page asked a route the real server does not have",
    ).toEqual([]);
  });

  it("asks the index for compare runs only", async () => {
    const asked = serveBoards([REAL_DETAIL]);
    renderPage();
    await board();

    expect(asked).toEqual(["?mode=compare"]);
  });
});

describe("wide content", () => {
  it("scrolls its tables inside their own container, never the page", async () => {
    renderPage();
    await board();

    for (const testId of ["compare-verdicts", "compare-metrics"]) {
      const tables = within(screen.getByTestId(testId)).getAllByRole("table");
      expect(tables.length).toBeGreaterThan(0);
      for (const table of tables) {
        expect(
          table.parentElement?.className,
          `a ${testId} table can push the instrument face sideways`,
        ).toContain("overflow-x-auto");
      }
    }
  });
});
