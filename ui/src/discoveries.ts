import type { CheckView, FindingRow, ReplayStatus } from "./api/types";
import type { TranscriptAnnotation } from "./components/TranscriptViewer";

/**
 * The discoveries model: the arithmetic and the wording behind the staging
 * bench, kept out of the component for the reason `trust.ts` is.
 *
 * `discover` does not report failures — it **stages candidate probes**. Every
 * file it writes carries a header saying the probe is staged and not adopted,
 * that adopting it is a move out of a gitignored directory, and that the file
 * may embed live data captured from the target verbatim, because redacting a
 * leaked value would break the outcome-graded confirmation the check exists to
 * make. The operator's real question on this page is therefore not "what broke"
 * but "should this become a permanent gate", and every function here serves
 * that decision.
 *
 * Which is why the wording is model logic rather than JSX. Three of the four
 * `ReplayStatus` members are routinely misread as verdicts, and the one that
 * matters most — a safety-critical finding whose replay was skipped on budget —
 * is the one an over-eager sentence would talk an operator out of adopting.
 */

export interface FindingTally {
  total: number;
  confirmed: number;
  safetyCritical: number;
  duplicates: number;
}

/**
 * What the replay establishes, in words, including when it establishes nothing.
 *
 * The enum has four members and **two of them are skips**. A skip is not a
 * negative result: `skipped_budget` means the run exhausted its cap before it
 * could try, and `skipped_disabled` means nobody asked it to. Neither is
 * evidence about whether the finding reproduces, and neither may borrow the
 * wording of `not_reproduced`.
 *
 * `null` is a fifth state the enum does not name — the row carries no replay
 * record at all — and it gets its own sentence for the same reason.
 */
export function replaySentence(status: ReplayStatus | null): string {
  switch (status) {
    case "reproduced":
      return "the replay reproduced this finding";
    case "not_reproduced":
      return "the replay ran and the finding did not reproduce";
    case "skipped_budget":
      return "no replay — the run's budget was exhausted before it could try";
    case "skipped_disabled":
      return "no replay — this run was asked to skip replays";
    case null:
      return "no replay was recorded for this finding";
  }
}

/**
 * Whether the row is a finding the run stood behind.
 *
 * `confirmed` and the replay status are independent axes and the page shows
 * both: the real `discovered-pii-leak` finding was confirmed by a required
 * invariant failing during the session, and separately never replayed because
 * the budget ran out. Folding the two into one verdict loses the half that
 * decides whether the finding is worth adopting.
 */
export function tallyFindings(rows: readonly FindingRow[]): FindingTally {
  return {
    total: rows.length,
    confirmed: rows.filter((row) => row.confirmed).length,
    safetyCritical: rows.filter((row) => row.safety_critical).length,
    duplicates: rows.filter((row) => row.duplicate_of !== null).length,
  };
}

/**
 * The objectives the loaded rows actually carry.
 *
 * Derived from the rows rather than hardcoded: objectives are pack-authored, so
 * a fixed list would be wrong for every pack but the one it was written
 * against. It is deliberately *not* claimed to be every objective the server
 * knows — it is the vocabulary of what has been loaded, which is the only set
 * the client can honestly offer.
 */
export function objectiveVocabulary(rows: readonly FindingRow[]): string[] {
  return [...new Set(rows.map((row) => row.objective_id))].sort();
}

/**
 * The checks, as marks on the transcript — and only where a mark is honest.
 *
 * Two filters, both refusals rather than tidying:
 *
 * - **`turn === null` is dropped.** A whole-session check has no index, and
 *   both real staged findings' required checks are of that kind
 *   (`rubric:groundedness` grades the session; `invariant:no-pii-leak` grades
 *   the session). Turning `null` into turn 1 would paint a highlight on words
 *   no check ever read.
 * - **Empty evidence is dropped.** There is no span to mark, and
 *   `TranscriptViewer` would report it as "not found verbatim", which states
 *   the wrong reason.
 *
 * Nothing is lost by either: every check is rendered in full by
 * `CheckEvidence`, which names what it looked at and prints its evidence as-is.
 *
 * The tone is rationed the way `TranscriptViewer` asks: `fail` only for a check
 * that actually went against the run. An abstaining check carries
 * `passed: null` and stays neutral, because a wash the eye reads as an alarm on
 * a reading nobody made is the one thing the payload must not do.
 */
export function annotationsFor(
  checks: readonly CheckView[],
): TranscriptAnnotation[] {
  const out: TranscriptAnnotation[] = [];
  checks.forEach((check, index) => {
    if (check.turn === null || check.evidence === "") return;
    out.push({
      // Index-prefixed: two checks can share a name as well as a turn, and the
      // id is both the React key and the mark's back-reference.
      id: `${index}:${check.check}`,
      turn: check.turn,
      evidence: check.evidence,
      label: check.check,
      tone: check.passed === false ? "fail" : "neutral",
      detail: check.required ? "required" : "advisory",
    });
  });
  return out;
}

/** A staged probe lives here, and adopting it is a move out of this segment. */
const STAGED_SEGMENT = "/discoveries/";

/**
 * The one consequential instruction this page gives, spelled out rather than
 * described.
 *
 * `discover` writes the same move into every staged file's own header: the
 * probe leaves `<pack>/discoveries/` for `<pack>/probes/`. `git mv` rather than
 * `mv`, because the point of the move is that the file starts being tracked —
 * `<pack>/discoveries/*.yaml` is gitignored, and leaving that directory is
 * exactly what removes the guard standing between a verbatim captured email
 * address and the repository's history.
 *
 * `null` when the path is not a staged discovery. A `git mv` assembled from a
 * guess is a line that silently moves a file somewhere nobody meant, and the
 * page prints nothing rather than that.
 */
export function adoptionCommand(probePath: string): string | null {
  const at = probePath.lastIndexOf(STAGED_SEGMENT);
  if (at === -1) return null;
  const adopted =
    probePath.slice(0, at) + "/probes/" + probePath.slice(at + STAGED_SEGMENT.length);
  return `git mv ${probePath} ${adopted}`;
}
