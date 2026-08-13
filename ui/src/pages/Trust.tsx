import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ApiFailure, apiGet } from "../api/client";
import type { CriterionCounts, PackListPage, TrustReport } from "../api/types";
import { Detent } from "../components/Detent";
import { Flatline } from "../components/Flatline";
import { IconAlert, IconCheck, IconQuery } from "../components/InstrumentIcon";
import { formatUtc } from "../format";
import { belowThreshold, buildTrustModel } from "../trust";

/**
 * Judge Trust: whether this pack's rubric scores can be believed, and on what
 * evidence.
 *
 * ## The number is ±1-point agreement, and it is never a kappa
 *
 * `calibrate` scores committed anchor transcripts — human-labelled 1-5 per
 * rubric criterion — with the tier-3 rubric judge, and reports the fraction of
 * (anchor x criterion) pairs where the judge landed **within one point** of the
 * human. Nothing computes Cohen's coefficient, nothing corrects for chance
 * agreement, and no word on this page may imply that something did. Naming an
 * uncorrected fraction after a chance-corrected statistic would claim a
 * certification nobody performed, on the one page whose entire subject is
 * whether a measurement can be believed.
 *
 * So the figure is labelled `±1-point agreement`, glossed in the product's own
 * words wherever it appears, and shown beside the count it came from: `100%`
 * over eleven pairs and `100%` over four hundred are different claims and the
 * wire reports them identically.
 *
 * ## `stale` is the headline, because `stale` is the consequence
 *
 * `stale` defaults to `true` and it is not cosmetic: `is_stale` is what the
 * gate consults, and a stale record makes it **refuse tier-3 rubric checks**
 * unless `--allow-uncalibrated` is passed. A record can therefore carry a
 * healthy 93% and still be one nothing will run against. That is invisible
 * unless the page says it where the operator is already looking, so the
 * record's condition is the display-size line and the figure is not: the
 * biggest thing on this page is never a number that may not be in force.
 *
 * ## Never calibrated is the ordinary case, not the edge
 *
 * `packs/twincore` is the only pack here with a `calibration.json`.
 * `packs/twincore-injection` — the demo pack — and `packs/example` have none,
 * and the route answers for them with a legitimate **200 and `agreement:
 * null`**, never a 404. The uncalibrated rendition is therefore what this page
 * usually shows, and it is written as a complete statement with its recovery
 * rather than as a table frame with nothing in it. Nothing is rendered as `0`:
 * zero is a measurement and nobody made one.
 *
 * ## The threshold gates rubrics, and this page marks nothing else
 *
 * `is_stale` compares `AGREEMENT_THRESHOLD` against the overall figure and
 * against **each rubric's own** pooled figure. It never applies it to a single
 * criterion — so `persona:Tone under refusal` sits at 82%, under the 85% bar,
 * inside a record the gate accepts. Marking that criterion as a shortfall would
 * report a failure the engine never declared, which is why the mark lives on
 * the rubric row and on the overall figure and nowhere else.
 *
 * (The mark reads the raw fractions while the cell prints a rounded percent, so
 * a reading of 0.8499 shows `85%` and is still marked. The word carries the
 * truth; the rounding is a display of it.)
 *
 * ## No status ink
 *
 * `status-*` is keyed to `RunStatus` members. A calibration record is not a run
 * state, so nothing here is hued — the same ruling the trends page carries. The
 * condition travels as a glyph and a word, which is what it had to do anyway.
 */

function Legend({ children }: { children: string }) {
  return (
    <h2 className="text-legend uppercase tracking-legend text-chassis-600">
      {children}
    </h2>
  );
}

function Field({
  label,
  testId,
  children,
}: {
  label: string;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <div data-testid={testId} className="py-2">
      <dt className="text-legend uppercase tracking-legend text-chassis-600">
        {label}
      </dt>
      <dd className="mt-1 break-words text-readout text-chassis-900">
        {children}
      </dd>
    </div>
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

/**
 * `0.9318…` -> `93%`.
 *
 * Whole percent is what `calibrate` itself prints, and a second decimal on an
 * eleven-anchor sample is noise dressed as precision. The matched-pair counts
 * beside every figure are the exact record.
 */
function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function pairsOf(counts: CriterionCounts): string {
  return `${counts.hits} / ${counts.total}`;
}

/** The word that carries a shortfall, so no shortfall travels as colour. */
function BelowBar() {
  return (
    <span className="mt-1 block text-legend uppercase tracking-legend text-chassis-900">
      below the bar
    </span>
  );
}

const COLUMNS = [
  { key: "criterion", label: "Criterion", width: "56%" },
  { key: "agreement", label: "Agreement", width: "22%" },
  { key: "pairs", label: "Matched pairs", width: "22%" },
] as const;

export function Trust() {
  const packs = useQuery({
    queryKey: ["packs"],
    queryFn: () => apiGet<PackListPage>("/packs"),
  });

  const [chosenPack, setChosenPack] = useState<string | null>(null);

  // `GET /api/packs` is an envelope, never a bare array, and the list is the
  // start-time allowlist rather than the set of packs with a record.
  const packNames = packs.data?.items.map((row) => row.name) ?? [];
  const pack = chosenPack ?? packNames[0] ?? null;

  const trust = useQuery({
    queryKey: ["trust", pack],
    queryFn: () => {
      const query = new URLSearchParams({ pack: pack! });
      return apiGet<TrustReport>(`/trust?${query.toString()}`);
    },
    enabled: pack !== null,
  });

  const report = trust.data ?? null;
  const model = useMemo(
    () => (report === null ? null : buildTrustModel(report)),
    [report],
  );

  /*
   * Neither read may be reported as a count while it is still in flight: zero
   * is a measurement and the client does not have one. The allowlist read is
   * part of this condition, which is the omission the trends page shipped —
   * every frame before it landed claimed a figure nobody had.
   */
  const reading = packs.isPending || (pack !== null && trust.isPending);
  const failure = packs.error ?? trust.error;
  const failedWhat = packs.error ? "pack allowlist" : "calibration record";

  const record =
    report === null
      ? null
      : report.agreement === null
        ? "absent"
        : report.stale
          ? "stale"
          : "calibrated";

  return (
    <section className="pb-16">
      <div className="engrave-b flex flex-wrap items-baseline gap-x-6 gap-y-1 px-4 py-3 sm:px-6">
        <h1 className="text-display uppercase tracking-display">Judge Trust</h1>

        <p data-testid="trust-readout" className="text-legend text-chassis-600">
          {reading ? (
            "reading the calibration record…"
          ) : failure ? (
            "the calibration record could not be read"
          ) : model === null || record === null ? (
            "nothing to read"
          ) : record === "absent" ? (
            "this pack has never been calibrated"
          ) : (
            <>
              <span className="tabular-nums text-chassis-900">
                {model.criteria}
              </span>{" "}
              {model.criteria === 1 ? "criterion" : "criteria"}
              <Dot />
              {model.pairs === null ? (
                "matched-pair counts not recorded"
              ) : (
                <>
                  <span className="tabular-nums text-chassis-900">
                    {model.pairs.hits}
                  </span>{" "}
                  of{" "}
                  <span className="tabular-nums text-chassis-900">
                    {model.pairs.total}
                  </span>{" "}
                  matched pairs agreed within one point
                </>
              )}
              {model.unmatched.length > 0 ? (
                <>
                  <Dot />
                  <span className="tabular-nums text-chassis-900">
                    {model.unmatched.length}
                  </span>{" "}
                  unmatched
                </>
              ) : null}
            </>
          )}
        </p>
      </div>

      <div
        data-testid="trust-pack"
        className="engrave-b flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6"
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

      {failure ? (
        <p
          data-testid="trust-error"
          className="engrave-b flex items-start gap-2 px-4 py-8 text-readout text-chassis-900 sm:px-6"
        >
          {/* The glyph carries the alarm, so the message is never colour alone,
              and no `status-*` ink enters: a record that cannot be read is not
              a run state. */}
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {failure instanceof ApiFailure
            ? `The ${failedWhat} could not be read (${failure.code ?? failure.status}): ${failure.message}`
            : "The cockpit could not reach its server. Is `evalyn ui` still running?"}
        </p>
      ) : reading ? (
        <p className="px-4 py-8 text-readout text-chassis-600 sm:px-6">
          Reading the calibration record…
        </p>
      ) : report === null || model === null || record === null ? null : (
        <>
          <Verdict report={report} record={record} />
          {record === "absent" ? (
            <NeverCalibrated />
          ) : (
            <>
              <RecordBand report={report} pairs={model.pairs} />
              <CriterionTable
                rubrics={model.rubrics}
                threshold={report.threshold}
              />
            </>
          )}
          {model.unmatched.length > 0 ? (
            <Unmatched ids={model.unmatched} />
          ) : null}
        </>
      )}
    </section>
  );
}

function Verdict({
  report,
  record,
}: {
  report: TrustReport;
  record: "calibrated" | "stale" | "absent";
}) {
  const { Mark, headline, consequence } =
    record === "calibrated"
      ? {
          Mark: IconCheck,
          headline: "Calibrated",
          consequence:
            "The gate runs this pack's rubric checks against this record.",
        }
      : record === "stale"
        ? {
            Mark: IconAlert,
            headline: "Calibration stale",
            consequence:
              "The gate refuses this pack's rubric checks until it is " +
              "recalibrated. `--allow-uncalibrated` runs them anyway and says " +
              "so in the log; the figures below are the last reading taken, " +
              "not a current one.",
          }
        : {
            // Not the cross: the instrument has no answer here, and a negative
            // one would be a different claim. Nothing failed — nothing was
            // measured.
            Mark: IconQuery,
            headline: "Not calibrated",
            consequence:
              "No record has ever been written for this pack, so the gate has " +
              "nothing to trust and will not run its rubric checks.",
          };

  return (
    <section
      data-testid="trust-verdict"
      data-record={record}
      aria-label="Calibration state"
      className="engrave-b rule-major px-4 py-4 sm:px-6"
    >
      <p className="flex items-center gap-2.5 text-display uppercase tracking-display text-chassis-900">
        {/* Glyph AND word. Nothing on this page is hued, so the word is not a
            caption on a colour — it is the whole statement. */}
        <Mark className="h-6 w-6 shrink-0" />
        <span>{headline}</span>
      </p>

      <p className="mt-2 max-w-[70ch] text-readout text-chassis-700">
        {consequence}
      </p>

      {/* Only while the record is actually refused: `is_stale` returns a reason
          in both directions, and printing "calibrated" under a heading that
          already says so is noise. */}
      {report.stale && report.stale_reason !== null ? (
        <p className="mt-3 flex flex-wrap items-baseline gap-x-2 text-legend text-chassis-600">
          <span className="uppercase tracking-legend">Reason</span>
          <span className="text-chassis-900">{report.stale_reason}</span>
        </p>
      ) : null}
    </section>
  );
}

/**
 * The measurement, its bar, and who took it.
 *
 * A definition list rather than a row of tiles: four labelled readings on one
 * continuous face is what an instrument does, and a card apiece would make the
 * judge model look like a metric.
 */
function RecordBand({
  report,
  pairs,
}: {
  report: TrustReport;
  pairs: CriterionCounts | null;
}) {
  const short = belowThreshold(report.agreement, report.threshold);
  return (
    <dl className="engrave-b grid grid-cols-1 gap-x-10 px-4 py-2 sm:grid-cols-2 sm:px-6 lg:grid-cols-4">
      <Field label="±1-point agreement" testId="trust-agreement">
        {report.agreement === null ? (
          <Flatline word="unmeasured" reason="the record carries no overall agreement" />
        ) : (
          <>
            <span className="tabular-nums">{percent(report.agreement)}</span>
            <span className="mt-1 block text-legend text-chassis-600">
              {pairs === null
                ? "matched-pair counts were not recorded"
                : `${pairs.hits} of ${pairs.total} matched pairs landed within one point of the human label`}
            </span>
            {short ? <BelowBar /> : null}
          </>
        )}
      </Field>

      <Field label="Threshold" testId="trust-threshold">
        {report.threshold === null ? (
          <Flatline word="unset" reason="the record names no threshold" />
        ) : (
          <>
            <span className="tabular-nums">{percent(report.threshold)}</span>
            <span className="mt-1 block text-legend text-chassis-600">
              the bar on the overall figure and on each rubric's own — not on a
              single criterion
            </span>
          </>
        )}
      </Field>

      <Field label="Rubric judge">
        {report.judge_model ?? (
          <Flatline word="unrecorded" reason="the record names no judge model" />
        )}
      </Field>

      <Field label="Calibrated (UTC)">
        {report.calibrated_at === null ? (
          <Flatline word="unrecorded" reason="the record carries no timestamp" />
        ) : (
          <span className="tabular-nums">{formatUtc(report.calibrated_at)}</span>
        )}
      </Field>
    </dl>
  );
}

function CriterionTable({
  rubrics,
  threshold,
}: {
  rubrics: ReturnType<typeof buildTrustModel>["rubrics"];
  threshold: number | null;
}) {
  if (rubrics.length === 0) {
    return (
      <p
        data-testid="trust-record-empty"
        className="engrave-b px-4 py-8 text-readout text-chassis-600 sm:px-6"
      >
        This record carries an overall agreement but no per-rubric breakdown, so
        there is nothing to list here.
      </p>
    );
  }

  return (
    // Wide content scrolls inside its own container; the page body never
    // scrolls sideways.
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] table-fixed border-collapse text-left">
        <caption className="sr-only">
          Every criterion the calibration record measured, grouped under its
          rubric, weakest reading first.
        </caption>
        <colgroup>
          {COLUMNS.map((column) => (
            <col key={column.key} style={{ width: column.width }} />
          ))}
        </colgroup>
        <thead>
          {/* No fill — the major rule divides the header, the way every other
              table on this surface does it. A tinted band would be a second
              ground. */}
          <tr className="engrave-b rule-major">
            {COLUMNS.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`whitespace-nowrap py-2 text-legend font-normal uppercase tracking-legend text-chassis-600 ${
                  column.key === "criterion"
                    ? "pl-4 pr-3 sm:pl-6"
                    : column.key === "pairs"
                      ? "pl-3 pr-4 text-right sm:pr-6"
                      : "pr-3 text-right"
                }`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>

        {rubrics.map((rubric) => {
          const short = belowThreshold(rubric.agreement, threshold);
          return (
            <tbody
              key={rubric.rubric}
              data-testid="rubric-group"
              data-rubric={rubric.rubric}
              data-below-threshold={String(short)}
            >
              <tr className="engrave-b rule-major">
                <th
                  scope="rowgroup"
                  className="break-words py-2 pl-4 text-left text-readout font-normal text-chassis-900 sm:pl-6"
                >
                  {/* The column is headed Criterion, and this row is not one —
                      the heavier rule says so on screen and the word says so
                      to a reader that cannot see it. */}
                  <span className="sr-only">Rubric </span>
                  {rubric.rubric}
                </th>
                <td className="py-2 pr-3 text-right align-top">
                  {rubric.agreement === null ? (
                    <Flatline
                      word="unscored"
                      reason="the record carries no agreement for this rubric"
                    />
                  ) : (
                    <>
                      <span className="text-readout tabular-nums text-chassis-900">
                        {percent(rubric.agreement)}
                      </span>
                      {short ? <BelowBar /> : null}
                    </>
                  )}
                </td>
                <td className="py-2 pl-3 pr-4 text-right align-top sm:pr-6">
                  {rubric.pairs === null ? (
                    <Flatline
                      word="unrecorded"
                      reason="no matched-pair counts for this rubric"
                    />
                  ) : (
                    <span className="text-readout tabular-nums text-chassis-700">
                      {pairsOf(rubric.pairs)}
                    </span>
                  )}
                </td>
              </tr>

              {rubric.criteria.length === 0 ? (
                <tr className="engrave-b">
                  <td className="py-2 pl-8 pr-4 sm:pl-10 sm:pr-6" colSpan={3}>
                    <Flatline
                      word="no criteria"
                      reason="this rubric was scored but the record lists no criterion for it"
                    />
                  </td>
                </tr>
              ) : (
                rubric.criteria.map((criterion) => (
                  <tr
                    key={criterion.id}
                    data-testid="criterion-row"
                    data-criterion={criterion.id}
                    className="engrave-b align-top"
                  >
                    <th
                      scope="row"
                      className="break-words py-2 pl-8 pr-3 text-left text-readout font-normal text-chassis-700 sm:pl-10"
                    >
                      {criterion.name}
                    </th>
                    <td className="py-2 pr-3 text-right">
                      {criterion.agreement === null ? (
                        <Flatline
                          word="unscored"
                          reason="the record carries no agreement for this criterion"
                        />
                      ) : (
                        <span className="text-readout tabular-nums text-chassis-900">
                          {percent(criterion.agreement)}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pl-3 pr-4 text-right sm:pr-6">
                      {criterion.counts === null ? (
                        <Flatline
                          word="unrecorded"
                          reason="no matched-pair counts for this criterion"
                        />
                      ) : (
                        <span className="text-readout tabular-nums text-chassis-700">
                          {pairsOf(criterion.counts)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          );
        })}
      </table>
    </div>
  );
}

/**
 * The demo pack's rendition, and the one this page shows most often.
 *
 * A complete statement with its recovery, not a frame with nothing in it: no
 * empty table, no axis, no zeroes, and no illustration. The operator is told
 * what is missing, what follows from it, and the one command that changes it.
 */
function NeverCalibrated() {
  return (
    <div data-testid="trust-absent" className="px-4 py-8 sm:px-6">
      <p className="max-w-[70ch] text-readout text-chassis-900">
        The rubric judge has never been scored against this pack's human-labelled
        anchors, so there is no agreement to report — and nothing here is shown
        as zero, because zero would be a measurement nobody took.
      </p>

      <p className="mt-6 text-legend uppercase tracking-legend text-chassis-600">
        Writing the record
      </p>
      <p className="mt-1 text-readout text-chassis-900">
        <code>evalyn calibrate --target &lt;pack&gt;</code>
      </p>
      <p className="mt-2 max-w-[70ch] text-legend text-chassis-600">
        It scores the pack's anchor transcripts with the rubric judge and records
        ±1-point agreement against the human labels — overall, per rubric and per
        criterion. That record is what this page reads.
      </p>
    </div>
  );
}

/**
 * Criteria the rubric declares that the record never matched.
 *
 * Named rather than dropped: they are the difference between "eight criteria
 * measured" and "eight of nine", and a page that silently lists only what was
 * measured overstates its own coverage.
 */
function Unmatched({ ids }: { ids: readonly string[] }) {
  return (
    <div
      data-testid="trust-unmatched"
      className="engrave-t rule-major px-4 py-4 sm:px-6"
    >
      <Legend>Unmatched criteria</Legend>
      <p className="mt-1 max-w-[70ch] text-legend text-chassis-600">
        Declared by the rubric and matched by no anchor label, so nothing above
        measures them and they are outside every figure on this page.
      </p>
      <ul className="mt-2 space-y-1">
        {ids.map((id) => (
          <li key={id} className="break-words text-readout text-chassis-900">
            {id}
          </li>
        ))}
      </ul>
    </div>
  );
}
