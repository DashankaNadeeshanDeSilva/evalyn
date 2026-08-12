import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import type { FindingRow } from "../../api/types";
import { FINDING_DETAIL, FINDING_ROWS } from "../../mocks/fixtures";
import { server } from "../../mocks/server";
import { Discoveries } from "../Discoveries";

/**
 * The discoveries page — the staging bench.
 *
 * Three facts about the real data drive almost everything below, and none of
 * them are visible in the fixtures alone.
 *
 * **A staged finding is a file, and adopting it is consequential.** Every file
 * `discover` writes carries its own header saying so: the probe is STAGED, not
 * adopted; `<pack>/discoveries/*.yaml` is **gitignored**; and moving the file
 * out of that directory is precisely what removes the guard. The two real
 * findings in `packs/twincore/discoveries/` embed live data captured from the
 * target — `discovered-pii-leak-0bf80f3b.yaml` carries a real email address
 * verbatim as a `not_contains` value, because redacting it would break the
 * outcome-graded confirmation the check exists to make. A page that lists these
 * as inert rows, with no word about what adopting one does, is lying by
 * omission about the only action it exists to support.
 *
 * **The bench is empty today.** `packs/twincore/discoveries/` is gitignored and
 * `packs/example/discoveries/` holds nothing but a `.gitkeep`, so the ordinary
 * rendition of this page against a clean checkout is *no findings at all* —
 * the same shape as the judge-trust page's never-calibrated state, and it has
 * to read as a deliberate statement rather than as a page that failed to load.
 *
 * **Nothing here may reveal.** Revealing is per-object and gated on a token
 * minted at server start and written to stderr; the browser has no way to know
 * it. On 2026-08-14 this page is projected, and the value behind the redaction
 * marker on the safety-critical finding is a real person's email address. So
 * the absence of a reveal control is a property under test, not an omission.
 */

function renderDiscoveries() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Discoveries />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Serve an arbitrary bench, unpaginated. */
function withFindings(items: FindingRow[]) {
  server.use(
    http.get("/api/discoveries", () =>
      HttpResponse.json({ items, next_cursor: null }),
    ),
  );
}

/** The page, once the first read has landed. */
async function settled() {
  return await screen.findByTestId("discoveries-bench");
}

/**
 * The utilities that clip a value to one line, spelled in halves.
 *
 * jsdom performs no layout, so no assertion here can measure a pixel — what a
 * test *can* hold is the class contract, and it is the only thing in this suite
 * that discriminates the three layout defects this page had: a provenance
 * sentence clipped to one line, a ~691px file path shredded into a narrow
 * gutter, and a `git mv` whose destination fell off the right edge behind a
 * scrollbar. All three leave `textContent` identical, which is why the test
 * named for the first of them could not observe it.
 *
 * The halves are not decoration: the build scans every `.ts`/`.tsx` under
 * `src/` for utility candidates, does not strip comments, and does not exempt
 * test files — so spelling one of these whole would ship a real CSS rule that
 * nothing renders. Split, the extractor sees nothing and the assertion is
 * unchanged.
 */
const CLIPS_TO_ONE_LINE = [
  "trun" + "cate",
  "text-" + "ellipsis",
  "whitespace-" + "no" + "wrap",
  "over" + "flow-hidden",
];

/** Which one-line-clipping utilities this element carries, if any. */
function clippingOn(element: Element): string[] {
  const carried = element.className.toString().split(/\s+/);
  return CLIPS_TO_ONE_LINE.filter((utility) => carried.includes(utility));
}

/** The `<dd>` whose whole value is `text`, searched under `root`. */
function valueCell(root: HTMLElement, text: string): HTMLElement {
  const found = [...root.querySelectorAll("dd")].find(
    (dd) => dd.textContent === text,
  );
  if (!found) throw new Error(`no value cell holding: ${text.slice(0, 60)}…`);
  return found;
}

function rowFor(probeId: string): HTMLElement {
  const found = screen
    .getAllByTestId("finding-row")
    .find((candidate) => candidate.dataset["probe"] === probeId);
  if (!found) throw new Error(`no row for ${probeId}`);
  return found;
}

const HALLUCINATION = FINDING_ROWS[0]!.probe_id;
const PII_LEAK = FINDING_ROWS[1]!.probe_id;

/**
 * A bench whose four figures are four different numbers.
 *
 * The real corpus is two rows — one confirmed, one safety-critical, one
 * flagged duplicate — so every figure the readout prints is `1` or `2`, and an
 * assertion over that corpus cannot tell which reading carried the digit it
 * found: swapping `safetyCritical` for `confirmed`, or either for `total`,
 * leaves a string that still contains a `2` and still contains the word
 * "safety-critical". The sibling model test broke the same tie with a third row
 * and said so in terms; the readout, which renders the same two counts, was
 * left on the tied pair.
 *
 * So: 4 staged, 1 confirmed, 2 safety-critical, 3 flagged duplicate. Four
 * distinct numbers means each figure can only be satisfied by its own count.
 */
const UNTIED_BENCH: FindingRow[] = [
  {
    ...FINDING_ROWS[0]!,
    probe_id: "discovered-untied-00000001",
    confirmed: true,
    safety_critical: false,
    duplicate_of: null,
    duplicate_reason: null,
  },
  {
    ...FINDING_ROWS[0]!,
    probe_id: "discovered-untied-00000002",
    confirmed: false,
    safety_critical: true,
    duplicate_of: "discovered-untied-00000001",
    duplicate_reason: "same objective and near-identical final turn",
  },
  {
    ...FINDING_ROWS[0]!,
    probe_id: "discovered-untied-00000003",
    confirmed: false,
    safety_critical: true,
    duplicate_of: "discovered-untied-00000001",
    duplicate_reason: "same objective and near-identical final turn",
  },
  {
    ...FINDING_ROWS[0]!,
    probe_id: "discovered-untied-00000004",
    confirmed: false,
    safety_critical: false,
    duplicate_of: "discovered-untied-00000001",
    duplicate_reason: null,
  },
];

describe("the bench lists what discover staged", () => {
  it("renders a row per staged finding, identified by its probe id", async () => {
    renderDiscoveries();
    await settled();

    expect(screen.getAllByTestId("finding-row")).toHaveLength(
      FINDING_ROWS.length,
    );
    expect(rowFor(HALLUCINATION)).toBeTruthy();
    expect(rowFor(PII_LEAK)).toBeTruthy();
  });

  it("states the bench's size, and claims nothing while still reading", async () => {
    withFindings(UNTIED_BENCH);
    renderDiscoveries();

    /*
     * Zero is a measurement, and before the read lands nobody has one — but
     * asserting only the absence of a digit is too weak to bite: a readout that
     * says "nothing is staged" before it has looked prints no digit and is
     * still a false claim about the bench. Both the count and the emptiness
     * have to be withheld, and the readout has to say what it is doing instead.
     */
    const early = screen.getByTestId("discoveries-readout").textContent ?? "";
    expect(early.toLowerCase()).toContain("reading");
    expect(early, "a count was printed before the findings had been read").not.toMatch(
      /\d/,
    );
    expect(
      early.toLowerCase(),
      "the bench was called empty before it had been read",
    ).not.toContain("nothing is staged");

    await settled();
    const readout = screen.getByTestId("discoveries-readout").textContent ?? "";
    /*
     * Each digit is asserted beside its own label, over a bench where no two
     * figures share a value. "Contains a 2 somewhere" was satisfied by the
     * total alone and left the other three readings pinned by nothing.
     */
    expect(readout, "the staged count is not the number of rows").toMatch(
      /4\s*staged/,
    );
    expect(
      readout,
      "the confirmed count was taken from another reading",
    ).toMatch(/1\s*confirmed/);
    expect(
      readout,
      "the safety-critical count was taken from another reading",
    ).toMatch(/2\s*safety-critical/);
    expect(
      readout,
      "the duplicate count was taken from another reading",
    ).toMatch(/3\s*flagged duplicate/);
  });
});

/**
 * The projector requirement: a safety-critical finding and an ordinary one must
 * be told apart from the back of a room, and never by colour.
 */
describe("safety-critical is legible without colour", () => {
  it("marks the safety-critical row with a word, not a hue", async () => {
    renderDiscoveries();
    await settled();

    const critical = within(rowFor(PII_LEAK));
    const mark = critical.getByTestId("safety-critical-mark");
    expect(mark.textContent?.toLowerCase()).toContain("safety-critical");

    // A glyph beside the word, so the state survives greyscale *and* a reader
    // who cannot resolve the letterforms at distance.
    expect(mark.querySelector("svg")).not.toBeNull();
  });

  it("does not mark the ordinary row, and says so in words rather than by absence", async () => {
    renderDiscoveries();
    await settled();

    const ordinary = within(rowFor(HALLUCINATION));
    expect(
      ordinary.queryByTestId("safety-critical-mark"),
      "an ordinary finding was flagged safety-critical",
    ).toBeNull();
    // `Flatline`'s rule, applied to a boolean: absence must be stated, because
    // a missing mark and an unrendered mark look identical.
    expect(ordinary.getByTestId("finding-safety").textContent).toContain(
      "not safety-critical",
    );
  });

  /**
   * `status-*` is keyed to `RunStatus` members. A finding's safety class is not
   * a run state, so the same ruling the trends and judge-trust pages carry
   * applies: no status ink enters this page, and the mark cannot quietly become
   * a hue that a colourblind operator reads as nothing at all.
   */
  it("carries no status ink anywhere on the bench", async () => {
    renderDiscoveries();
    await settled();

    const hued = [...document.querySelectorAll("[class]")].filter((node) =>
      /(?:^|\s)(?:text|bg|border)-status-/.test(node.className.toString()),
    );
    expect(
      hued.map((n) => n.className.toString()),
      "status ink entered a page whose subject is not a run state",
    ).toEqual([]);
  });
});

describe("the page is honest about what a replay did and did not establish", () => {
  it("does not report a budget skip as a failure to reproduce", async () => {
    renderDiscoveries();
    await settled();

    const critical = rowFor(PII_LEAK).textContent?.toLowerCase() ?? "";
    expect(critical).toContain("budget");
    expect(
      critical,
      "a replay that never ran was reported as one that failed",
    ).not.toContain("not reproduce");
  });

  it("names the finding a duplicate flags, and why", async () => {
    renderDiscoveries();
    await settled();

    const duplicate = within(rowFor(PII_LEAK)).getByTestId("finding-duplicate");
    expect(duplicate.textContent).toContain(HALLUCINATION);
    expect(duplicate.textContent).toContain(
      "same objective and near-identical final turn",
    );
  });
});

/**
 * The instruction the page exists to give. Lifted from the header `discover`
 * writes into every staged file, because that header is the authority.
 */
describe("adopting a finding is presented as the consequential act it is", () => {
  it("says the staged files are gitignored and that adopting removes the guard", async () => {
    renderDiscoveries();
    await settled();

    const notice = screen.getByTestId("staging-notice").textContent ?? "";
    expect(notice.toLowerCase()).toContain("gitignored");
    expect(notice.toLowerCase()).toContain("live data");
  });

  it("gives the exact move, rather than describing it", async () => {
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const move = await screen.findByTestId("adopt-command");
    const command = move.textContent ?? "";
    expect(command).toContain("git mv");
    expect(command).toContain("discoveries/");
    expect(command).toContain("probes/");

    /*
     * And legibly. The line is ~130 characters and its two halves are the whole
     * message — *from* the gitignored directory, *to* the tracked one. Clipped
     * or scrolled, the half that disappears is the destination, and on a
     * projector that is a `git mv` whose target nobody in the room can read.
     * Both renditions leave the assertions above passing, so the wrapping is
     * held here rather than inferred from the text.
     */
    const carried = move.className.split(/\s+/);
    expect(
      clippingOn(move),
      "the git mv destination was clipped off the end of the line",
    ).toEqual([]);
    expect(
      carried,
      "the git mv destination was put behind a horizontal scrollbar",
    ).not.toContain("overflow-x-auto");
    expect(carried).toContain("whitespace-pre-wrap");
  });

  /**
   * The path is the one value an operator retypes or pastes, and at 1440 the
   * two-column span offered ~620px for the ~691px it needs — so it broke
   * mid-identifier and read as two different files. It takes the whole grid
   * row, and it is never clipped: an elided path is a path that moves a file
   * somewhere nobody meant.
   */
  it("gives the staged file's path the whole row, unclipped", async () => {
    renderDiscoveries();
    await settled();

    const path = valueCell(rowFor(HALLUCINATION), FINDING_ROWS[0]!.probe_path);
    expect(
      clippingOn(path),
      "the staged file's path was clipped to one line",
    ).toEqual([]);
    expect(
      path.parentElement?.className,
      "the path was put back into a two-column span it does not fit",
    ).toContain("col-span-full");
  });

  it("does not offer a staging notice when nothing is staged", async () => {
    withFindings([]);
    renderDiscoveries();
    await settled();

    expect(
      screen.queryByTestId("staging-notice"),
      "a caution was printed about files that do not exist",
    ).toBeNull();
  });
});

describe("an empty bench is a statement, not a frame with no rows", () => {
  it("names what would put something here", async () => {
    withFindings([]);
    renderDiscoveries();
    await settled();

    const empty = screen.getByTestId("discoveries-empty").textContent ?? "";
    expect(empty).toContain("evalyn discover");
    expect(screen.queryAllByTestId("finding-row")).toEqual([]);
  });

  it("offers no objective filter when there is nothing to filter", async () => {
    withFindings([]);
    renderDiscoveries();
    await settled();

    expect(
      screen.queryAllByTestId("detent"),
      "a filter was offered over an empty vocabulary",
    ).toEqual([]);
  });
});

describe("the objective filter asks the server, not the DOM", () => {
  it("sends the chosen objective as ?objective= on the wire", async () => {
    const asked: string[] = [];
    server.events.on("request:start", ({ request }) => {
      const url = new URL(request.url);
      if (url.pathname === "/api/discoveries") asked.push(url.search);
    });

    renderDiscoveries();
    await settled();

    await userEvent.click(screen.getByRole("button", { name: "pii" }));

    // Client-side filtering would satisfy any DOM assertion here, so the
    // request itself is what gets asserted: the cursor grammar and the
    // server's own filter are the only correct pagination.
    await waitFor(() => {
      expect(asked.some((search) => search.includes("objective=pii"))).toBe(
        true,
      );
    });
    server.events.removeAllListeners();
  });

  it("offers one position per objective the loaded rows carry", async () => {
    renderDiscoveries();
    await settled();

    const labels = screen
      .getAllByTestId("detent")
      .map((d) => d.dataset["value"]);
    expect(labels).toEqual(["All", "hallucination", "pii"]);
  });

  /**
   * A selector that destroys itself on first use.
   *
   * The filter is applied **server-side**, so the rows on screen while it is
   * active are exactly the ones that match — and a vocabulary derived from the
   * current rows would therefore delete every other position the moment one was
   * chosen, stranding the operator on a filter they cannot leave except through
   * `All`. The positions accumulate instead.
   */
  it("keeps every position after one is chosen and the rows narrow", async () => {
    renderDiscoveries();
    await settled();

    await userEvent.click(screen.getByRole("button", { name: "pii" }));
    await waitFor(() =>
      expect(screen.getAllByTestId("finding-row")).toHaveLength(1),
    );

    expect(
      screen.getAllByTestId("detent").map((d) => d.dataset["value"]),
      "choosing an objective deleted the positions the operator would go back to",
    ).toEqual(["All", "hallucination", "pii"]);
  });
});

describe("pagination hands the server's cursor back verbatim", () => {
  it("asks for the next page with the opaque cursor the server returned", async () => {
    const cursor = "2026-08-10T12:00:00.000000+00:00|20260810T120000-abcdef12";
    let call = 0;
    const asked: string[] = [];
    server.use(
      http.get("/api/discoveries", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("before") ?? "");
        call += 1;
        return HttpResponse.json(
          call === 1
            ? { items: [FINDING_ROWS[0]], next_cursor: cursor }
            : { items: [FINDING_ROWS[1]], next_cursor: null },
        );
      }),
    );

    renderDiscoveries();
    await settled();

    await userEvent.click(screen.getByTestId("discoveries-more"));

    await waitFor(() => expect(screen.getAllByTestId("finding-row")).toHaveLength(2));
    // Verbatim: nothing on the client parses, compares or rebuilds a cursor.
    expect(asked[1]).toBe(cursor);
  });

  it("offers no next-page key once the server says the list has ended", async () => {
    renderDiscoveries();
    await settled();
    expect(screen.queryByTestId("discoveries-more")).toBeNull();
  });
});

describe("opening a finding brings the answer to the operator", () => {
  it("moves focus into the panel it just opened", async () => {
    renderDiscoveries();
    await settled();

    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const panel = await screen.findByTestId("finding-panel");
    // The whole lesson of the 565px-off-screen panel: content in the DOM is
    // not content on the screen, and focus is the only half of that a test can
    // hold. `scrollIntoView` is the other half and lives in `useRevealOnOpen`.
    await waitFor(() => expect(panel).toHaveFocus());
  });

  it("shows the session and the checks behind the finding", async () => {
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const panel = within(await screen.findByTestId("finding-panel"));
    expect(panel.getAllByTestId("transcript-turn").length).toBe(
      FINDING_DETAIL.turns.length,
    );
    expect(panel.getAllByTestId("check-evidence").length).toBe(
      FINDING_DETAIL.checks.length,
    );
  });

  /**
   * The real route builds `turns` from the staged probe's own `turns:` list,
   * which is the **user side of the hunt only** — "the target's replies are not
   * in the staged file at all". Both real findings therefore render as an
   * unbroken column of prompts, and a region called "the session" would read as
   * a transcript that failed to load. The page says whose words these are.
   */
  it("says the prompts are the hunt's, not the target's replies", async () => {
    server.use(
      http.get("/api/discoveries/:probeId", () =>
        HttpResponse.json({
          ...FINDING_DETAIL,
          turns: [
            { role: "user", text: "Which company exactly?", redacted: false },
            { role: "user", text: "And when was it funded?", redacted: false },
          ],
        }),
      ),
    );
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const panel = await screen.findByTestId("finding-panel");
    const said = panel.textContent?.toLowerCase() ?? "";
    expect(said).toContain("prompts");
    expect(
      said,
      "a column of prompts with no replies was presented as the session",
    ).toContain("not the target");

    /*
     * Scoped to the headings, because the whole panel's text is satisfied by
     * the explanatory paragraph alone — which leaves the region *label*, the
     * largest type in the region and the only part read from the back of a
     * room, free to become the exact word the wire fact forbids.
     */
    const headings = within(panel)
      .getAllByRole("heading")
      .map((h) => h.textContent?.toLowerCase() ?? "");
    expect(
      headings.some((h) => h.includes("prompt")),
      "no heading says these are prompts",
    ).toBe(true);
    expect(
      headings.filter((h) => /\bsessions?\b|\btranscripts?\b/.test(h)),
      "a prompts-only column was headed as a session or a transcript",
    ).toEqual([]);
  });

  /**
   * `checks` is flattened off the **replay**, so a finding whose replay was
   * skipped carries none — the ordinary case for the real safety-critical
   * finding. The probe still declares its checks; they are in the staged file.
   * Saying "the probe declares no checks" would be false about real data and
   * would send the operator looking for a bug instead of a budget.
   */
  it("blames the missing replay for missing checks, not the probe", async () => {
    server.use(
      http.get("/api/discoveries/:probeId", () =>
        HttpResponse.json({ ...FINDING_DETAIL, checks: [], replay: null }),
      ),
    );
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const panel = await screen.findByTestId("finding-panel");
    const said = panel.textContent?.toLowerCase() ?? "";
    expect(said).toContain("replay did not run");
    expect(
      said,
      "the probe was blamed for declaring no checks when it declares them in the staged file",
    ).not.toContain("declares no checks");
  });

  /**
   * The real `confirmation` provenance value is the engine's own account of why
   * the finding was confirmed, and on `discovered-hallucination-4a057400` it
   * runs past 200 characters. It is the one thing on the panel that explains the
   * verdict, so it is rendered whole — never clipped to a tidy cell.
   */
  it("renders a long provenance sentence in full rather than truncating it", async () => {
    const confirmation =
      "confirmed: required rubric:groundedness FAILED (medians={'Claim support': 1, " +
      "'Specificity without overreach': 1} samples=[{'Claim support': 1, " +
      "'Specificity without overreach': 1}, {'Claim support': 1, " +
      "'Specificity without overreach': 1}])";
    server.use(
      http.get("/api/discoveries/:probeId", () =>
        HttpResponse.json({
          ...FINDING_DETAIL,
          provenance: { ...FINDING_DETAIL.provenance, confirmation },
        }),
      ),
    );
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const panel = await screen.findByTestId("finding-panel");
    expect(panel.textContent).toContain(confirmation);

    /*
     * The half the name promises and `textContent` cannot deliver. Clipping is
     * CSS: it leaves the DOM text byte-identical, so the assertion above passes
     * unchanged over a cell clipped to one line with an ellipsis. The class
     * contract is what separates "in the DOM" from "on the screen".
     */
    const sentence = valueCell(panel, confirmation);
    expect(
      clippingOn(sentence),
      "the confirmation sentence was clipped to one line",
    ).toEqual([]);
    expect(
      sentence.className.split(/\s+/),
      "the sentence breaks mid-token instead of between words",
    ).toContain("break-words");

    /*
     * And the gutter it breaks into. Provenance is eight keys, one of which is
     * this sentence; at four columns it gets ~180px on a projector, which is a
     * column of shredded prose whether or not it is clipped.
     */
    const provenance = sentence.closest("dl");
    expect(provenance?.className).toContain("sm:grid-cols-2");
    expect(
      provenance?.className,
      "the long provenance sentence was put back into a narrow four-column gutter",
    ).not.toContain("lg:grid-cols-4");
  });

  it("renders the staged file's own bytes, so what is adopted is what is shown", async () => {
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const yaml = await screen.findByTestId("finding-yaml");
    expect(yaml.textContent).toBe(FINDING_DETAIL.probe_yaml);
  });

  it("states a detail that could not be read rather than opening an empty panel", async () => {
    server.use(
      http.get("/api/discoveries/:probeId", () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "no such finding" } },
          { status: 404 },
        ),
      ),
    );
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const failure = await screen.findByTestId("finding-error");
    expect(failure.textContent).toContain("no such finding");
  });

  it("closes the panel and returns focus to the row that opened it", async () => {
    renderDiscoveries();
    await settled();
    const key = within(rowFor(HALLUCINATION)).getByRole("button", {
      name: HALLUCINATION,
    });
    await userEvent.click(key);
    await screen.findByTestId("finding-panel");

    await userEvent.click(screen.getByRole("button", { name: /close/i }));

    await waitFor(() =>
      expect(screen.queryByTestId("finding-panel")).toBeNull(),
    );
    // A keyboard operator who closes a panel must not be dropped at the top of
    // the document with the list they were reading scrolled away.
    expect(key).toHaveFocus();
  });
});

/**
 * Redaction. The page is downstream of a chokepoint and must add nothing of its
 * own — this is where the divergence between the mock and the real redactor
 * would otherwise be baked into the UI.
 */
describe("redaction is reported, never interpreted", () => {
  it("never sends the reveal token", async () => {
    const headers: (string | null)[] = [];
    server.events.on("request:start", ({ request }) => {
      headers.push(request.headers.get("X-Evalyn-Reveal"));
    });

    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );
    await screen.findByTestId("finding-panel");

    expect(
      headers.filter((h) => h !== null),
      "the cockpit tried to reveal live data it has no token for",
    ).toEqual([]);
    server.events.removeAllListeners();
  });

  it("offers no control that would reveal a redacted value", async () => {
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );
    await screen.findByTestId("finding-panel");

    expect(screen.queryByRole("button", { name: /reveal|unmask|show raw/i })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  /**
   * The marker's *kind* is server vocabulary that the client must not model.
   * The fixtures render `«redacted:org»`, and no `org` kind exists anywhere in
   * the real redactor — `_classify` returns only `email`, `phone`, `path`,
   * `token` or `check_value`, and the walker adds `too_deep` and `error`. A page
   * that mapped kinds to friendly labels would ship a table that is wrong about
   * the server today and wrong again the day a kind is added, so the marker is
   * passed through as the bytes it arrived as.
   */
  it("prints the marker verbatim rather than translating its kind", async () => {
    /*
     * Served with the kinds the real redactor actually emits, not the fixture's.
     * `FINDING_DETAIL` renders `«redacted:org»` and **no `org` kind exists** —
     * `_classify` returns only `email`, `phone`, `path`, `token` or
     * `check_value`, and the walker adds `too_deep` and `error`. Asserting the
     * fixture's string would pin this test to a kind the server can never send,
     * so it asserts the property instead: whatever kind arrives, it survives.
     */
    server.use(
      http.get("/api/discoveries/:probeId", () =>
        HttpResponse.json({
          ...FINDING_DETAIL,
          probe_yaml:
            "checks:\n  - not_contains: '«redacted:email»'\n" +
            "  - not_contains: '«redacted:check_value»'\n",
        }),
      ),
    );
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const yaml = await screen.findByTestId("finding-yaml");
    expect(yaml.textContent).toContain("«redacted:email»");
    expect(yaml.textContent).toContain("«redacted:check_value»");
  });

  /**
   * The reveal path does not exist. `GET /api/discoveries/{probe_id}` takes
   * `probe_id` and nothing else — no `Request`, no `Header` — and redaction is
   * applied unconditionally by `RedactingRoute`. The MSW handler *does* honour
   * an `X-Evalyn-Reveal` header, so a reveal control would pass every test here
   * and do nothing at all against the real server, on a projector.
   *
   * So the state is stated, and the recovery points off-screen at the file.
   */
  it("says the redaction cannot be lifted here, rather than staying silent", async () => {
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );

    const said = (await screen.findByTestId("finding-no-reveal")).textContent ?? "";
    expect(said.toLowerCase()).toContain("cannot be revealed");
    expect(said).toContain("discover");
  });

  it("says nothing about revealing when nothing was redacted", async () => {
    server.use(
      http.get("/api/discoveries/:probeId", () =>
        HttpResponse.json({ ...FINDING_DETAIL, redacted: false }),
      ),
    );
    renderDiscoveries();
    await settled();
    await userEvent.click(
      within(rowFor(HALLUCINATION)).getByRole("button", { name: HALLUCINATION }),
    );
    await screen.findByTestId("finding-panel");

    expect(screen.queryByTestId("finding-no-reveal")).toBeNull();
  });

  it("takes the redacted chip off the flag, not off the text", async () => {
    withFindings([{ ...FINDING_ROWS[0]!, redacted: true }]);
    renderDiscoveries();
    await settled();

    // No marker anywhere in this row's text, and the chip must still appear:
    // the redactor can remove a whole clause and leave nothing to sniff.
    expect(rowFor(HALLUCINATION).textContent).not.toContain("«redacted");
    expect(
      within(rowFor(HALLUCINATION)).getByTestId("redacted-chip"),
    ).toBeTruthy();
  });
});

describe("a bench that cannot be read says so", () => {
  it("reports the refusal instead of rendering an empty bench", async () => {
    server.use(
      http.get("/api/discoveries", () =>
        HttpResponse.json(
          { error: { code: "invalid_cursor", message: "malformed cursor" } },
          { status: 400 },
        ),
      ),
    );
    renderDiscoveries();

    const failure = await screen.findByTestId("discoveries-error");
    expect(failure.textContent).toContain("malformed cursor");
    // "Nothing was found" and "nothing could be read" are different facts.
    expect(screen.queryByTestId("discoveries-empty")).toBeNull();
  });
});
