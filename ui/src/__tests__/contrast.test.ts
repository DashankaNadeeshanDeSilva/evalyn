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
 * 2. **Inventories every ink/ground pairing on the surface.** `SURFACES` below
 *    is the complete, reviewed list of which colour tokens each component puts
 *    on which ground. The test asserts the inventory is *exhaustive* — a
 *    component using a token nobody declared fails — and then asserts each
 *    declared pairing against the threshold for its role.
 *
 * ## What this guard enforces, exactly — and what it does not
 *
 * It reasons **per file**. For each source file it reads the `text-*` and `bg-*`
 * tokens that file contains, holds them against the inventory, and measures
 * every ink the file uses against every ground that **same file** establishes.
 * So within a file, an undeclared ink fails, an undeclared ground fails, and no
 * ink can be exempted from a ground its own file sets.
 *
 * **It does not see composition across files.** `inherits` is hand-written, and
 * no file's grounds are ever applied to the components it renders. Verified by
 * probe: a new page whose own ground is `chassis-900`, rendering
 * `<RunStatusChip>`, passes the whole suite — the chip declares
 * `inherits: "chassis-25"`,
 * nothing re-checks it against the dark ground it was actually dropped onto, and
 * `status-passed` on `chassis-900` measures 3.38:1. Near-black on near-black,
 * certified. That gap is parked deliberately (ruling R4-24): closing it means
 * either host declarations in `SURFACES` or rendering-based measurement, and
 * that is a design decision with real cost.
 *
 * **So Task 21 must verify its inherited inks by hand.** Its live view is built
 * on the `inset` family — the one dark ground on the surface, where every
 * light-ground rule inverts — and any component it renders inside that ground
 * was written against `chassis-25` and is still measured against `chassis-25`
 * here. This file will not catch it.
 *
 * What the guard *is* worth: the failure it was built for is a component
 * quietly using an ink nobody measured, and that class it does catch, in every
 * `.ts` and `.tsx` under `src/`.
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

/**
 * Composite a translucent ground over what is behind it.
 *
 * `bg-degraded/[0.08]` is not the `degraded` grey — it is 8% of it over the
 * face, which lands at `#f3f4f5`. Treating the modifier as opaque would have
 * this guard reject `chassis-700` on a degraded row at a measured 3.57:1 when
 * the real pairing is 8.36:1. Wrong in the safe direction is still wrong: it
 * teaches the next author that the guard cries wolf.
 */
function over(top: string, bottom: string, alpha: number): string {
  const mix = (shift: number) => {
    const t = (parseInt(top.slice(1), 16) >> shift) & 255;
    const b = (parseInt(bottom.slice(1), 16) >> shift) & 255;
    return Math.round(t * alpha + b * (1 - alpha));
  };
  const hex = (v: number) => v.toString(16).padStart(2, "0");
  return `#${hex(mix(16))}${hex(mix(8))}${hex(mix(0))}`;
}

/** `"chassis-600"` / `"status-passed"` / `"inset"` / `"degraded"` -> its hex. */
function hexFor(token: string): string {
  const direct = colors[token];
  if (typeof direct === "string") return direct;
  // The bare family name is what Tailwind emits for `inset.DEFAULT`, and a
  // background written that way is exactly what Task 21 will write. Without
  // this line it threw "no such colour token: inset" — fail-closed, so safe,
  // but Task 21 met a crash where it should have met a contrast number.
  //
  // (The class itself is deliberately not spelled out anywhere in this file:
  // Tailwind scans `src/**/*.{ts,tsx}` and does not strip comments, so naming
  // an unused utility here emits dead CSS into the shipped bundle. Measured —
  // an earlier draft of this comment added two rules to the wheel.)
  if (direct && typeof direct["DEFAULT"] === "string") return direct["DEFAULT"];

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

interface Ink {
  ink: string;
  role: Role;
  note?: string;
}

interface Surface {
  /**
   * The ground this file does not set itself — the shell's face, usually.
   * Declared because a component cannot see what it will be rendered inside.
   */
  inherits: string;
  /**
   * Every `bg-*` colour token this file sets, in any variant (`hover:`, `sm:`,
   * with an opacity modifier). Asserted equal to what the source actually
   * contains, so a new background cannot enter without being declared.
   */
  sets: string[];
  inks: Ink[];
}

/**
 * Every colour token each component uses, and every ground it can sit on.
 *
 * The `ground` field used to be a single hand-written value. That is precisely
 * how the guard came to stamp AA-compliant on a failing pairing: a row was
 * `hover:bg-chassis-50`, nothing read `bg-*`, and the inventory said
 * `chassis-25` because a human wrote `chassis-25`.
 *
 * **Within a file there is deliberately no way to narrow an ink to a subset of
 * that file's grounds.** A first attempt at this guard offered exactly that
 * escape hatch, with a `note` required to use it — and it reproduced the
 * original bug on the first probe, because the note said "the header row
 * carries no status ink" and a `hover:` fill on a *data* row is invisible at
 * file granularity. So the rule is unconditional inside the file: every ink is
 * checked against every ground its file establishes. When that is too strict,
 * the answer is to change the code — drop the second ground, or split the
 * component so each file has one — and both of those made the design better
 * here.
 *
 * **The file boundary is itself a narrowing, though, and this is the guard's
 * real limit.** `inherits` states the ground a component expects to be rendered
 * inside; nothing verifies it against the ground the rendering page actually
 * establishes. An ink is never measured against a ground some *other* file puts
 * behind it. See the module docstring and ruling R4-24.
 */
const SURFACES: Record<string, Surface> = {
  "components/AppShell.tsx": {
    inherits: "chassis-25",
    sets: ["chassis-100", "chassis-50", "chassis-25"],
    inks: [
      { ink: "chassis-900", role: "text" },
      { ink: "chassis-600", role: "text" },
      {
        ink: "chassis-400",
        role: "redundant",
        note: "the aria-hidden '·' separating version from runs_dir",
      },
    ],
  },
  "components/RedactionBanner.tsx": {
    inherits: "chassis-25",
    sets: ["chassis-100", "chassis-200"],
    inks: [
      { ink: "chassis-800", role: "text" },
      { ink: "chassis-900", role: "text" },
      { ink: "chassis-600", role: "graphic", note: "the lock mark" },
      {
        ink: "chassis-400",
        role: "redundant",
        note: "aria-hidden '·' separators",
      },
    ],
  },
  "components/RunStatusChip.tsx": {
    inherits: "chassis-25",
    sets: [],
    inks: [
      { ink: "status-passed", role: "text" },
      { ink: "status-gate_failed", role: "text" },
      { ink: "status-invalid", role: "text" },
      { ink: "status-running", role: "text" },
      { ink: "status-paused", role: "text" },
      { ink: "status-cancelled", role: "text" },
      { ink: "status-interrupted", role: "text" },
      { ink: "status-failed_to_start", role: "text" },
      { ink: "status-unreadable", role: "text" },
      {
        ink: "chassis-600",
        role: "text",
        note: "the `unverified` rendition on a degraded row",
      },
    ],
  },
  "components/RunsTable.tsx": {
    inherits: "chassis-25",
    // No tinted grounds at all: the header row is divided by its rule, and row
    // hover deepens that rule rather than filling the row. One ground means
    // every ink here is measured against the one surface it can sit on.
    sets: [],
    inks: [
      { ink: "status-passed", role: "text" },
      { ink: "status-gate_failed", role: "text" },
      { ink: "chassis-900", role: "text" },
      { ink: "chassis-700", role: "text" },
      { ink: "chassis-600", role: "text" },
    ],
  },
  "components/DegradedRow.tsx": {
    inherits: "chassis-25",
    // The dead-channel wash: 8% of the degraded grey over the face, which is
    // the ground every ink in this row actually sits on.
    sets: ["degraded/0.08"],
    inks: [
      { ink: "chassis-900", role: "text" },
      { ink: "chassis-700", role: "text" },
      { ink: "chassis-600", role: "text" },
      {
        ink: "chassis-500",
        role: "redundant",
        note: "the flat-line stroke immediately left of the word DEGRADED",
      },
    ],
  },
  "components/Flatline.tsx": {
    inherits: "chassis-25",
    sets: [],
    inks: [
      { ink: "chassis-500", role: "graphic" },
      { ink: "chassis-600", role: "text" },
    ],
  },
  "components/InstrumentIcon.tsx": { inherits: "chassis-25", sets: [], inks: [] },
  "pages/RunsPage.tsx": {
    inherits: "chassis-25",
    // chassis-100 is the load-more key's hover fill; chassis-50/60 is the
    // loading skeleton's bar, which carries no text at all.
    sets: ["chassis-100", "chassis-50/0.6"],
    inks: [
      { ink: "chassis-900", role: "text" },
      { ink: "chassis-600", role: "text" },
      {
        ink: "chassis-500",
        role: "disabled",
        note: "the `Load older runs` key while a page is in flight",
      },
      {
        ink: "chassis-400",
        role: "redundant",
        note: "aria-hidden '·' separator",
      },
    ],
  },
  "pages/RunDetailPage.tsx": {
    inherits: "chassis-25",
    sets: [],
    inks: [
      { ink: "chassis-900", role: "text" },
      { ink: "chassis-700", role: "text" },
      { ink: "chassis-600", role: "text" },
      {
        ink: "chassis-500",
        role: "redundant",
        note: "the flat-line stroke beside the word DEGRADED",
      },
    ],
  },
  "routes.tsx": {
    inherits: "chassis-25",
    sets: [],
    inks: [
      { ink: "chassis-900", role: "text" },
      { ink: "chassis-600", role: "text" },
    ],
  },
};

const SRC = resolve(import.meta.dirname, "..");

/**
 * Every colour family the palette defines. Kept in sync with the config by
 * derivation, not by hand — a family added to `tailwind.config.ts` widens the
 * scanner automatically, which is what stops the reserved `inset` and `safety`
 * families (Task 21's live view, and the one dark ground on the surface) from
 * being invisible to this guard.
 */
const FAMILIES = Object.keys(colors).sort();
const TOKEN = `(?:${FAMILIES.join("|")})(?:-[a-z0-9_]+)?`;

/**
 * Source files that can carry a class name.
 *
 * `.ts` as well as `.tsx`: Tailwind's own content glob is `./src/**‍/*.{ts,tsx}`
 * and this codebase's established pattern for ink is a constant map in a `.ts`
 * module. Scanning only `.tsx` let a whole file's palette escape the guard.
 */
function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string, prefix: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "__tests__" || entry.name === "mocks" || entry.name === "test") {
        continue;
      }
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) walk(join(dir, entry.name), rel);
      else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts")) {
        out.push(rel);
      }
    }
  };
  walk(SRC, "");
  return out.sort();
}

/**
 * A file's source with comments stripped.
 *
 * Without this, a docstring *explaining* why a token was removed counts as
 * using it — which is what happened on this guard's first run, and is the same
 * false-positive class that makes Tailwind emit `.rounded` because the word
 * appears in an anti-pastiche note.
 */
function code(file: string): string {
  return readFileSync(join(SRC, file), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
}

function tokensAfter(file: string, prefix: "text" | "bg"): Set<string> {
  const found = new Set<string>();
  // A background may carry an opacity modifier — `bg-degraded/[0.08]` or
  // `bg-chassis-50/60` — and the modifier changes the ground materially, so it
  // is part of the token rather than noise to strip.
  // No trailing \b when an alpha may follow: the modifier ends in `]`, which
  // is not a word character, so a word boundary there never matches.
  const alpha = prefix === "bg" ? `(?:\\/(?:\\[([0-9.]+)\\]|(\\d+)))?` : "\\b";
  const pattern = new RegExp(`\\b${prefix}-(${TOKEN})${alpha}`, "g");
  for (const match of code(file).matchAll(pattern)) {
    const fraction = match[2] ?? (match[3] ? Number(match[3]) / 100 : undefined);
    found.add(fraction === undefined ? match[1]! : `${match[1]}/${fraction}`);
  }
  return found;
}

/** A declared ground -> the hex a human actually sees, backdrop composited in. */
function groundHex(ground: string, behind: string): string {
  const at = ground.indexOf("/");
  if (at === -1) return hexFor(ground);
  return over(
    hexFor(ground.slice(0, at)),
    hexFor(behind),
    Number(ground.slice(at + 1)),
  );
}

/** `text-[#999]` / `bg-[rgb(...)]` — a colour outside the palette entirely. */
function arbitraryColours(file: string): string[] {
  return [...code(file).matchAll(/\b(?:text|bg|border)-\[\s*(#|rgb|hsl|color)/g)].map(
    (m) => m[0],
  );
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

  /**
   * Reserved for Task 21's live view — the single dark field on the surface,
   * where every light-ground rule inverts. Checked now so the reservation is a
   * measured promise rather than a hex nobody has ever evaluated.
   */
  it("keeps the reserved inset and safety pairings usable before Task 21 needs them", () => {
    expect(
      contrast(hexFor("inset-ink"), hexFor("inset-DEFAULT")),
      "inset-ink on the inset window",
    ).toBeGreaterThanOrEqual(AA_TEXT);
    // The same window named the way Task 21 will name it — the bare family,
    // which is what a `DEFAULT` key renders as. Without the fallback in
    // `hexFor` this throws instead of measuring.
    expect(
      contrast(hexFor("inset-ink"), hexFor("inset")),
      "inset-ink on the bare `inset` token, which is inset.DEFAULT",
    ).toBeGreaterThanOrEqual(AA_TEXT);
    expect(
      contrast(hexFor("safety-ink"), hexFor("safety-DEFAULT")),
      "near-black ink on safety orange — white-on-orange typically fails AA",
    ).toBeGreaterThanOrEqual(AA_TEXT);
  });
});

describe("every ink on the surface is declared and compliant", () => {
  it("has an inventory entry for every source file that names a palette token", () => {
    const undeclared = sourceFiles().filter(
      (file) =>
        (tokensAfter(file, "text").size > 0 || tokensAfter(file, "bg").size > 0) &&
        SURFACES[file] === undefined,
    );
    expect(
      undeclared,
      "these files use palette tokens but are absent from SURFACES",
    ).toEqual([]);
  });

  it("declares every ink each component uses, and no ink it does not", () => {
    for (const [file, surface] of Object.entries(SURFACES)) {
      const used = [...tokensAfter(file, "text")].sort();
      const declared = [...new Set(surface.inks.map((i) => i.ink))].sort();
      expect(used, `${file}: SURFACES.inks is out of date`).toEqual(declared);
    }
  });

  /**
   * The half that stops the hand-assertion going stale: `sets` is checked
   * against the `bg-*` tokens actually present, so a new background — including
   * one behind a `hover:` variant — cannot enter without being declared, and
   * once declared it is automatically checked against every ink in the file.
   */
  it("declares every ground each component sets, and no ground it does not", () => {
    for (const [file, surface] of Object.entries(SURFACES)) {
      const used = [...tokensAfter(file, "bg")].sort();
      const declared = [...new Set(surface.sets)].sort();
      expect(used, `${file}: SURFACES.sets is out of date`).toEqual(declared);
    }
  });

  it("uses no colour from outside the palette", () => {
    for (const file of sourceFiles()) {
      expect(
        arbitraryColours(file),
        `${file} sets a colour the palette does not define, so nothing can measure it`,
      ).toEqual([]);
    }
  });

  it("meets the threshold on every ground the component can actually render on", () => {
    for (const [file, surface] of Object.entries(SURFACES)) {
      const grounds = [surface.inherits, ...surface.sets];
      for (const ink of surface.inks) {
        for (const ground of grounds) {
          const ratio = contrast(
            hexFor(ink.ink),
            groundHex(ground, surface.inherits),
          );
          const where = `${file}: ${ink.ink} on ${ground} (${ink.role})`;
          if (ink.role === "text") {
            expect(ratio, where).toBeGreaterThanOrEqual(AA_TEXT);
          } else if (ink.role === "graphic") {
            expect(ratio, where).toBeGreaterThanOrEqual(AA_NON_TEXT);
          } else {
            // `redundant` and `disabled` carry no ratio, but they must carry a
            // note saying why — an unexplained exemption is just a contrast
            // failure with a label on it.
            expect(ink.note, `${where} must justify itself`).toBeTruthy();
          }
        }
      }
    }
  });
});
