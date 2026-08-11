import { useState } from "react";
import { useQueries } from "@tanstack/react-query";

import { ApiFailure, apiGet } from "../api/client";
import type { CheckView, ProbeRow, TrialView } from "../api/types";
import { Flatline } from "./Flatline";
import { IconAlert, IconCheck, IconCross } from "./InstrumentIcon";
import { RedactedChip } from "./RedactedChip";

/**
 * Every trial of one probe, together — the answer to *"it says the approved
 * line six times in seven, and once it doesn't."*
 *
 * ## Why this exists beside the single-trial panel
 *
 * `TrialPanel` answers "what happened in trial 4". It cannot answer "is trial 4
 * unusual", because a claim about **variance across trials** is only legible
 * when the trials are next to each other. `pass^k` is exactly such a claim —
 * the gate fails a safety-critical probe when *any* trial fails — so the
 * evidence behind a red `pass^k` is a set, not a document, and the cockpit was
 * only ever able to show one member of it at a time.
 *
 * So the layout is the argument. The replies are stacked, left-aligned, at one
 * indent, with a fixed legend gutter: six identical blocks of text and one that
 * is a different shape. Nothing has to be *said* for that to be visible, which
 * is the point — a badge asserts the conclusion, a stack lets the room reach it.
 * A grid of tiles would ruin it (ragged left edges kill the comparison), and it
 * would also break the surface brief's ban on cards as the organising device.
 *
 * ## Marking is an enhancement, never the feature
 *
 * **`TrialView.checks` is `[]` on every artifact in `runs/` today**, and the 87
 * that already exist will never gain it. So the panel is built to be fully
 * useful with no check data at all — the replies together *are* the value — and
 * every mark below is layered on top of that, with `unmarked` stated in words
 * rather than left as a silence that reads like "nothing failed".
 *
 * ## What may and may not decide that a trial deviated
 *
 * Only a **required** check with `passed === false`. Not `passed: null`, which
 * is "no score" and never "failed"; not a non-required check, which can fail
 * without moving the gate; and above all **not a comparison of the replies to
 * each other**. The approved refusal lives in the pack, not on the wire — a
 * panel that recovered the marking by noticing six replies agree would be
 * inventing a verdict, and it would be right often enough to be believed.
 *
 * Nothing here keys off a position either. Measured: the deviating trial was
 * epoch 2 of 7 in one real run and epoch 6 of 7 in another, with different
 * wording each time, and two deviations in one probe is an ordinary state.
 *
 * ## Seven requests, seven independent outcomes
 *
 * There is no bulk endpoint, so this is seven parallel `GET`s under the same
 * query keys `TrialPanel` uses — opening one trial first warms this panel, and
 * vice versa. Each row renders its own pending, error and empty state, because
 * one unreadable trial record must cost exactly one row and not the panel.
 *
 * ## Contrast
 *
 * This file establishes **no ground of its own**, so every ink sits on the page
 * face `chassis-25` and is measured against it (the guard reasons per file and
 * would not see a ground some other file put behind it):
 *
 *   chassis-900 16.37   chassis-700 8.70   chassis-600 5.98
 *   status-gate_failed 6.24   status-passed 4.84
 *
 * All five clear AA for text. The row divisions are the shared engraved rule at
 * its default weight — no rule colour is named here, so there is no hand-
 * measured border figure to keep in sync.
 */

/**
 * How much of a reply is shown before it is cut.
 *
 * A character budget, not a line clamp, and that is deliberate: a CSS clamp
 * hides text at a length nothing in the DOM can state, so the panel could not
 * honestly say *how much* it was hiding, and a headless render or a narrow
 * window would silently move the boundary. Cutting the string means the cut is
 * a fact — countable, stated, and reversible.
 *
 * 360 characters is roughly four projected lines: long enough that a refusal is
 * never cut, short enough that seven long answers still fit one screen.
 */
const EXCERPT_CHARS = 360;

export interface Excerpt {
  shown: string;
  /** Characters withheld. `0` means the reply is on screen in full. */
  hidden: number;
}

/** Cut at a word boundary, never mid-word, and report the cost. */
export function excerpt(text: string): Excerpt {
  if (text.length <= EXCERPT_CHARS) return { shown: text, hidden: 0 };
  const window = text.slice(0, EXCERPT_CHARS);
  const space = window.search(/\s\S*$/);
  const cut = space > EXCERPT_CHARS * 0.6 ? space : EXCERPT_CHARS;
  return { shown: text.slice(0, cut), hidden: text.length - cut };
}

export type TrialMark = "deviated" | "conformed" | "unmarked";

/**
 * What this trial's own checks say about it — and `unmarked` whenever they say
 * nothing, which is today's every artifact.
 *
 * The three-way answer matters: collapsing `unmarked` into `conformed` would
 * paint six green ticks onto a run that never scored anything, which is the
 * same class of fabrication as painting a red one.
 */
export function markOf(checks: readonly CheckView[]): TrialMark {
  const required = checks.filter((check) => check.required);
  if (required.some((check) => check.passed === false)) return "deviated";
  if (required.length > 0 && required.every((check) => check.passed === true)) {
    return "conformed";
  }
  return "unmarked";
}

/** The required checks that went against this trial, for naming them. */
function failedChecks(checks: readonly CheckView[]): CheckView[] {
  return checks.filter((check) => check.required && check.passed === false);
}

interface Reply {
  text: string;
  /** 1-based index in the trial's own turn list. */
  turn: number;
  turns: number;
  redacted: boolean;
}

/**
 * The target's answer: the **last** assistant turn of the session.
 *
 * Not the first, and not the whole transcript. A probe's earlier assistant
 * turns are the setup an adversarial playbook walks through; the reply that
 * either carries the approved refusal or does not is the final one. The row
 * states which turn it took and how many there were, so the choice is visible
 * rather than implied, and the numbered key beside the probe still opens the
 * whole conversation.
 */
export function replyOf(trial: TrialView): Reply | null {
  for (let i = trial.turns.length - 1; i >= 0; i -= 1) {
    const turn = trial.turns[i]!;
    if (turn.role === "assistant") {
      return {
        text: turn.text,
        turn: i + 1,
        turns: trial.turns.length,
        redacted: turn.redacted,
      };
    }
  }
  return null;
}

const MARK_INK: Record<TrialMark, string> = {
  deviated: "text-status-gate_failed",
  conformed: "text-status-passed",
  // Never rendered — `unmarked` uses `Flatline`, which carries its own ink.
  unmarked: "",
};

const MARK_REASON: Record<TrialMark, string> = {
  deviated: "a required check failed on this trial",
  conformed: "every required check passed on this trial",
  unmarked:
    "this trial record carries no per-check result, so nothing is claimed about it",
};

function Mark({ mark, amongMarked }: { mark: TrialMark; amongMarked: boolean }) {
  if (mark === "unmarked") {
    /*
     * `unmarked` is worth saying **in a set where other trials are marked** —
     * there it distinguishes "this one did not fail" from "nobody looked at
     * this one". When no trial in the set is marked, which is every artifact in
     * `runs/` today, seven identical flat lines say nothing the panel's own
     * tally has not already said in a sentence, and they cost a column of ink
     * on a projector. Seen on the built page, not reasoned about.
     */
    if (!amongMarked) return null;
    return (
      <Flatline
        word="unmarked"
        reason={MARK_REASON.unmarked}
        variant="dead"
      />
    );
  }
  const Glyph = mark === "deviated" ? IconCross : IconCheck;
  return (
    <span
      data-testid="trial-mark"
      title={MARK_REASON[mark]}
      // Glyph AND word AND colour: the mark has to survive a monochrome
      // projector and the red/green colourblind pair, which is the one this
      // product's central output lands on.
      className={`inline-flex items-center gap-1.5 whitespace-nowrap text-legend uppercase tracking-legend ${MARK_INK[mark]}`}
    >
      <Glyph className="h-4 w-4 shrink-0" />
      {mark}
      <span className="sr-only">{` — ${MARK_REASON[mark]}`}</span>
    </span>
  );
}

function ReplyBody({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const cut = excerpt(text);
  return (
    <>
      <p
        data-testid="trial-reply"
        /*
         * A measure, not the full panel width. Seven replies are read as one
         * comparison, and a 180-character line makes the eye traverse rather
         * than compare — the same reason prose has a measure at all. 78ch of
         * this mono stack is ~660px, so six identical answers still wrap
         * identically and the odd one out still breaks the shape.
         */
        className="max-w-[78ch] whitespace-pre-wrap break-words text-readout text-chassis-900"
      >
        {open || cut.hidden === 0 ? text : `${cut.shown}…`}
      </p>
      {cut.hidden === 0 ? null : (
        <button
          type="button"
          data-testid="reply-expand"
          aria-expanded={open}
          onClick={() => setOpen((was) => !was)}
          // The same key vocabulary as the trial keys: a hard rectangle over an
          // engraved rule, snapping between two positions. `chassis-700` on the
          // face measures 8.70.
          className="mt-1.5 text-legend uppercase tracking-legend text-chassis-700 transition-colors duration-state hover:text-chassis-900 engrave-b [--rule:theme(colors.chassis.500)] hover:[--rule:theme(colors.chassis.900)]"
        >
          {open
            ? "show less"
            : `show ${cut.hidden} more characters`}
        </button>
      )}
    </>
  );
}

/** One trial: its number and mark in the gutter, its reply beside them. */
function TrialRow({
  runId,
  probeId,
  epoch,
  amongMarked,
  query,
}: {
  runId: string;
  probeId: string;
  epoch: number;
  /** Some other trial in this set carries a verdict, so silence is ambiguous. */
  amongMarked: boolean;
  query: {
    isPending: boolean;
    isError: boolean;
    error: unknown;
    data: TrialView | undefined;
  };
}) {
  const trial = query.data;
  const mark = trial ? markOf(trial.checks) : "unmarked";
  const reply = trial ? replyOf(trial) : null;
  const failed = trial ? failedChecks(trial.checks) : [];

  return (
    <li
      data-testid="all-trials-row"
      data-epoch={String(epoch)}
      data-mark={mark}
      className="engrave-b grid gap-x-4 gap-y-1 px-4 py-3 sm:grid-cols-[9rem_1fr] sm:px-6"
    >
      {/* The legend gutter. Fixed width so the replies share one left edge —
          the alignment is what makes six identical answers and one different
          one legible without reading a word of them. */}
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 sm:block">
        <p className="text-legend uppercase tracking-legend tabular-nums text-chassis-900">
          {`trial ${epoch}`}
        </p>
        <div className="sm:mt-1">
          {query.isPending || query.isError ? null : (
            <Mark mark={mark} amongMarked={amongMarked} />
          )}
        </div>
      </div>

      <div>
        {query.isPending ? (
          <p className="text-readout text-chassis-600">
            Reading this trial record…
          </p>
        ) : query.isError ? (
          // One unreadable record costs one row. The others keep their replies,
          // which is what makes this a degrade rather than a blank panel.
          <p className="flex items-start gap-2 text-readout text-chassis-900">
            <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
            {query.error instanceof ApiFailure
              ? `${query.error.code ?? query.error.status}: ${query.error.message}`
              : "The cockpit could not reach its server."}
          </p>
        ) : reply === null ? (
          <p className="text-readout text-chassis-600">
            {trial && trial.turns.length === 0
              ? "This trial record captured no conversation. That is 'not captured', not 'the model said nothing'."
              : "This trial record captured no reply from the target — its turns carry no assistant message."}
          </p>
        ) : (
          <>
            <ReplyBody text={reply.text} />
            <p className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-legend text-chassis-600">
              <span className="tabular-nums">
                {`assistant turn ${reply.turn} of ${reply.turns}`}
              </span>
              {reply.redacted ? <RedactedChip what="this turn" /> : null}
            </p>
          </>
        )}

        {failed.length === 0 ? null : (
          // The mark asserts; this is the evidence under it. A red word with no
          // named check is a score, not a finding.
          <ul className="mt-1.5 space-y-1">
            {failed.map((check, index) => (
              <li
                key={`${check.check}#${index}`}
                className="flex flex-wrap items-baseline gap-x-2 text-legend text-chassis-600"
              >
                <span className="uppercase tracking-legend">
                  Failed required check
                </span>
                <span className="break-all text-chassis-900">{check.check}</span>
                {check.evidence === "" ? null : <span>{check.evidence}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <span className="sr-only">
        {`Trial ${epoch} of ${probeId} in run ${runId}.`}
      </span>
    </li>
  );
}

/**
 * The one sentence the panel says out loud, built from what actually loaded.
 *
 * Counted, never assumed: "exactly one deviating trial" is a property of one
 * run, not of the feature, and a hardcoded "1 of 7" would be right on stage and
 * wrong forever after.
 */
function tally(
  marks: readonly TrialMark[],
  total: number,
  unread: number,
): string {
  const deviated = marks.filter((m) => m === "deviated").length;
  const conformed = marks.filter((m) => m === "conformed").length;
  const unmarked = marks.filter((m) => m === "unmarked").length;
  const unreadSuffix =
    unread === 0
      ? ""
      : ` ${unread} of ${total} could not be read, and is counted in neither.`;

  if (marks.length === 0) {
    return unread === total && unread > 0
      ? `None of the ${total} trial records could be read.`
      : `Reading ${total} trial records…`;
  }
  if (deviated > 0) {
    return (
      `${deviated} of ${total} trials failed a required check.` + unreadSuffix
    );
  }
  if (unmarked === marks.length) {
    // The state of every artifact in `runs/` today. Said plainly, because a
    // silent absence of marks reads as "nothing failed".
    return (
      `These trial records carry no per-check results, so no trial is marked` +
      ` — the replies are shown as recorded.` +
      unreadSuffix
    );
  }
  if (unmarked > 0) {
    return (
      `No trial failed a required check; ${unmarked} of ${total} carry no` +
      ` per-check result.` +
      unreadSuffix
    );
  }
  return `All ${conformed} of ${total} trials passed every required check.${unreadSuffix}`;
}

export function AllTrialsPanel({
  runId,
  probe,
}: {
  runId: string;
  probe: ProbeRow;
}) {
  /**
   * The epochs, deduplicated and read in ascending order.
   *
   * `trial_epochs` is the authority on which trials exist — never `trials`,
   * which counts trials the artifact may not have captured a record for. The
   * sort is a display decision: an epoch is an ordinal, and a room reading
   * seven answers as a sequence needs them in sequence whatever order the
   * server listed them in. The dedupe keeps a repeated epoch from colliding two
   * rows onto one React key.
   */
  const epochs = [...new Set(probe.trial_epochs)].sort((a, b) => a - b);

  const queries = useQueries({
    queries: epochs.map((epoch) => ({
      // The same key `TrialPanel` uses, so the two views share one cache entry
      // per trial rather than re-fetching each other's work.
      queryKey: ["trial", runId, probe.id, epoch],
      queryFn: () =>
        apiGet<TrialView>(
          `/runs/${encodeURIComponent(runId)}/trials/` +
            `${encodeURIComponent(probe.id)}/${epoch}`,
        ),
    })),
  });

  const loaded = queries.flatMap((q) => (q.data ? [q.data] : []));
  const amongMarked = loaded.some(
    (trial) => markOf(trial.checks) !== "unmarked",
  );
  const unread = queries.filter((q) => q.isError).length;
  const opening = loaded
    .map((trial) => ({
      trial,
      turn: trial.turns.find((t) => t.role === "user") ?? null,
    }))
    .find((candidate) => candidate.turn !== null);

  return (
    <section
      data-testid="all-trials-panel"
      data-probe={probe.id}
      aria-label="All trials of this probe"
      className="engrave-t rule-major"
    >
      <div className="engrave-b px-4 py-3 sm:px-6">
        <p className="text-legend uppercase tracking-legend text-chassis-600">
          All trials
        </p>
        <h2 className="mt-1 flex flex-wrap items-baseline gap-x-3 text-panel">
          <span className="break-all text-chassis-900">{probe.id}</span>
          <span className="text-legend tabular-nums text-chassis-600">
            {`${epochs.length} trial records`}
          </span>
          {probe.safety_critical ? (
            // Not colour: this is the fact that turns pass^k into a hard gate,
            // and it is why one deviating trial fails the whole probe.
            <span className="text-legend uppercase tracking-legend text-chassis-900">
              safety-critical
            </span>
          ) : null}
        </h2>

        <p
          data-testid="all-trials-tally"
          className="mt-1.5 text-legend text-chassis-600"
        >
          {tally(
            loaded.map((trial) => markOf(trial.checks)),
            epochs.length,
            unread,
          )}
        </p>

        {opening?.turn ? (
          <p className="mt-2 text-legend text-chassis-600">
            {/* Attributed, never generalised: the trials are not guaranteed to
                have been sent the same words, so this says which one it read
                rather than claiming it stands for all seven. */}
            <span className="uppercase tracking-legend">
              {`Opening turn, as sent in trial ${opening.trial.epoch}`}
            </span>
            <span className="mt-1 block whitespace-pre-wrap break-words text-readout text-chassis-700">
              {opening.turn.text}
            </span>
          </p>
        ) : null}
      </div>

      <ol>
        {epochs.map((epoch, index) => (
          <TrialRow
            key={epoch}
            runId={runId}
            probeId={probe.id}
            epoch={epoch}
            amongMarked={amongMarked}
            query={queries[index]!}
          />
        ))}
      </ol>
    </section>
  );
}
