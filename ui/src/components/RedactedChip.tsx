import { IconRedacted } from "./InstrumentIcon";

/**
 * "Something here went through the redactor."
 *
 * Redaction is a chokepoint in this product, not a per-view concern: transcripts
 * and findings can carry real identifiers from the product under test, so every
 * body leaves the server already scrubbed. What the operator needs from the
 * cockpit is the *fact* that scrubbing happened here, because a
 * `«redacted:org»` marker in the middle of a sentence is easy to read past and
 * an absent value is easy to read as "the model said nothing".
 *
 * The flag is the authority, never the text. A turn can be flagged `redacted`
 * with no visible marker (the redactor removed a whole clause), and a turn can
 * contain the literal marker without having been touched (the model typed it).
 * Sniffing `REDACTION_MARKER_RE` out of the string gets both cases wrong, which
 * is why this component takes no text at all.
 *
 * Shared deliberately: `TranscriptTurn`, `CheckView`, `GateVerdict`,
 * `FindingRow` and `Scoreboard` all carry the same boolean, and Tasks 15, 16 and
 * 17 render three of those.
 */
export function RedactedChip({ what = "this value" }: { what?: string }) {
  const reason = `${what} passed through the redactor before it left the server`;
  return (
    <span
      data-testid="redacted-chip"
      title={reason}
      className="inline-flex items-center gap-1 whitespace-nowrap text-legend uppercase tracking-legend text-chassis-600"
    >
      <IconRedacted className="h-3.5 w-3.5 shrink-0" />
      redacted
      <span className="sr-only">{` — ${reason}`}</span>
    </span>
  );
}
