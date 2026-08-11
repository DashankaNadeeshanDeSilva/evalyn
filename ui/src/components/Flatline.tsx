import { IconFlatline, IconNotApplicable } from "./InstrumentIcon";

/**
 * A readout that carries no value — in one of **two** materially different
 * senses, which get two different marks.
 *
 * - `"dead"` — something should be here and is not. The artifact was
 *   unreadable, the field was never recorded. This is damage, and Product
 *   Principle 3 depends on it being visible as damage. Drawn as the flat-line
 *   trace *between end stops*.
 * - `"n/a"` — nothing should be here. A `compare` run has no gate verdict to
 *   report; that is correctness, not damage. Drawn as a bare centred stroke
 *   with no stops.
 *
 * ## `word` is required, and that is the whole design
 *
 * The mark alone was never enough. The `n/a` variant shipped at `chassis-400`
 * (2.30:1) as the *sole* content of its cell, with the meaning available only
 * through `title` and `sr-only` text — invisible to a keyboard, and on a
 * projector that cell simply reads as blank. Which is precisely the failure
 * this component's own docstring claims to prevent: degraded quietly coming to
 * mean blank.
 *
 * Making `word` required rather than optional is deliberate. Compare has
 * genuinely zero data, discoveries has an empty `probe_path`, trends have gaps;
 * five later pages are full of legitimately empty cells, and a required
 * parameter is what forces each of them to *say* what is absent instead of
 * rendering a hairline and hoping. Two extra characters at the call site, and
 * the glyph-plus-word rule holds across the whole cockpit.
 *
 * Contrast: the mark is `chassis-500` (4.03:1, clearing the 3:1 bar for a
 * graphical object) and the word is `chassis-600` (5.98:1, clearing AA for
 * text). The full reason still travels as `title` and as screen-reader text —
 * the visible word is the short form, not the whole story.
 *
 * `data-flatlined` marks a cell carrying no value. It is deliberately not
 * `data-metric`, which marks a cell carrying a real one.
 */
export function Flatline({
  reason,
  word,
  variant = "dead",
}: {
  /** The full explanation. Tooltip and screen-reader text. */
  reason: string;
  /** The short visible label. One or two words: `no gate`, `unrecorded`. */
  word: string;
  variant?: "dead" | "n/a";
}) {
  const Mark = variant === "dead" ? IconFlatline : IconNotApplicable;
  return (
    <span
      data-flatlined={variant}
      title={reason}
      // `text-legend` is set here rather than inherited, and that is the point:
      // the verdict and spend cells carry no size token, so an inherited size
      // meant the browser's 16px default won and the word rendered larger than
      // the values around it. A component that states its own size cannot be
      // broken by the cell it is dropped into.
      //
      // Legend, not readout: this is a label describing the cell's emptiness,
      // not a value. 12px is what every other label on the surface uses.
      className="inline-flex items-center gap-1.5 whitespace-nowrap text-legend"
    >
      <Mark className="h-4 w-6 shrink-0 text-chassis-500" />
      <span className="text-chassis-600">{word}</span>
      <span className="sr-only">{reason}</span>
    </span>
  );
}
