import type { ReactElement, ReactNode } from "react";

import type { EventName } from "../api/types";
import { formatUsd } from "../format";
import type { RunEventsState, RunPhase } from "../hooks/useRunEvents";
import {
  IconAlert,
  IconBarred,
  IconCheck,
  IconLive,
  IconPause,
  IconQuery,
} from "./InstrumentIcon";

/**
 * The one inset window.
 *
 * `.impeccable/surfaces/ui-src.md` §3 reserves exactly one darker, recessed
 * readout region on the whole surface, and this is it: the single dark field,
 * the asymmetry that breaks the strict grid, and the reason the bench metaphor
 * survives a light theme. It **appears only while something is actually running
 * or has just finished** — it is not a permanent decorative slab, which is why
 * nothing renders it from a route and only the live panel mounts it.
 *
 * It is a readout, not a log. Every line here is a *current* reading; the run's
 * history lives in the artifact underneath, and a scrolling event tail would be
 * a second, worse transcript viewer.
 *
 * ## ⚠ Every ink here was measured by hand against the dark ground
 *
 * The contrast guard reasons per file and is blind to this composition (ruling
 * R4-24): a component written against the pale chassis and dropped in here is
 * still measured against the pale chassis, and passes while being unreadable.
 * So the numbers below are hand-computed with the guard's own formula, and the
 * refusals are as load-bearing as the permissions:
 *
 *   inset-ink   on the inset window   15.21:1   readings, and every alarm word
 *   chassis-400 on the inset window    7.58:1   legends and secondary prose
 *   chassis-300 on the inset window   11.27:1   (available, unused)
 *
 *   REFUSED — chassis-600            2.92:1   the pale face's secondary prose
 *             chassis-500            4.33:1   just under AA for body text
 *             status-running         2.69:1   every status hue fails here:
 *             status-passed          3.60:1   passed, gate_failed and running
 *             status-gate_failed     2.79:1   are all below AA on this ground
 *
 * The consequence is concrete: `Flatline`, `RunStatusChip`, `CostChip` and
 * `VerdictBadge` all read correctly on the chassis and **must not be rendered
 * inside this window**, because each of them carries chassis-600 or a status
 * hue. The absent-value renditions below are written locally for that reason
 * rather than reused, and the local one says the same thing in the same words.
 *
 * Colour does no work in here at all: every state is a glyph and a word in the
 * one ink. That is stricter than "never colour alone", deliberately — the dark
 * field has no hue that clears AA on it, so leaning on one would have been the
 * failure the guard cannot see.
 */

const PHASE_WORDS: Record<RunPhase, string> = {
  connecting: "connecting",
  running: "live",
  paused: "paused",
  // Not "cancelled": the engine acknowledged the request and in-flight trials
  // are still finishing — and still spending. `run.finished` is what stops it.
  cancelling: "cancelling",
  finished: "finished",
};

/**
 * The mark for the phase. `finished` splits on the exit code, but **both
 * renditions say "finished"** — the verdict is the gate banner's job below, and
 * a cross up here would claim a gate failure for a run that exited 3 because
 * the operator cancelled it.
 */
function phaseMark(
  phase: RunPhase,
  exitCode: number | null,
): (props: { className?: string }) => ReactElement {
  switch (phase) {
    case "connecting":
      return IconQuery;
    case "running":
      return IconLive;
    case "paused":
      return IconPause;
    case "cancelling":
      return IconBarred;
    case "finished":
      return exitCode === 0 ? IconCheck : IconAlert;
  }
}

/** What the last frame was, in the surface's own words rather than its wire name. */
const ACTIVITY_WORDS: Partial<Record<EventName, string>> = {
  "run.started": "run started",
  "trial.started": "trial started",
  "turn.sent": "sent turn",
  "turn.received": "received turn",
  "probe.scored": "scored",
  "artifact.written": "artifact written",
  "control.paused": "pause acknowledged",
  "control.resumed": "resume acknowledged",
  "control.cancelled": "cancel acknowledged",
  "run.finished": "run finished",
};

function Reading({
  label,
  testId,
  children,
}: {
  label: string;
  /** Set only where a test must count reporters rather than read a figure. */
  testId?: string;
  children: ReactNode;
}) {
  return (
    <div data-testid={testId}>
      <dt className="text-legend uppercase tracking-legend text-chassis-400">
        {label}
      </dt>
      <dd className="mt-0.5 text-readout text-inset-ink">{children}</dd>
    </div>
  );
}

/** A reading the stream has not reported. Never `0`, never an empty cell. */
function Unreported({ what }: { what: string }) {
  return <span className="text-chassis-400">{what}</span>;
}

export function LiveBanner({
  state,
  showSpend = true,
  ceiling = null,
  ceilingSettled = false,
  children,
}: {
  state: RunEventsState;
  /**
   * Does the stream still own the spend reading?
   *
   * It owns it only while there is no artifact to own it instead. Once one
   * exists, the identity panel's chip reports the authoritative figure and this
   * reading stands down — one readout on screen at every instant, decided by
   * one value the caller also uses, never by a second opinion taken here.
   */
  showSpend?: boolean;
  /**
   * The pack's own `max_usd_per_run`, or `null` when this build cannot learn it
   * — the run's pack may not be on the running server's allowlist at all.
   */
  ceiling?: number | null;
  /**
   * Has the lookup finished? `null` before it settles is "still reading";
   * `null` after it settles is the claim "there is no ceiling to show", and the
   * two must not render as the same thing.
   */
  ceilingSettled?: boolean;
  /** The controls. Passed in so the rationed orange lives in its own file. */
  children?: ReactNode;
}) {
  const Mark = phaseMark(state.phase, state.exitCode);
  const activity = state.activity;
  const stalled = state.connection === "closed" && state.phase !== "finished";

  return (
    <section
      data-testid="live-window"
      data-phase={state.phase}
      data-connection={state.connection}
      /*
       * The hook the focus ring hangs on. The surface's one focus treatment is
       * a hard rule in the near-black chassis ink, which measures 1.06:1 on
       * this ground — invisible, on the only region of the surface that
       * carries a dangerous control. `index.css` inverts it here, keyed to this
       * attribute, so no component inside can forget it and none can reset it.
       */
      data-field="inset"
      aria-label="Live run readout"
      className="engrave-t engrave-b rule-major bg-inset px-4 py-5 sm:px-6"
    >
      <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
        <p
          data-testid="live-phase"
          // The one announcement in the window: an operator who has looked away
          // needs the phase change, not every turn of every trial.
          aria-live="polite"
          className="flex items-center gap-2.5 text-display uppercase tracking-display text-inset-ink"
        >
          <Mark className="h-6 w-6 shrink-0" />
          <span>{PHASE_WORDS[state.phase]}</span>
        </p>
        {children ? <div className="ml-auto">{children}</div> : null}
      </div>

      <dl className="mt-5 flex flex-wrap gap-x-10 gap-y-4">
        {showSpend ? (
        <Reading label="Judge spend" testId="live-spend">
          {state.judgeUsd === null ? (
            // `null` is not `$0.0000`: a run that has not reported spend is not
            // a run that spent nothing, and this window is where an operator
            // decides whether to stop paying.
            <Unreported what="not reported yet" />
          ) : (
            <span data-numeric="judge_usd" className="tabular-nums">
              {formatUsd(state.judgeUsd)}
            </span>
          )}
          {/*
            The ceiling travels with the figure, because `$0.0138` means
            nothing until you know whether the pack's per-run ceiling is two
            dollars or two cents — and this is the readout beside a Cancel key.
            `CostChip` makes the same argument on the pale face; it cannot be
            reused here (chassis-600, 2.92:1 on this ground), so the comparison
            is re-rendered rather than dropped.
          */}
          {!ceilingSettled ? null : ceiling === null ? (
            <span className="ml-2 text-legend text-chassis-400">
              pack ceiling unknown
            </span>
          ) : (
            <span className="ml-2 text-legend text-chassis-400">
              <span className="tabular-nums">{`of ${formatUsd(ceiling)}`}</span>
              {" ceiling"}
              {state.judgeUsd !== null && ceiling > 0 ? (
                <span className="tabular-nums">
                  {` · ${((state.judgeUsd / ceiling) * 100).toFixed(1)}% used`}
                </span>
              ) : null}
            </span>
          )}
        </Reading>
        ) : null}

        <Reading label="Probes scored">
          {/* Derived from the list itself — never a counter that can drift
              away from the rows it claims to count. */}
          <span data-numeric="probes_scored" className="tabular-nums">
            {state.probes.length}
          </span>
        </Reading>

        <Reading label="Trials started">
          <span data-numeric="trials" className="tabular-nums">
            {state.trials}
          </span>
        </Reading>

        {state.phase === "finished" ? (
          <Reading label="Exit code">
            {state.exitCode === null ? (
              <Unreported what="not reported" />
            ) : (
              <span data-numeric="exit_code" className="tabular-nums">
                {state.exitCode}
              </span>
            )}
          </Reading>
        ) : null}
      </dl>

      <p
        data-testid="live-activity"
        className="mt-4 break-all text-legend text-chassis-400"
      >
        {activity === null
          ? "no events yet"
          : [
              ACTIVITY_WORDS[activity.name] ?? activity.name,
              activity.probeId,
              activity.epoch === null ? null : `trial ${activity.epoch}`,
              activity.turn === null ? null : `turn ${activity.turn}`,
            ]
              .filter((part): part is string => part !== null)
              .join(" · ")}
      </p>

      {state.connection === "reconnecting" || stalled || state.missedEvents > 0 ? (
        <p
          data-testid="live-connection"
          className="mt-3 flex items-start gap-2 text-legend text-inset-ink"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {stalled
              ? "The event stream closed before the run finished. This readout has stopped updating — reload the page to resubscribe. The run itself is unaffected."
              : state.connection === "reconnecting"
                ? "Reconnecting. The browser is resubscribing from the last event it saw."
                : // Open again, but the gap is a permanent fact about this
                  // session: the readings above are lower bounds, not totals.
                  "The stream lost events earlier, so the readings above may under-report."}
            <span className="tabular-nums">
              {state.missedEvents > 0
                ? ` ${state.missedEvents} event${state.missedEvents === 1 ? "" : "s"} lost.`
                : ""}
            </span>
          </span>
        </p>
      ) : null}
    </section>
  );
}
