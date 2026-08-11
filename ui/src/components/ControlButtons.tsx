import { useState } from "react";
import type { ReactNode } from "react";

import type { ControlAction } from "../api/types";
import type { RunPhase } from "../hooks/useRunEvents";
import { IconAlert, IconBarred, IconPause, IconRun } from "./InstrumentIcon";
import { SafetyKey } from "./SafetyKey";

/**
 * The controls inside the live readout window: pause, resume, cancel.
 *
 * ## Pause does not stop spend, and the control says so (ruling R4-12)
 *
 * Pause means "start no new samples". Trials already in flight run to
 * completion and **keep billing**, so a key labelled plainly "Pause" is a lie
 * about money on a product whose whole thesis is enforcement over advice. The
 * label is fixed by ruling: **"Pause (finishes in-flight trials)"**, with the
 * full consequence carried as text for a screen reader beside it.
 *
 * ## The 202 is not the acknowledgement
 *
 * `POST /api/runs/{id}/control` answering `accepted: true` says only that the
 * request was well-formed and the control file was written. The matching
 * `control.*` SSE event is what says the engine actually paused, resumed or
 * cancelled — so this component never flips its own state off a response. It
 * shows "waiting for the engine" until the phase moves, and the phase only
 * moves when an event says so.
 *
 * That wait is not always short and may never end: cancel is **not** built on
 * signals (ruling R4-11), and an unacknowledged cancel becomes an honest
 * `interrupted` run rather than a `SIGTERM`. The waiting line therefore reads
 * as a real state, not as a spinner that promises completion.
 *
 * ## Measured by hand against the dark ground (ruling R4-24)
 *
 *   inset-ink   on the inset window   15.21:1   key labels and alarm text
 *   chassis-400 on the inset window    7.58:1   the consequence and wait lines
 *   chassis-400 as the key's rule      7.58:1   the engraved edge  (1.4.11: 3)
 *
 * The orange lives in `SafetyKey`, which paints its own ground and measures
 * itself; there is exactly one of it here, because cancel is the only action in
 * this window that interrupts work.
 */

/** A key that is not dangerous: an engraved rule, ink, and nothing else. */
function BenchKey({
  onClick,
  title,
  children,
}: {
  onClick: () => void;
  title: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      /*
       * The same key shape the scenario table already established: a hard
       * rectangle whose only boundary is the engraved rule beneath it, snapping
       * between discrete inks. No box, no radius, no fill — a filled secondary
       * key beside the orange one would spend the ration twice.
       */
      className="engrave-b inline-flex items-center gap-2 px-3 py-2 text-legend uppercase tracking-legend text-inset-ink transition-colors duration-state [--rule:theme(colors.chassis.400)] hover:[--rule:theme(colors.inset.ink)]"
    >
      {children}
    </button>
  );
}

/** The consequence sentence, in one place so both renditions say it identically. */
const PAUSE_CONSEQUENCE =
  "Pausing starts no new samples. Trials already in flight finish, and keep spending.";
const CANCEL_CONSEQUENCE =
  "Cancelling starts no new samples. Trials already in flight finish, and keep spending. " +
  "The engine may take a while to acknowledge, and the artifact is still written.";

const WAITING_WORDS: Record<ControlAction, string> = {
  pause: "Pause requested",
  resume: "Resume requested",
  cancel: "Cancel requested",
};

export function ControlButtons({
  phase,
  requested,
  error,
  onAction,
}: {
  phase: RunPhase;
  /** The action whose ack has not arrived yet, or `null`. Never derived from a 202. */
  requested: ControlAction | null;
  /** A refused or failed control request, already turned into a sentence. */
  error: string | null;
  onAction: (action: ControlAction) => void;
}) {
  const [arming, setArming] = useState(false);

  // A run that has ended takes no more control requests, and the phase readout
  // beside these keys already says so.
  if (phase === "finished") return null;

  const alarm =
    error === null ? null : (
      <p
        data-testid="control-error"
        className="flex items-start gap-2 text-legend text-inset-ink"
      >
        <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{error}</span>
      </p>
    );

  if (requested !== null) {
    return (
      <div data-testid="control-waiting" className="max-w-sm space-y-2 text-right">
        <p className="text-legend text-chassis-400">
          {`${WAITING_WORDS[requested]} — waiting for the engine to acknowledge. `}
          {/* Said here rather than only on the key, because by now the key that
              carried the warning has been replaced by this line. */}
          {requested === "cancel" ? CANCEL_CONSEQUENCE : PAUSE_CONSEQUENCE}
        </p>
        {alarm}
      </div>
    );
  }

  if (phase === "cancelling") {
    return (
      <div className="max-w-sm space-y-2 text-right">
        <p data-testid="control-cancelling" className="text-legend text-chassis-400">
          {"Cancel acknowledged. In-flight trials are finishing, and still spending."}
        </p>
        {alarm}
      </div>
    );
  }

  // Nothing has been heard from the run yet, so there is nothing to interrupt.
  if (phase === "connecting") return alarm;

  if (arming) {
    return (
      <div
        data-testid="cancel-confirm"
        className="max-w-sm space-y-3 text-right"
        onKeyDown={(event) => {
          if (event.key === "Escape") setArming(false);
        }}
      >
        <p className="text-legend text-chassis-400">{CANCEL_CONSEQUENCE}</p>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <BenchKey title="Leave the run running" onClick={() => setArming(false)}>
            Keep running
          </BenchKey>
          {/* One primary dangerous action, and this is it. */}
          <SafetyKey
            autoFocus
            onClick={() => {
              setArming(false);
              onAction("cancel");
            }}
          >
            <IconBarred className="h-4 w-4 shrink-0" />
            Cancel run
          </SafetyKey>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2 text-right">
      <div className="flex flex-wrap items-center justify-end gap-3">
        {phase === "paused" ? (
          <BenchKey
            title="Start taking new samples again"
            onClick={() => onAction("resume")}
          >
            <IconRun className="h-4 w-4 shrink-0" />
            Resume
          </BenchKey>
        ) : (
          <BenchKey title={PAUSE_CONSEQUENCE} onClick={() => onAction("pause")}>
            <IconPause className="h-4 w-4 shrink-0" />
            {/* Fixed by ruling R4-12. A bare "Pause" claims a hard stop. */}
            Pause (finishes in-flight trials)
            <span className="sr-only">{` — ${PAUSE_CONSEQUENCE}`}</span>
          </BenchKey>
        )}

        <SafetyKey onClick={() => setArming(true)}>
          <IconBarred className="h-4 w-4 shrink-0" />
          Cancel run
        </SafetyKey>
      </div>
      {alarm}
    </div>
  );
}
