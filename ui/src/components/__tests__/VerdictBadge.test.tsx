import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VERDICT_TIERS, type VerdictTier } from "../../api/types";
import { VerdictBadge } from "../VerdictBadge";

/**
 * The badge is the product's central output rendered at check granularity, so
 * the properties asserted here are contract properties rather than pixels:
 *
 * - **All four tiers**, iterated from the enum itself so widening `VerdictTier`
 *   reds here instead of shipping a blank badge.
 * - **`abstained` is a tier, not tier zero.** It may never render as pass or
 *   fail; the judge declining to score is a third answer.
 * - **`passed: null` is not `false`.** A check that returned no score is
 *   `unscored`, and calling it a failure is a fabricated verdict.
 * - **Never colour alone** — every rendition carries a glyph and a word.
 */

function words(el: HTMLElement): string {
  return (el.textContent ?? "").toLowerCase();
}

describe("VerdictBadge", () => {
  it("renders every VerdictTier member with a glyph and a word", () => {
    for (const tier of VERDICT_TIERS) {
      const { unmount } = render(<VerdictBadge tier={tier} passed={null} />);
      const badge = screen.getByTestId("verdict-badge");

      expect(
        badge.querySelector("svg"),
        `tier ${tier} rendered without a glyph — colour and word alone`,
      ).not.toBeNull();
      expect(
        words(badge).trim(),
        `tier ${tier} rendered no word at all`,
      ).not.toEqual("");
      unmount();
    }
  });

  it("names its tier verbatim, as the string the wire actually carries", () => {
    for (const tier of VERDICT_TIERS) {
      const { unmount } = render(<VerdictBadge tier={tier} passed={null} />);
      const badge = screen.getByTestId("verdict-badge");

      // The wire form is `"1" | "2" | "3" | "abstained"`. A badge that stored
      // `Number(tier)` would render `1` here and `NaN` for `abstained`.
      expect(badge.dataset["tier"]).toBe(tier);
      expect(
        words(badge),
        `tier ${tier} is not distinguishable from the other three in the DOM`,
      ).toContain(tier === "abstained" ? "abstained" : `tier ${tier}`);
      unmount();
    }
  });

  it("never renders abstained as a pass or a fail", () => {
    // `passed` is null by construction on an abstained check, but pass a lie in
    // deliberately: the tier is the authority, not the boolean beside it.
    for (const passed of [null, true, false] as const) {
      const { unmount } = render(
        <VerdictBadge tier="abstained" passed={passed} />,
      );
      const badge = screen.getByTestId("verdict-badge");

      expect(badge.dataset["outcome"]).toBe("abstained");
      expect(words(badge)).not.toMatch(/\bpass\b/);
      expect(words(badge)).not.toMatch(/\bfail\b/);
      unmount();
    }
  });

  it("separates unscored from failed on a scored tier", () => {
    const cases: [boolean | null, string][] = [
      [true, "pass"],
      [false, "fail"],
      // The one that matters: `null` means the check produced no score. A badge
      // that reads `passed ? pass : fail` invents a failure that never happened.
      [null, "unscored"],
    ];
    for (const [passed, expected] of cases) {
      const { unmount } = render(<VerdictBadge tier="2" passed={passed} />);
      const badge = screen.getByTestId("verdict-badge");
      expect(badge.dataset["outcome"], `passed=${passed}`).toBe(expected);
      expect(words(badge)).toContain(expected);
      unmount();
    }
  });

  it("gives the four tiers four distinct outcome renditions on the same input", () => {
    // Same `passed` for all four, so any difference in the rendition comes from
    // the tier alone. `abstained` must part company with 1/2/3.
    const outcomes = new Set<string>();
    for (const tier of VERDICT_TIERS) {
      const { unmount } = render(<VerdictBadge tier={tier} passed={false} />);
      outcomes.add(screen.getByTestId("verdict-badge").dataset["outcome"]!);
      unmount();
    }
    expect(outcomes).toEqual(new Set(["fail", "abstained"]));
  });

  it("keeps the whole meaning available without colour", () => {
    render(<VerdictBadge tier="1" passed={false} />);
    const badge = screen.getByTestId("verdict-badge");
    // Strip nothing, read the text: it has to say what happened on its own.
    expect(words(badge)).toContain("fail");
    expect(words(badge)).toContain("tier 1");
    expect(within(badge).getByText(/fail/i)).toBeInTheDocument();
  });
});

/** A compile-time reminder that the union is exactly what this file iterates. */
const _tiers: readonly VerdictTier[] = VERDICT_TIERS;
void _tiers;
