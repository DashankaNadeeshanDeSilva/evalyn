import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiFailure, apiGet } from "../api/client";
import type {
  CheckView,
  GateVerdict,
  RunDetail,
  TrialView,
} from "../api/types";
import { CheckEvidence } from "../components/CheckEvidence";
import { IconAlert, IconCheck, IconCross } from "../components/InstrumentIcon";
import { RedactedChip } from "../components/RedactedChip";
import {
  ScenarioTable,
  type TrialSelection,
} from "../components/ScenarioTable";
import {
  TranscriptViewer,
  type TranscriptAnnotation,
} from "../components/TranscriptViewer";

/**
 * The gate payload: the verdict, the probe rows behind it, and the conversation
 * behind one of those rows.
 *
 * Task 8 owns the route and the identity header; this owns everything below it.
 * The hierarchy is the surface brief's, top to bottom: **verdict → evidence →
 * transcript**. The operator arrives knowing a gate went red and leaves knowing
 * what the model said when it did.
 *
 * ## The verdict comes off `exit_code`, and only off `exit_code`
 *
 * `failures[]` is the *explanation*, not the verdict. A gate can exit non-zero
 * with an empty `failures[]` — an incompleteness check, a capability regression
 * measured against a baseline — and an implementation that counts the array
 * reports that run as a pass. `evaluate_gate`'s exit code is the authority and
 * it is the only thing this banner reads.
 *
 * ## No baseline is a fact, not a blank
 *
 * `baseline_run_id: null` means the gate had nothing to diff against, which
 * makes its capability checks advisory rather than enforcing. There is no
 * committed twincore baseline in this repository, so on the demo corpus this is
 * the normal case and not an edge one. Saying nothing there would let a green
 * banner imply a comparison that never happened.
 *
 * ## No SSE, no polling
 *
 * A finished artifact does not change. Task 21 owns the live view and the one
 * inset window that carries it; nothing here pretends to be live.
 */

/**
 * `TrialView.checks[]` -> `TranscriptViewer` annotations.
 *
 * Only checks that name a turn **and** quote something can be placed at all, so
 * the rest are filtered out here rather than handed down as annotations that can
 * never land. The ones that survive may still fail to place — the viewer matches
 * verbatim and reports what it could not mark — which is the behaviour every
 * artifact in `runs/` currently exercises, since their checks carry
 * `turn: null` and a description of what was missing rather than a quotable
 * span.
 */
export function annotationsFor(
  checks: readonly CheckView[],
): TranscriptAnnotation[] {
  return checks.flatMap((check, index) =>
    check.turn === null || check.evidence === ""
      ? []
      : [
          {
            // The check id repeats across trials and tiers, so the index is part
            // of the key. React would otherwise collapse two real annotations.
            id: `${check.check}#${index}`,
            turn: check.turn,
            evidence: check.evidence,
            label: check.check,
            // Rationed: only a check that actually went against the run reads as
            // a failure. `null` (unscored) and `abstained` stay neutral.
            tone: check.passed === false ? ("fail" as const) : ("neutral" as const),
            ...(check.tier === "abstained"
              ? { detail: "the judge abstained on this check" }
              : {}),
          },
        ],
  );
}

function GateBanner({ verdict }: { verdict: GateVerdict }) {
  const failed = verdict.exit_code !== 0;
  const Mark = failed ? IconCross : IconCheck;
  return (
    <section
      data-testid="gate-banner"
      data-verdict={failed ? "fail" : "pass"}
      aria-label="Gate verdict"
      className="engrave-b rule-major px-4 py-4 sm:px-6"
    >
      <p
        className={`flex items-center gap-2.5 text-display uppercase tracking-display ${
          failed ? "text-status-gate_failed" : "text-status-passed"
        }`}
      >
        <Mark className="h-6 w-6 shrink-0" />
        {/* Glyph AND word AND colour. This is the sentence the room reads. */}
        <span>{failed ? "gate failed" : "gate passed"}</span>
      </p>

      <p className="mt-1.5 flex flex-wrap items-baseline gap-x-3 text-legend text-chassis-600">
        <span className="uppercase tracking-legend">Exit code</span>
        <span className="tabular-nums text-chassis-900">
          {verdict.exit_code}
        </span>
        {verdict.redacted ? <RedactedChip what="this verdict" /> : null}
      </p>

      <p className="mt-2 text-legend text-chassis-600">
        {verdict.baseline_run_id === null ? (
          // Stated, because a gate with nothing to diff against enforces less
          // than one that had a baseline, and the difference is invisible.
          <>
            <span className="uppercase tracking-legend text-chassis-900">
              No baseline
            </span>
            {" — nothing was diffed against, so capability checks are advisory."}
          </>
        ) : (
          <>
            {"Diffed against baseline "}
            <span className="break-all text-chassis-900">
              {verdict.baseline_run_id}
            </span>
          </>
        )}
      </p>

      {verdict.failures.length > 0 ? (
        <div className="mt-3">
          <p className="text-legend uppercase tracking-legend text-chassis-600">
            Failures
          </p>
          <ul className="mt-1 space-y-1">
            {verdict.failures.map((line) => (
              <li
                key={line}
                className="break-words text-readout text-chassis-900"
              >
                {line}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {verdict.quarantined.length > 0 ? (
        <div className="mt-3">
          <p className="text-legend uppercase tracking-legend text-chassis-600">
            Quarantined
          </p>
          <ul className="mt-1 space-y-1">
            {verdict.quarantined.map((line) => (
              <li key={line} className="break-words text-readout text-chassis-700">
                {line}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function TrialPanel({
  runId,
  selection,
}: {
  runId: string;
  selection: TrialSelection;
}) {
  const trial = useQuery({
    queryKey: ["trial", runId, selection.probeId, selection.epoch],
    queryFn: () =>
      apiGet<TrialView>(
        `/runs/${encodeURIComponent(runId)}/trials/` +
          `${encodeURIComponent(selection.probeId)}/${selection.epoch}`,
      ),
  });

  return (
    <section
      data-testid="trial-panel"
      data-probe={selection.probeId}
      data-epoch={String(selection.epoch)}
      aria-label="Trial transcript"
      className="engrave-t rule-major"
    >
      <div className="engrave-b px-4 py-3 sm:px-6">
        <p className="text-legend uppercase tracking-legend text-chassis-600">
          Transcript
        </p>
        <h2 className="mt-1 flex flex-wrap items-baseline gap-x-3 text-panel">
          <span className="break-all text-chassis-900">
            {selection.probeId}
          </span>
          <span className="text-legend tabular-nums text-chassis-600">
            {`trial ${selection.epoch}`}
          </span>
          {trial.data?.redacted ? <RedactedChip what="this trial" /> : null}
        </h2>
        {trial.data ? (
          <p className="mt-1 flex flex-wrap items-baseline gap-x-4 text-legend text-chassis-600">
            <span>
              {"session "}
              {trial.data.session_seconds === null ? (
                // Pre-#2b logs did not record it, and it is not end-to-end
                // latency even when they did — the queue wait is excluded.
                <span className="text-chassis-700">not recorded</span>
              ) : (
                <span className="tabular-nums text-chassis-700">
                  {`${trial.data.session_seconds.toFixed(3)}s`}
                </span>
              )}
            </span>
            <span>
              {"invariant failures "}
              <span className="tabular-nums text-chassis-700">
                {trial.data.invariant_failures}
              </span>
            </span>
          </p>
        ) : null}
      </div>

      {trial.isPending ? (
        <p className="px-4 py-6 text-readout text-chassis-600 sm:px-6">
          Reading the trial record…
        </p>
      ) : trial.isError ? (
        <p className="flex items-start gap-2 px-4 py-6 text-readout text-chassis-900 sm:px-6">
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {trial.error instanceof ApiFailure
            ? `${trial.error.code ?? trial.error.status}: ${trial.error.message}`
            : "The cockpit could not reach its server."}
        </p>
      ) : (
        <>
          <TranscriptViewer
            turns={trial.data.turns}
            annotations={annotationsFor(trial.data.checks)}
            emptyReason="This trial record captured no conversation. That is 'not captured', not 'the model said nothing'."
          />
          <div className="engrave-t rule-major px-4 pt-3 sm:px-6">
            <p className="text-legend uppercase tracking-legend text-chassis-600">
              Checks on this trial
            </p>
          </div>
          {trial.data.checks.length === 0 ? (
            <p className="px-4 py-6 text-readout text-chassis-600 sm:px-6">
              This trial record carries no per-check results.
            </p>
          ) : (
            <ul>
              {trial.data.checks.map((check, index) => (
                <CheckEvidence key={`${check.check}#${index}`} check={check} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

export function GateRunDetail({ run }: { run: RunDetail }) {
  const [selected, setSelected] = useState<TrialSelection | null>(null);
  const gate = useQuery({
    queryKey: ["gate", run.run_id],
    queryFn: () =>
      apiGet<GateVerdict>(`/runs/${encodeURIComponent(run.run_id)}/gate`),
  });

  return (
    <div className="mt-4">
      {gate.isPending ? (
        <p className="engrave-t px-4 py-4 text-readout text-chassis-600 sm:px-6">
          Evaluating the gate…
        </p>
      ) : gate.isError ? (
        <p
          data-testid="gate-banner-error"
          className="engrave-t flex items-start gap-2 px-4 py-4 text-readout text-chassis-900 sm:px-6"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {/* Degrade visibly: the probe rows below are still readable, so the
              page states what it could not compute instead of emptying. */}
          {"The gate verdict could not be evaluated — "}
          {gate.error instanceof ApiFailure
            ? `${gate.error.code ?? gate.error.status}: ${gate.error.message}`
            : "the cockpit could not reach its server."}
        </p>
      ) : (
        <GateBanner verdict={gate.data} />
      )}

      <ScenarioTable
        probes={run.probes}
        capabilities={run.capabilities}
        selected={selected}
        onSelect={setSelected}
      />

      {selected === null ? null : (
        <TrialPanel runId={run.run_id} selection={selected} />
      )}
    </div>
  );
}
