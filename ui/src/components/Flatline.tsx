import { IconFlatline } from "./InstrumentIcon";

/**
 * A dead readout: the value this cell would carry does not exist.
 *
 * Rendered as the flat-line mark rather than an empty cell, because an empty
 * cell is indistinguishable from a rendering bug — and rendered with an
 * explicit reason in `title` plus screen-reader text, because the stroke itself
 * must never be the only thing carrying the meaning. (`degraded` measures
 * 2.43:1; it is redundant reinforcement, not the message.)
 *
 * `data-flatlined` marks the cell as carrying no value. It is deliberately not
 * `data-metric`, which marks a cell that carries a real one — that distinction
 * is what `RunsTable.test.tsx` asserts a degraded row against.
 */
export function Flatline({ reason }: { reason: string }) {
  return (
    <span
      data-flatlined="true"
      title={reason}
      className="inline-flex items-center text-degraded"
    >
      <IconFlatline className="h-4 w-6" />
      <span className="sr-only">{reason}</span>
    </span>
  );
}
