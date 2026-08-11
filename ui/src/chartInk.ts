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
 */

const colors = tailwindConfig.theme.extend.colors;

export const CHART_INK = {
  focal: colors.chassis[900],
  context: colors.chassis[500],
  failed: colors.status.gate_failed,
  axis: colors.chassis[400],
  grid: colors.chassis[200],
  tick: colors.chassis[600],
  face: colors.chassis[25],
} as const;
