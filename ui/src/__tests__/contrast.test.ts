import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import tailwindConfig from "../../tailwind.config";

/**
 * The contrast guard.
 *
 * WCAG 2.1 AA is a committed standard for this product, and the palette's own
 * documentation states which steps may carry text. Neither fact stopped the
 * same defect shipping **three times**: `chassis-500` on the verdict prefix,
 * then `status-unreadable` at 4.34:1 and `chassis-500` at 3.82:1 in the legend
 * strip — the last two in a file the commit that fixed the first one touched.
 * A rule written in a comment is not a rule.
 *
 * So this file does two things, and the second is the one that matters:
 *
 * 1. **Measures the palette.** Every number the config claims is recomputed
 *    from the hex values. If someone re-hues a step, the claim moves with it.
 * 2. **Inventories every ink/ground pairing on the surface.** `INK_USAGE` below
 *    is the complete, reviewed list of which colour tokens each component puts
 *    on which ground. The test asserts the inventory is *exhaustive* — a
 *    component using a token nobody declared fails — and then asserts each
 *    declared pairing against the threshold for its role.
 *
 * The exhaustiveness half is the point. Tasks 9, 15, 16, 17 and 21 cannot add a
 * colour to a page without coming here and stating, in one line, what ground it
 * sits on and whether it is text. That is a thirty-second cost that catches the
 * failure this project has now made three times.
 */

// ---------------------------------------------------------------------------
// WCAG 2.1 relative luminance
// ---------------------------------------------------------------------------

function channel(value: number): number {
  const s = value / 255;
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  return (
    0.2126 * channel((n >> 16) & 255) +
    0.7152 * channel((n >> 8) & 255) +
    0.0722 * channel(n & 255)
  );
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [
    number,
    number,
  ];
  return (hi + 0.05) / (lo + 0.05);
}

// ---------------------------------------------------------------------------
// The palette, read from the config rather than copied out of it
// ---------------------------------------------------------------------------

const colors = tailwindConfig.theme!.extend!.colors as Record<
  string,
  string | Record<string, string>
>;

/** `"chassis-600"` / `"status-passed"` / `"degraded"` -> its hex. */
function hexFor(token: string): string {
  const direct = colors[token];
  if (typeof direct === "string") return direct;

  const at = token.lastIndexOf("-");
  const family = colors[token.slice(0, at)];
  const step = token.slice(at + 1);
  if (family && typeof family === "object" && typeof family[step] === "string") {
    return family[step];
  }
  throw new Error(`no such colour token: ${token}`);
}

const AA_TEXT = 4.5;
/** WCAG 1.4.11: a graphical object needed to understand the content. */
const AA_NON_TEXT = 3;

// ---------------------------------------------------------------------------
// The inventory
// ---------------------------------------------------------------------------

type Role =
  /** Text a human reads. 4.5:1. */
  | "text"
  /** A mark that carries meaning without an adjacent word. 3:1. */
  | "graphic"
  /**
   * Redundant reinforcement: an `aria-hidden` separator, or a stroke sitting
   * beside a word that already says the same thing. No threshold, because
   * removing it removes no information — but it must be genuinely redundant,
   * which is why each one carries a note.
   */
  | "redundant"
  /**
   * The label of a disabled control. WCAG 1.4.3 exempts inactive user
   * interface components by name, and the whole point of the treatment is to
   * read as unavailable. Still declared, so the exemption is a decision on the
   * record rather than an oversight that happens to be legal.
   */
  | "disabled";

interface Usage {
  ink: string;
  ground: string;
  role: Role;
  note?: string;
}

/**
 * Every `text-*` token each component uses, and the ground it sits on.
 *
 * "Ground" is the darkest surface that token is actually rendered against —
 * the strip is `chassis-50`, the banner `chassis-100`, table rows `chassis-25`.
 */
const INK_USAGE: Record<string, Usage[]> = {
  "components/AppShell.tsx": [
    { ink: "chassis-900", ground: "chassis-50", role: "text" },
    { ink: "chassis-600", ground: "chassis-50", role: "text" },
    {
      ink: "chassis-400",
      ground: "chassis-50",
      role: "redundant",
      note: "the aria-hidden '·' separating version from runs_dir",
    },
  ],
  "components/RedactionBanner.tsx": [
    { ink: "chassis-800", ground: "chassis-100", role: "text" },
    { ink: "chassis-900", ground: "chassis-100", role: "text" },
    { ink: "chassis-600", ground: "chassis-100", role: "graphic", note: "the lock mark" },
    {
      ink: "chassis-400",
      ground: "chassis-100",
      role: "redundant",
      note: "aria-hidden '·' separators",
    },
  ],
  "components/RunStatusChip.tsx": [
    { ink: "status-passed", ground: "chassis-25", role: "text" },
    { ink: "status-gate_failed", ground: "chassis-25", role: "text" },
    { ink: "status-invalid", ground: "chassis-25", role: "text" },
    { ink: "status-running", ground: "chassis-25", role: "text" },
    { ink: "status-paused", ground: "chassis-25", role: "text" },
    { ink: "status-cancelled", ground: "chassis-25", role: "text" },
    { ink: "status-interrupted", ground: "chassis-25", role: "text" },
    { ink: "status-failed_to_start", ground: "chassis-25", role: "text" },
    { ink: "status-unreadable", ground: "chassis-25", role: "text" },
    {
      ink: "chassis-600",
      ground: "chassis-25",
      role: "text",
      note: "the `unverified` rendition on a degraded row",
    },
  ],
  "components/RunsTable.tsx": [
    { ink: "status-passed", ground: "chassis-25", role: "text" },
    { ink: "status-gate_failed", ground: "chassis-25", role: "text" },
    { ink: "chassis-900", ground: "chassis-25", role: "text" },
    { ink: "chassis-700", ground: "chassis-25", role: "text" },
    { ink: "chassis-600", ground: "chassis-50", role: "text" },
  ],
  "components/DegradedRow.tsx": [
    { ink: "chassis-900", ground: "chassis-25", role: "text" },
    { ink: "chassis-700", ground: "chassis-25", role: "text" },
    { ink: "chassis-600", ground: "chassis-25", role: "text" },
    {
      ink: "chassis-500",
      ground: "chassis-25",
      role: "redundant",
      note: "the flat-line stroke immediately left of the word DEGRADED",
    },
  ],
  "components/Flatline.tsx": [
    { ink: "chassis-500", ground: "chassis-25", role: "graphic" },
    { ink: "chassis-600", ground: "chassis-25", role: "text" },
  ],
  "pages/RunsPage.tsx": [
    { ink: "chassis-900", ground: "chassis-25", role: "text" },
    { ink: "chassis-600", ground: "chassis-25", role: "text" },
    {
      ink: "chassis-500",
      ground: "chassis-25",
      role: "disabled",
      note: "the `Load older runs` key while a page is in flight",
    },
    { ink: "status-unreadable", ground: "chassis-25", role: "text" },
    {
      ink: "chassis-400",
      ground: "chassis-25",
      role: "redundant",
      note: "aria-hidden '·' separator",
    },
  ],
  "pages/RunDetailPage.tsx": [
    { ink: "chassis-900", ground: "chassis-25", role: "text" },
    { ink: "chassis-700", ground: "chassis-25", role: "text" },
    { ink: "chassis-600", ground: "chassis-25", role: "text" },
    { ink: "status-unreadable", ground: "chassis-25", role: "text" },
    {
      ink: "chassis-500",
      ground: "chassis-25",
      role: "redundant",
      note: "the flat-line stroke beside the word DEGRADED",
    },
  ],
  "routes.tsx": [
    { ink: "chassis-900", ground: "chassis-25", role: "text" },
    { ink: "chassis-600", ground: "chassis-25", role: "text" },
  ],
};

const SRC = resolve(import.meta.dirname, "..");

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string, prefix: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "__tests__" || entry.name === "mocks" || entry.name === "test") {
        continue;
      }
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) walk(join(dir, entry.name), rel);
      else if (entry.name.endsWith(".tsx")) out.push(rel);
    }
  };
  walk(SRC, "");
  return out.sort();
}

/**
 * Every `text-<token>` class written in a file, colour tokens only.
 *
 * Comments are stripped first. Without that, a docstring *explaining* why a
 * token was removed counts as using it — which is exactly what happened on the
 * first run of this test, and is the same false-positive class that makes
 * Tailwind emit `.rounded` because the word appears in an anti-pastiche note.
 */
function inksUsedIn(file: string): Set<string> {
  const source = readFileSync(join(SRC, file), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
  const found = new Set<string>();
  const pattern = /\btext-((?:chassis|status)-[a-z0-9_]+|degraded)\b/g;
  for (const match of source.matchAll(pattern)) found.add(match[1]!);
  return found;
}

describe("the palette measures what the config says it measures", () => {
  it("keeps every status colour above AA on the one ground status ink may use", () => {
    const ground = hexFor("chassis-25");
    const statuses = colors["status"] as Record<string, string>;
    for (const [member, hex] of Object.entries(statuses)) {
      expect(
        contrast(hex, ground),
        `status-${member} on chassis-25`,
      ).toBeGreaterThanOrEqual(AA_TEXT);
    }
  });

  it("keeps chassis-600 and darker usable as text on every ground that carries text", () => {
    for (const ground of ["chassis-25", "chassis-50", "chassis-100"]) {
      for (const ink of ["chassis-600", "chassis-700", "chassis-800", "chassis-900"]) {
        expect(
          contrast(hexFor(ink), hexFor(ground)),
          `${ink} on ${ground}`,
        ).toBeGreaterThanOrEqual(AA_TEXT);
      }
    }
  });

  /**
   * The config prohibits these two as body text. That prohibition is only
   * meaningful while it is *true* — if a later task re-hues them to pass, the
   * comment saying "not a body-text colour" becomes a lie, and this reds so
   * whoever changed the hex updates the rule too.
   */
  it("holds the prohibition on chassis-400 and chassis-500 as text", () => {
    for (const ink of ["chassis-400", "chassis-500"]) {
      expect(
        contrast(hexFor(ink), hexFor("chassis-25")),
        `${ink} is documented as too light for text`,
      ).toBeLessThan(AA_TEXT);
    }
    // ...but chassis-500 must stay usable as a graphical mark, which is the job
    // the Flatline trace depends on.
    expect(
      contrast(hexFor("chassis-500"), hexFor("chassis-25")),
    ).toBeGreaterThanOrEqual(AA_NON_TEXT);
  });
});

describe("every ink on the surface is declared and compliant", () => {
  it("has an inventory entry for every component that renders ink", () => {
    const undeclared = sourceFiles().filter(
      (file) => inksUsedIn(file).size > 0 && INK_USAGE[file] === undefined,
    );
    expect(
      undeclared,
      "these files use colour tokens but are absent from INK_USAGE",
    ).toEqual([]);
  });

  it("declares every ink each component actually uses, and no ink it does not", () => {
    for (const [file, usages] of Object.entries(INK_USAGE)) {
      const used = [...inksUsedIn(file)].sort();
      const declared = [...new Set(usages.map((u) => u.ink))].sort();
      expect(used, `${file}: INK_USAGE is out of date`).toEqual(declared);
    }
  });

  it("meets the threshold for every declared pairing's role", () => {
    for (const [file, usages] of Object.entries(INK_USAGE)) {
      for (const usage of usages) {
        const ratio = contrast(hexFor(usage.ink), hexFor(usage.ground));
        const where = `${file}: ${usage.ink} on ${usage.ground} (${usage.role})`;
        if (usage.role === "text") {
          expect(ratio, where).toBeGreaterThanOrEqual(AA_TEXT);
        } else if (usage.role === "graphic") {
          expect(ratio, where).toBeGreaterThanOrEqual(AA_NON_TEXT);
        } else {
          // `redundant` and `disabled` carry no ratio, but they must carry a
          // note saying why — an unexplained exemption is just a contrast
          // failure with a label on it.
          expect(usage.note, `${where} must justify itself`).toBeTruthy();
        }
      }
    }
  });
});
