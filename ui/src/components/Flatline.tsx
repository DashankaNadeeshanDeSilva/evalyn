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
 * They were one mark in the first build, separated only by a `title` tooltip —
 * invisible to a keyboard and to a projector. Compare, discoveries, trends and
 * judge trust all have legitimately empty columns and would have inherited the
 * conflation wholesale, which is how "degraded" quietly comes to mean "blank".
 *
 * The reason travels with the mark either way: as `title` for a pointer and as
 * screen-reader text for everything else. `chassis-500` (4.03:1) carries it,
 * not the `degraded` grey (2.43:1) — in a metric cell this mark is the only
 * visible thing saying "nothing here".
 *
 * `data-flatlined` marks a cell carrying no value. It is deliberately not
 * `data-metric`, which marks a cell carrying a real one.
 */
export function Flatline({
  reason,
  variant = "dead",
}: {
  reason: string;
  variant?: "dead" | "n/a";
}) {
  const Mark = variant === "dead" ? IconFlatline : IconNotApplicable;
  return (
    <span
      data-flatlined={variant}
      title={reason}
      className={
        variant === "dead"
          ? "inline-flex items-center text-chassis-500"
          : "inline-flex items-center text-chassis-400"
      }
    >
      <Mark className="h-4 w-10" />
      <span className="sr-only">{reason}</span>
    </span>
  );
}
