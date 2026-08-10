import { IconFlatline } from "./InstrumentIcon";

/**
 * A dead readout: the value this cell would carry does not exist.
 *
 * Rendered as the flat-line trace rather than an empty cell, because an empty
 * cell is indistinguishable from a rendering bug — and carried by `chassis-500`
 * (4.03:1) rather than the `degraded` grey (2.43:1), because in a metric cell
 * this mark is the *only* visible thing saying "nothing here". The first render
 * used the degraded grey at glyph scale and it read as a speck.
 *
 * The reason travels with it, always: as `title` for a pointer and as
 * screen-reader text for everything else. The stroke is never the only carrier.
 *
 * `data-flatlined` marks a cell that carries no value. It is deliberately not
 * `data-metric`, which marks a cell that carries a real one — that distinction
 * is what `RunsTable.test.tsx` asserts a degraded row against.
 */
export function Flatline({ reason }: { reason: string }) {
  return (
    <span
      data-flatlined="true"
      title={reason}
      className="inline-flex items-center text-chassis-500"
    >
      <IconFlatline className="h-4 w-10" />
      <span className="sr-only">{reason}</span>
    </span>
  );
}
