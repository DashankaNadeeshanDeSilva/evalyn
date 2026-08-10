import type { RedactionMeta } from "../api/types";
import { IconRedacted } from "./InstrumentIcon";

/**
 * The standing notice that what you are reading has been scrubbed.
 *
 * Always visible while redaction is on, and redaction is on by default with no
 * off switch. That is the whole point: transcripts and findings can carry real
 * identifiers from the product under test, so the operator must never have to
 * wonder whether a quiet-looking transcript is quiet or censored.
 *
 * It is a legend, not an alert — a permanent condition of the instrument, in
 * chassis ink on a chassis field. Safety orange is rationed to actions that
 * spend money or interrupt work, and this is neither.
 */
export function RedactionBanner({ redaction }: { redaction: RedactionMeta }) {
  if (!redaction.enabled) return null;

  return (
    <div
      data-testid="redaction-banner"
      className="engrave-b flex items-start gap-2.5 bg-chassis-100 px-4 py-2 text-chassis-800 sm:px-6"
    >
      <IconRedacted className="mt-px h-4 w-4 shrink-0 text-chassis-600" />
      <p className="text-readout">
        <span className="text-legend uppercase text-chassis-900">
          Redaction on
        </span>
        <span className="mx-2 text-chassis-400" aria-hidden="true">
          ·
        </span>
        Transcripts, findings and paths are scrubbed before they leave the
        server. A removed value reads{" "}
        <code className="bg-chassis-200 px-1 text-chassis-900">
          {redaction.marker}
        </code>
        {redaction.reveal_required
          ? ". Revealing is per-object and logged; there is no global off switch."
          : "."}
      </p>
    </div>
  );
}
