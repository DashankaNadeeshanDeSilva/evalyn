import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiFailure, useRunDetail } from "../api/client";
import { CostChip } from "../components/CostChip";
import { RunStatusChip } from "../components/RunStatusChip";
import { Flatline } from "../components/Flatline";
import {
  IconAlert,
  IconArrowLeft,
  IconFlatline,
} from "../components/InstrumentIcon";
import { isLive, LiveRunPanel } from "../components/LiveRunPanel";
import { formatUtc } from "../format";
import { isRunId, type Capabilities } from "../api/types";
import { GateRunDetail } from "./GateRunDetail";

/**
 * A single run's identity panel.
 *
 * Task 8 owns the route and the header; **Task 9 owns the payload** — the probe
 * table, the gate verdict and the transcript viewer. Everything rendered here
 * is a real field from `GET /api/runs/{id}`; nothing is invented to fill space,
 * and there is no placeholder pretending to be a chart.
 *
 * `capabilities` is stated plainly because it is what decides which
 * drill-downs Task 9 may offer. A legacy artifact answers none of them, and
 * "not captured" is a different fact from "empty".
 */

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="py-2">
      <dt className="text-legend uppercase tracking-legend text-chassis-600">{label}</dt>
      <dd className="mt-1 break-all text-readout text-chassis-900">
        {children}
      </dd>
    </div>
  );
}

/** The drill-downs this artifact can actually answer, or `null` for none. */
function readableDrilldowns(caps: Capabilities): string | null {
  const available = [
    caps.trial_records ? "trial records" : null,
    caps.transcripts ? "transcripts" : null,
    caps.hard_metrics ? "hard metrics" : null,
  ].filter((label): label is string => label !== null);
  return available.length > 0 ? available.join(" · ") : null;
}

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const detail = useRunDetail(runId);

  if (!isRunId(runId)) {
    return (
      <Shell runId={runId}>
        <p className="flex items-start gap-2 text-readout text-chassis-900">
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          That is not a run id. Artifact stems look like{" "}
          <code>20260804T081544953468-53e4125b-example</code>.
        </p>
      </Shell>
    );
  }

  if (detail.isPending) {
    return (
      <Shell runId={runId}>
        <p className="text-readout text-chassis-600">Reading the artifact…</p>
      </Shell>
    );
  }

  if (detail.isError) {
    return (
      <Shell runId={runId}>
        <p className="flex items-start gap-2 text-readout text-chassis-900">
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {detail.error instanceof ApiFailure
            ? `${detail.error.code ?? detail.error.status}: ${detail.error.message}`
            : "The cockpit could not reach its server."}
        </p>
      </Shell>
    );
  }

  const run = detail.data;
  const caps = run.capabilities;
  /*
   * Is a process attached right now? One value, read once per render, handed to
   * everything that needs it — the panel included. It used to be computed here
   * *and* latched inside the panel, and the two diverged the instant a run
   * finished.
   *
   * A live run has no finished artifact, which is what it decides: no verdict
   * to evaluate, and no artifact figure to report spend from.
   */
  const live = isLive(run.status);

  return (
    <Shell
      runId={runId}
      /*
       * The one inset window, directly under the run's own identity: the
       * hierarchy is live readout -> verdict -> evidence -> history, and the
       * operator needs to know *which* run is on the air before they read what
       * it is doing. The panel decides for itself whether there is anything to
       * show, and renders nothing when there is not.
       */
      live={
        <LiveRunPanel
          runId={run.run_id}
          status={run.status}
          live={live}
          packName={run.pack_name}
        />
      }
      /*
       * The payload, for the one mode that has a gate verdict.
       *
       * `mode` is classified lexically from the artifact's filename, so this is
       * a fact about the run rather than a guess from its contents — and
       * `/api/runs/{id}/gate` 404s for the other two, which makes asking the
       * bug rather than the answer. Tasks 15 and 16 hang their own payloads
       * here for `discover` and `compare`.
       *
       * It goes beside `children` rather than inside it because the payload's
       * tables and transcript span the whole instrument face: the identity
       * panel is inset by the shell's gutter, the panel lines beneath it are
       * not.
       */
      payload={
        run.mode === "gate" ? <GateRunDetail run={run} live={live} /> : null
      }
    >
      <dl className="grid grid-cols-1 gap-x-10 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Status">
          <RunStatusChip status={run.status} unverified={run.degraded} />
        </Field>
        <Field label="Mode">{run.mode}</Field>
        <Field label="Pack">
          {run.pack_name ?? (
            <Flatline word="unknown" reason="pack name not recorded" />
          )}
        </Field>
        <Field label="Created (UTC)">
          <span className="tabular-nums">{formatUtc(run.created_at)}</span>
        </Field>
        <Field label="Judge model">
          {run.judge_model ?? (
            <Flatline word="unrecorded" reason="judge model not recorded" />
          )}
        </Field>
        {live ? null : (
          <Field label="Judge USD">
            {/*
              **Spend is reported by the stream only while there is no artifact
              to report it, and by the artifact from the moment there is.**

              That sentence is true in every state, which the one it replaces
              was not. "One spend readout per screen" was asserted while `live`
              was recomputed here and separately latched inside the panel — so
              the instant a run finished, the refetch flipped this copy while
              the panel's stayed put, and a finished run rendered this chip
              *and* the window's figure together. In the `judge_usd: null` case
              that put "unrecorded" beside a real number, on the screen carrying
              the Cancel key.

              Both sides now key off the same `live`, in the same render. While
              it holds, the window owns the reading; the moment the refetch
              brings back a terminal status, this chip does — carrying the same
              pack ceiling by the same join. There is no instant at which both
              are on screen, and none at which neither is.
            */}
            <CostChip judgeUsd={run.judge_usd} packName={run.pack_name} />
          </Field>
        )}
        <Field label="Probes indexed">
          <span className="tabular-nums">{run.probes.length}</span>
        </Field>
        <Field label="Readable drill-downs">
          {/* Affordances come off `capabilities`, never off truthiness: an
              empty transcript list means "not captured", not "the
              conversation was empty". */}
          {readableDrilldowns(caps) ?? (
            <Flatline
              word="none captured"
              reason="this artifact captured no drill-downs"
            />
          )}
        </Field>
      </dl>

      {run.degraded ? (
        <p className="engrave-t mt-4 flex items-start gap-2 pt-3 text-readout text-chassis-700">
          <IconFlatline className="mt-1 h-3 w-8 shrink-0 text-chassis-500" />
          <span>
            <span className="text-legend uppercase tracking-legend text-chassis-900">
              Degraded
            </span>
            {" — "}
            {run.degraded_reason ?? "this artifact could not be fully read"}
          </span>
        </p>
      ) : null}
    </Shell>
  );
}

function Shell({
  runId,
  children,
  live = null,
  payload = null,
}: {
  runId: string;
  children: ReactNode;
  /** The inset readout window, full-bleed. Absent unless a run is on the air. */
  live?: ReactNode;
  /** Full-bleed, so its panel lines span the face rather than the gutter. */
  payload?: ReactNode;
}) {
  return (
    <section className="pb-16">
      <div className="engrave-b px-4 py-3 sm:px-6">
        <Link
          to="/runs"
          className="inline-flex items-center gap-1.5 text-legend uppercase tracking-legend text-chassis-600 transition-colors duration-state hover:text-chassis-900"
        >
          {/* Drawn, not `←`. The icon family's own comment explains at length
              why unicode marks are refused; this was the one that slipped. */}
          <IconArrowLeft className="h-4 w-4 shrink-0" />
          Runs
        </Link>
        <h1 className="mt-1.5 break-all text-display">
          {runId}
        </h1>
      </div>
      {live}
      <div className="px-4 py-2 sm:px-6">{children}</div>
      {payload}
    </section>
  );
}
