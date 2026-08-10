import { describe, expect, it } from "vitest";

import { formatUsd, formatUtc } from "../format";

/**
 * `format.ts` had no test, and one of the two functions encodes a product
 * decision rather than a formatting preference.
 *
 * The reviewer flipped `formatUsd` from four decimals to two and the entire
 * suite stayed green — while the rendered cost of a real `$0.0042` run became
 * `$0.00`. The docstring calls that "a lie the interface must not tell", and
 * the task report then explicitly invites the maintainer to reconsider the
 * precision, which makes an unguarded blast radius worse rather than better.
 *
 * So the assertion below is written against the **property**, not the format:
 * whatever precision a future maintainer picks, a spend that happened must
 * never render as a spend that did not. Someone lowering the precision has to
 * confront that sentence, which is exactly the conversation worth forcing.
 */
describe("formatUsd", () => {
  it("never renders a real spend as zero", () => {
    // Real values from the corpus and from a sub-cent discover run.
    for (const spent of [0.0001, 0.0042, 0.01377, 0.0421, 0.1234]) {
      const rendered = formatUsd(spent);
      const parsed = Number(rendered.replace("$", ""));
      expect(
        parsed,
        `${spent} rendered as ${rendered}, which reads as free`,
      ).toBeGreaterThan(0);
    }
  });

  it("renders judge spend to a fixed width so the column cannot jitter", () => {
    // A fixed decimal count is the other half of `tabular-nums`: same glyph
    // width AND same glyph count, or the column still moves.
    const widths = new Set(
      [0.0001, 0.0042, 0.01377, 0.1234, 0.5].map(
        (v) => formatUsd(v).split(".")[1]!.length,
      ),
    );
    expect(widths.size, "decimal places must not vary between rows").toBe(1);
  });

  it("keeps the dollar mark and does not round a value away", () => {
    expect(formatUsd(0.0042)).toBe("$0.0042");
    expect(formatUsd(0)).toBe("$0.0000");
  });
});

describe("formatUtc", () => {
  it("renders the artifact's own UTC stamp, seconds precision, locale-free", () => {
    // Sub-second precision is real but belongs in the run_id, not a scan column.
    expect(formatUtc("2026-08-04T08:15:44.953115+00:00")).toBe(
      "2026-08-04 08:15:44Z",
    );
  });

  it("returns an unparseable stamp verbatim rather than 'Invalid Date'", () => {
    // On a degraded artifact `created_at` was recovered from the filename.
    // Showing what was actually recovered beats showing a JavaScript error.
    expect(formatUtc("not-a-date")).toBe("not-a-date");
    expect(formatUtc("")).toBe("");
  });
});
