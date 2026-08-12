import tailwindConfig from "../tailwind.config";

/**
 * The chart's ink, **derived** from the palette rather than copied out of it.
 *
 * A chart paints with SVG `stroke`/`fill` attributes, not with Tailwind
 * classes, so two of this project's safety nets go blind here at once:
 *
 * - **Tailwind never sees these values**, which is why they must come off the
 *   config object instead of being written out as hex literals that drift the
 *   day someone re-hues a step.
 * - **`__tests__/contrast.test.ts` never sees them either.** That guard reads
 *   `text-*` and `bg-*` tokens out of the source text; a `stroke={…}` is
 *   invisible to it. So the ratios below are **measured by hand** with the same
 *   WCAG 2.1 formula the guard uses, against the one ground these marks sit on
 *   (`chassis-25`, `#fafbfc`, the instrument face), and recorded here:
 *
 *       focal    chassis-900         16.37   the selected probe's line and dots
 *       context  chassis-500          4.03   every other probe's line
 *       failed   status-gate_failed   6.24   a reading that did not reach the pass line
 *       pass     chassis-700          8.70   the pass line, the one rule that is not data
 *       axis     chassis-400          2.30   the axis rules and tick marks
 *       grid     chassis-200          1.27   the gridlines
 *       tick     chassis-600          5.98   the tick LABELS, which are text
 *
 * Two of those are deliberately below 3:1 and neither carries information.
 * `grid` is a gridline: removing it removes nothing, because every tick it
 * aligns to is labelled in `tick`, which is real text at AA. `axis` is the same
 * hairline weight the surface uses for a major panel division, and the axis it
 * draws is identified by those same labels.
 *
 * `context` at 4.03 is the interesting one. Each faint line IS data, so it is
 * held to the 3:1 graphical threshold rather than exempted — and it clears it.
 * It stays subordinate to the focal line by **weight** (1px against 2.5px) and
 * by a 4x contrast gap, not by being too pale to see.
 *
 * `pass` is the newest and the one with a story. The pass line was drawn in
 * `context` — the same bytes as every data line — and at `pass^k` the threshold
 * is 1.00 while a healthy probe is flat at 1.00, so the rule and a real reading
 * were the same colour at the same height and nothing on the page said which
 * was which. It is now a step darker than the data it judges, dashed, drawn
 * over the lines rather than under them, and named in the caption. It is
 * deliberately NOT a hue: the surface brief names pass/fail red-green as this
 * product's colourblind failure pair, and a green threshold beside a red
 * failure mark is exactly that pair. The separation from `context` is 2.2x in
 * luminance, which survives greyscale, and the dash carries it on top of that.
 *
 * **None of which made the rule findable, and the number says why.** `pass`
 * against `focal` is **1.88:1** — measured in a browser by a re-reviewer at 1x,
 * 4x and 6x zoom, and reproduced here from these two tokens. That is the ratio
 * of a rule to the healthy probe lying on top of it, and no re-hueing raises
 * it, because the two marks are not adjacent: they are the same pixels. The
 * rule therefore carries its own name on the chart (`TrendChart`'s
 * `passLineTag`), drawn in this same `pass` ink — **8.70:1** on `chassis-25`,
 * measured against the live painted ground and clear of the 4.5:1 text floor.
 * Ink was never the lever here. Identification was.
 */

const colors = tailwindConfig.theme.extend.colors;

export const CHART_INK = {
  focal: colors.chassis[900],
  context: colors.chassis[500],
  failed: colors.status.gate_failed,
  pass: colors.chassis[700],
  axis: colors.chassis[400],
  grid: colors.chassis[200],
  tick: colors.chassis[600],
  face: colors.chassis[25],
} as const;
