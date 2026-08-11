import type { ReactNode } from "react";

import type { TranscriptTurn } from "../api/types";
import { RedactedChip } from "./RedactedChip";

/**
 * The conversation, with evidence marked on it.
 *
 * **This is the payload of the whole cockpit, not a detail view.** Product
 * Principle 2: a red gate is only useful if the operator can see what the model
 * actually said. Everything else on a run page exists to get them here with the
 * verdict already understood.
 *
 * ## One implementation, four callers
 *
 * Task 9 opens a gate trial; Task 15 shows a discovery's session; Task 17 shows
 * the pairs behind a judge-agreement figure; Task 21 streams turns as they
 * arrive. They differ only in *what is annotated on top*, so the annotation is a
 * prop and the viewer knows nothing about checks, findings or rubrics.
 *
 * ## The highlight is a span, and it is never guessed
 *
 * An annotation is placed only where its `evidence` is a **verbatim substring**
 * of the named turn. No trimming, no normalisation, no fuzzy match — this
 * component's entire claim is "the check pointed at *these words*", and a
 * highlight placed on an approximate match is a fabricated claim about evidence
 * on the screen that will be projected when a guardrail failed.
 *
 * That is not a hypothetical strictness. In every artifact in `runs/` today,
 * `checks[].turn` is `null` and `checks[].evidence` is a *description* of what
 * was missing ("missing 'I'm here to help with…'") rather than a quotable span,
 * so nothing places and the whole set lands in the unplaced list. Which is the
 * point: an annotation that cannot be placed is **reported, never dropped**.
 * Silently discarding a check's evidence is the exact failure this component
 * exists to prevent, and it would be invisible.
 *
 * ## Colour is never load-bearing here
 *
 * The marked span carries a tone-keyed ground, and the check's own name is
 * printed beneath the turn in words. Strip every colour and the turn still says
 * which check pointed at it and whether that check failed.
 *
 * Measured contrast — this file establishes two grounds beyond the page face,
 * and both inks clear AA on all three:
 *
 *   ground                    chassis-900   chassis-600
 *   chassis-25 (the face)        16.37         5.98
 *   chassis-200 (neutral mark)   12.90         4.71
 *   the failure wash             12.94         4.72
 *
 * No status ink appears in this file, and that is a constraint rather than an
 * omission: `status-passed` measures 3.81 on `chassis-200` and would fail.
 */

export interface TranscriptAnnotation {
  /** Stable within one render. Used as a key and as the mark's back-reference. */
  id: string;
  /** 1-based turn index, matching `CheckView.turn`. */
  turn: number;
  /** The exact span to mark. Placed only on a verbatim substring match. */
  evidence: string;
  /** What to call it in words — a check id, a criterion, an objective. */
  label: string;
  /**
   * `fail` is rationed to a reading that actually went against the run. Anything
   * advisory, abstained or merely informative is `neutral`, because a wash the
   * eye reads as an alarm is the one thing on this screen that must not cry
   * wolf.
   */
  tone: "fail" | "neutral";
  /** The long form, for the line printed beneath the turn. */
  detail?: string;
}

/** An annotation that was placed, with the offsets it was placed at. */
interface Placement {
  annotation: TranscriptAnnotation;
  start: number;
  end: number;
}

/**
 * Which annotations land on this turn's text, and where.
 *
 * Overlaps are resolved by refusing the later one rather than nesting marks: two
 * highlights sharing characters cannot both be "the span the check pointed at",
 * and the refused annotation goes to the unplaced list where it is still stated.
 */
function place(
  text: string,
  annotations: readonly TranscriptAnnotation[],
): Placement[] {
  const found: Placement[] = [];
  for (const annotation of annotations) {
    if (annotation.evidence === "") continue;
    const start = text.indexOf(annotation.evidence);
    if (start === -1) continue;
    found.push({ annotation, start, end: start + annotation.evidence.length });
  }
  found.sort((a, b) => a.start - b.start);
  const kept: Placement[] = [];
  for (const candidate of found) {
    const last = kept[kept.length - 1];
    if (last && candidate.start < last.end) continue;
    kept.push(candidate);
  }
  return kept;
}

/** The turn's text, split into plain runs and marked spans. */
function segments(text: string, placements: Placement[]): ReactNode[] {
  const out: ReactNode[] = [];
  let cursor = 0;
  for (const { annotation, start, end } of placements) {
    if (start > cursor) out.push(text.slice(cursor, start));
    out.push(
      <mark
        key={annotation.id}
        data-testid="evidence-span"
        data-tone={annotation.tone}
        data-annotation={annotation.id}
        title={annotation.label}
        /*
         * The user agent's own `mark` is a yellow fill this palette does not
         * define, and Tailwind's preflight does not reset it — so both the
         * ground and the ink are stated here rather than inherited.
         */
        className={
          annotation.tone === "fail"
            ? "bg-status-gate_failed/[0.14] text-chassis-900"
            : "bg-chassis-200 text-chassis-900"
        }
      >
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  }
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}

function AnnotationLine({
  annotation,
  placed,
}: {
  annotation: TranscriptAnnotation;
  placed: boolean;
}) {
  return (
    <li className="flex items-baseline gap-2 text-legend text-chassis-600">
      <span className="uppercase tracking-legend">
        {annotation.tone === "fail" ? "failed check" : "check"}
      </span>
      <span className="break-all">{annotation.label}</span>
      {annotation.detail ? <span>{`— ${annotation.detail}`}</span> : null}
      {placed ? null : (
        <span>
          {"— evidence not found verbatim in this transcript, so nothing was marked"}
        </span>
      )}
    </li>
  );
}

export function TranscriptViewer({
  turns,
  annotations = [],
  emptyReason,
}: {
  turns: readonly TranscriptTurn[];
  annotations?: readonly TranscriptAnnotation[];
  /**
   * Why there are no turns, in the caller's own words.
   *
   * **Required, for the same reason `Flatline`'s `word` is.** "Not captured" and
   * "the conversation was empty" are different facts and only the caller knows
   * which one applies — a pre-#2b artifact recorded nothing, a live run has not
   * spoken yet, a finding's replay was skipped on budget. A blank region states
   * neither, and an optional prop is how it stays blank.
   */
  emptyReason: string;
}) {
  if (turns.length === 0) {
    return (
      <p
        data-testid="transcript-empty"
        className="px-4 py-6 text-readout text-chassis-600 sm:px-6"
      >
        {emptyReason}
      </p>
    );
  }

  const placedIds = new Set<string>();
  const rows = turns.map((turn, index) => {
    const number = index + 1;
    const mine = annotations.filter((a) => a.turn === number);
    const placements = place(turn.text, mine);
    for (const p of placements) placedIds.add(p.annotation.id);
    return { turn, number, mine, placements };
  });

  const unplaced = annotations.filter((a) => !placedIds.has(a.id));

  return (
    <div>
      {/*
        Wide content scrolls inside its own container and the page body never
        scrolls sideways — but a transcript is prose, so the honest treatment is
        to wrap it rather than to hand the operator a horizontal scrollbar
        through a conversation. `whitespace-pre-wrap` keeps the model's own line
        breaks, which are sometimes the evidence.
      */}
      <ol className="engrave-t">
        {rows.map(({ turn, number, mine, placements }) => (
          <li
            key={number}
            data-testid="transcript-turn"
            data-turn={String(number)}
            data-role={turn.role}
            className="engrave-b px-4 py-3 sm:px-6"
          >
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-legend uppercase tracking-legend text-chassis-900">
                {turn.role}
              </span>
              <span className="text-legend tabular-nums text-chassis-600">
                {`turn ${number}`}
              </span>
              {/* Off the flag, never sniffed out of the text. */}
              {turn.redacted ? <RedactedChip what="this turn" /> : null}
            </div>
            <p className="mt-1.5 whitespace-pre-wrap break-words text-readout text-chassis-900">
              {segments(turn.text, placements)}
            </p>
            {placements.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {placements.map(({ annotation }) => (
                  <AnnotationLine
                    key={annotation.id}
                    annotation={annotation}
                    placed
                  />
                ))}
              </ul>
            ) : null}
            {mine.length > placements.length ? (
              <p className="sr-only">
                {`${mine.length - placements.length} annotation(s) name this turn but could not be placed on it`}
              </p>
            ) : null}
          </li>
        ))}
      </ol>

      {unplaced.length > 0 ? (
        <div
          data-testid="unplaced-annotations"
          className="px-4 py-3 sm:px-6"
        >
          <p className="text-legend uppercase tracking-legend text-chassis-900">
            Checks with no span in this transcript
          </p>
          <p className="mt-1 text-legend text-chassis-600">
            Their evidence is not a verbatim quote from a turn above, so nothing
            was marked. They are listed rather than dropped.
          </p>
          <ul className="mt-2 space-y-1">
            {unplaced.map((annotation) => (
              <AnnotationLine
                key={annotation.id}
                annotation={annotation}
                placed={false}
              />
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
