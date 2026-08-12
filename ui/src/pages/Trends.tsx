import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiFailure, apiGet } from "../api/client";
import {
  TREND_METRICS,
  type PackListPage,
  type TrendMetric,
  type TrendSeries,
} from "../api/types";
import { Detent } from "../components/Detent";
import { IconAlert } from "../components/InstrumentIcon";
import { TrendChannels } from "../components/TrendChannels";
import { TrendChart } from "../components/TrendChart";
import { METRIC_FACTS, buildTrendModel } from "../trends";

/**
 * Trends: one probe's history against every other probe's, across the pack.
 *
 * The page answers a question the runs list cannot — *is this failure
 * recurrent, or did I catch a bad afternoon?* That is why the scope draws every
 * channel and picks one out, rather than drawing the selected probe alone: the
 * answer is only worth anything beside its siblings.
 *
 * ## What is derived, and why nothing here is a literal
 *
 * Ruling R4-6: the corpus grows whenever an eval runs, so a probe count, a
 * reading count or a run count written down in this file is wrong on the day it
 * is written. Every figure in the readout comes off the response.
 *
 * ## `?pack=` is a NAME
 *
 * `/api/runs` filters on `row.pack_name` and `TrendSeries.pack_name` is a name,
 * so the selector sends `PackRow.name`. `PackRow.path` is a display-safe label
 * with `$HOME` collapsed — it is not a usable path and it is never sent back.
 *
 * The list is the launch allowlist, which is the set of packs this server was
 * *started with* rather than the set that has history. A pack in the list with
 * no readable runs is a legitimate, stated empty state, not an error.
 *
 * ## The metric is re-fetched, never converted
 *
 * Moving the metric detent re-asks the server. Nothing here derives `pass@k`
 * from `pass^k` or a mean score from either: they are different measurements
 * over the same trials and only the server has the trial records.
 *
 * ## Deferred — this page has never met its own route
 *
 * `GET /api/trends` is Task 13's, and it is being built in parallel. Everything
 * below is proven against the frozen wire model and the MSW layer; the wiring
 * pass must confirm three things a mock cannot:
 *
 * 1. A degraded run really is **absent** from every series rather than present
 *    with a zero — the whole chart's honesty rests on it, and 26 of the
 *    `example` pack's runs are degraded.
 * 2. `?pack=` really does take the pack **name** the allowlist reports.
 * 3. A pack with no calibration/history answers `200` with an empty array
 *    rather than a 404, which is what the empty state here assumes.
 */

function Legend({ children }: { children: string }) {
  return (
    <h2 className="text-legend uppercase tracking-legend text-chassis-600">
      {children}
    </h2>
  );
}

export function Trends() {
  const packs = useQuery({
    queryKey: ["packs"],
    queryFn: () => apiGet<PackListPage>("/packs"),
  });

  const [chosenPack, setChosenPack] = useState<string | null>(null);
  const [metric, setMetric] = useState<TrendMetric>("pass_k");
  const [chosenProbe, setChosenProbe] = useState<string | null>(null);

  // `GET /api/packs` is an envelope, never a bare array.
  const packNames = packs.data?.items.map((row) => row.name) ?? [];
  const pack = chosenPack ?? packNames[0] ?? null;

  const trends = useQuery({
    queryKey: ["trends", pack, metric],
    queryFn: () => {
      const query = new URLSearchParams({ pack: pack!, metric });
      return apiGet<TrendSeries[]>(`/trends?${query.toString()}`);
    },
    enabled: pack !== null,
  });

  const series = useMemo(() => trends.data ?? [], [trends.data]);
  const model = useMemo(() => buildTrendModel(series, metric), [series, metric]);

  /*
   * The selection is DERIVED, not stored in an effect.
   *
   * The operator's choice wins while it still names a channel that exists;
   * otherwise the page falls back to the most notable channel for the metric.
   * Changing pack or metric therefore re-opens on the worst reading with no
   * effect to fire, no stale probe id, and no frame where the chart is blank.
   */
  const selectedProbeId =
    model.channels.find((c) => c.probeId === chosenProbe)?.probeId ??
    model.channels[0]?.probeId ??
    null;

  const facts = METRIC_FACTS[metric];

  /*
   * Two reads stand between this page and a number, and **neither may be
   * reported as zero while it is still in flight**.
   *
   * The allowlist read was missing from this condition in the first draft, and
   * the page spent every render before it landed claiming "0 probes · 0
   * readings · 0 runs" — the exact defect the runs list already carries a
   * ruling about: zero is a measurement, and the client does not have one. It
   * was invisible until a test asserted on the readout's text.
   */
  const reading = packs.isPending || (pack !== null && trends.isPending);
  const failure = packs.error ?? trends.error;
  const failedWhat = packs.error ? "pack allowlist" : "trend history";

  return (
    <section className="pb-16">
      <div className="engrave-b flex flex-wrap items-baseline gap-x-6 gap-y-1 px-4 py-3 sm:px-6">
        <h1 className="text-display uppercase tracking-display">Trends</h1>

        <p data-testid="trends-readout" className="text-legend text-chassis-600">
          {reading ? (
            "reading the history…"
          ) : failure ? (
            // Never a count on a failed read: zero is a measurement and the
            // client does not have one.
            "the history could not be read"
          ) : (
            <>
              <span className="tabular-nums text-chassis-900">
                {model.channels.length}
              </span>{" "}
              probes
              <Dot />
              <span className="tabular-nums text-chassis-900">
                {model.readings}
              </span>{" "}
              readings
              <Dot />
              <span className="tabular-nums text-chassis-900">{model.runs}</span>{" "}
              runs
              <Dot />
              {facts.label} — {facts.gloss}
              {model.unplaceable > 0 ? (
                <>
                  <Dot />
                  <span className="tabular-nums text-chassis-900">
                    {model.unplaceable}
                  </span>{" "}
                  unplaceable in time, so not drawn
                </>
              ) : null}
            </>
          )}
        </p>
      </div>

      <div className="engrave-b flex flex-wrap items-center gap-x-8 gap-y-3 px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Legend>Metric</Legend>
          <div className="flex flex-wrap">
            {TREND_METRICS.map((member) => (
              <Detent
                key={member}
                selected={metric === member}
                onClick={() => setMetric(member)}
              >
                {METRIC_FACTS[member].label}
              </Detent>
            ))}
          </div>
        </div>

        <div
          data-testid="trends-pack"
          className="flex flex-wrap items-center gap-x-4 gap-y-2"
        >
          <Legend>Pack</Legend>
          {packNames.length === 0 ? (
            <p className="text-legend text-chassis-600">
              {packs.isPending
                ? "reading the allowlist…"
                : "this server was started with no pack allowlist"}
            </p>
          ) : (
            <div className="flex flex-wrap">
              {packNames.map((name) => (
                <Detent
                  key={name}
                  selected={pack === name}
                  onClick={() => setChosenPack(name)}
                >
                  {name}
                </Detent>
              ))}
            </div>
          )}
        </div>
      </div>

      {failure ? (
        <p
          data-testid="trends-error"
          className="engrave-b flex items-start gap-2 px-4 py-8 text-readout text-chassis-900 sm:px-6"
        >
          {/* The glyph carries the alarm so the message is never colour alone,
              and `status-*` is keyed to RunStatus members — a history that
              cannot be read is not a run state. */}
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {failure instanceof ApiFailure
            ? `The ${failedWhat} could not be read (${failure.code ?? failure.status}): ${failure.message}`
            : "The cockpit could not reach its server. Is `evalyn ui` still running?"}
        </p>
      ) : reading ? (
        // A skeleton, not a spinner: the chart's height is already known, so
        // the page does not jump when the series land.
        //
        // The bar is hidden from the accessibility tree and the sentence is
        // NOT: they were both inside the hidden wrapper, which removes the
        // announcement along with the subtree it sits in — coverage that
        // announced nothing to anybody.
        <div className="px-4 py-4 sm:px-6">
          <div className="h-[340px] bg-chassis-50/60" aria-hidden="true" />
          <span className="sr-only">Reading the trend history…</span>
        </div>
      ) : (
        <>
          <TrendChart
            series={series}
            metric={metric}
            selectedProbeId={selectedProbeId}
          />
          <TrendChannels
            channels={model.channels}
            metric={metric}
            selectedProbeId={selectedProbeId}
            onSelect={setChosenProbe}
          />
        </>
      )}
    </section>
  );
}

/** The readout's separator. Decorative, and announced as nothing. */
function Dot() {
  return (
    <span aria-hidden="true" className="mx-2 text-chassis-400">
      ·
    </span>
  );
}
