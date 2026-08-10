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
 *
 * **One line, and short — but it must keep its subject.** The first build spent
 * a 44-word paragraph at ~190 characters of measure, nearly triple the readable
 * ceiling, on every page. Cutting it to one line then cut the wrong half: it
 * kept *how* a removed value looks and dropped *what* gets removed, which is
 * the load-bearing noun. The banner is permanent precisely so nobody has to
 * wonder whether a quiet transcript is quiet or censored, and only the scope
 * answers that.
 *
 * So the line carries three facts and stops: redaction is on, **transcripts,
 * findings and paths** are what it touches, and this is what a removed value
 * looks like when you meet one.
 *
 * `reveal_required` is deliberately not rendered here. Revealing is per-object
 * and belongs beside the object being revealed (the finding detail view), not
 * as a fourth clause in a standing legend on six pages that have nothing to
 * reveal.
 */
export function RedactionBanner({ redaction }: { redaction: RedactionMeta }) {
  if (!redaction.enabled) return null;

  return (
    <div
      data-testid="redaction-banner"
      className="engrave-b flex items-start gap-2.5 bg-chassis-100 px-4 py-2 text-chassis-800 sm:px-6"
    >
      <IconRedacted className="h-4 w-4 shrink-0 text-chassis-600" />
      <p className="text-legend normal-case tracking-normal">
        <span className="uppercase tracking-[0.12em] text-chassis-900">
          Redaction on
        </span>
        <span className="mx-2 text-chassis-400" aria-hidden="true">
          ·
        </span>
        transcripts, findings and paths are scrubbed
        <span className="mx-2 text-chassis-400" aria-hidden="true">
          ·
        </span>
        removed values read{" "}
        <code className="bg-chassis-200 px-1 text-chassis-900">
          {redaction.marker}
        </code>
      </p>
    </div>
  );
}
