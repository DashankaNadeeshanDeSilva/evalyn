import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiFailure, apiGet, useRunDetail } from "../api/client";
import type { RunListPage, RunSummary, Scoreboard } from "../api/types";
import {
  ADVISORY,
  DELTA_LEGEND,
  buildCompareModel,
  formatDelta,
  formatFlipRate,
  formatValue,
  type MetricBlock,
  type VerdictRow,
} from "../compare";
import { Detent } from "../components/Detent";
import { Flatline } from "../components/Flatline";
import { IconAlert } from "../components/InstrumentIcon";
import { formatUsd, formatUtc } from "../format";

/**
 * Compare: two runs of one pack, side by side, with nothing collapsed.
 *
 * ## Two halves, and one of them is often empty on purpose
 *
 * A compare board has a **verdict** half (what the judge said about
 * rubric-checked probes, pair by pair) and a **hard-metric** half (latency and
 * invariant counts, straight off the trial records). They are drawn as two
 * regions rather than one table because they are two different kinds of claim,
 * measured by two different mechanisms, and the product's whole position is
 * that they are never fused into a score.
 *
 * `run_compare` judges only probes that carry a rubric check, so a pack with
 * none produces a board whose verdict half is **genuinely empty** while its
 * hard-metric half is fully measured. That is the shape of the only compare
 * artifact in `runs/` today. The empty half is a first-class state here: it
 * says why it is empty, and it never borrows the vocabulary of a failure, a
 * skip or a load in flight — the model layer owns that sentence so a test can
 * pin it.
 *
 * ## Where the board comes from
 *
 * `GET /api/runs/{id}` -> `RunDetail.compare`, via `useRunDetail`. There is no
 * `/api/compare/{id}` route on the server and there never has been, whatever
 * `models.py`, `types.ts` and the MSW handler say — a page built against that
 * route is green in vitest and dead in `evalyn ui`.
 *
 * The index read beside it (`/api/runs?mode=compare`) is what fills the board
 * selector. Only the first page is read: a directory with more compare runs
 * than one page says so rather than pretending the list is complete.
 *
 * ## Nothing on this page ranks anything
 *
 * No overall winner, no score, no recommendation — `models.py` refuses the
 * field, the engine prints the refusal in its own report, and the difference
 * column here is subtraction with its arithmetic stated beside it.
 */

function Legend({ children }: { children: string }) {
  return (
    <h2 className="text-legend uppercase tracking-legend text-chassis-600">
      {children}
    </h2>
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

/** A failed read, said with a glyph so it is never colour alone. */
function Failure({ what, error }: { what: string; error: unknown }) {
  return (
    <p
      data-testid="compare-error"
      className="engrave-b flex max-w-[74ch] items-start gap-2 px-4 py-8 text-readout text-chassis-900 sm:px-6"
    >
      <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
      {error instanceof ApiFailure
        ? `The ${what} could not be read (${error.code ?? error.status}): ${error.message}`
        : "The cockpit could not reach its server. Is `evalyn ui` still running?"}
    </p>
  );
}

export function Compare() {
  /*
   * The index, filtered to compare runs. `apiGet` inside `useQuery` is the
   * page pattern here; the infinite-query hook exists for the runs table's
   * "load older" key, and this selector has no such key — it states the
   * truncation instead.
   */
  const runs = useQuery({
    queryKey: ["runs", "compare", null],
    queryFn: () => apiGet<RunListPage>("/runs?mode=compare"),
  });

  const [chosen, setChosen] = useState<string | null>(null);

  const rows: RunSummary[] = runs.data?.items ?? [];
  // Derived, never stored in an effect: the operator's choice wins while it
  // still names a board that exists, and the newest board is the fallback.
  const selected =
    rows.find((row) => row.run_id === chosen)?.run_id ?? rows[0]?.run_id ?? null;

  return (
    <section className="pb-16">
      <div className="engrave-b flex flex-wrap items-baseline gap-x-6 gap-y-1 px-4 py-3 sm:px-6">
        <h1 className="text-display uppercase tracking-display">Compare</h1>
        <p className="text-legend text-chassis-600">
          two runs of one pack, judged pair by pair and measured trial by trial
        </p>
      </div>

      {rows.length > 0 ? (
        <div
          data-testid="compare-boards"
          className="engrave-b flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6"
        >
          <Legend>Board</Legend>
          <div className="flex flex-wrap">
            {rows.map((row) => (
              <Detent
                key={row.run_id}
                selected={row.run_id === selected}
                onClick={() => setChosen(row.run_id)}
              >
                {formatUtc(row.created_at)}
              </Detent>
            ))}
          </div>
          {runs.data?.next_cursor !== null ? (
            <p className="text-legend text-chassis-600">
              older boards exist and are not listed here
            </p>
          ) : null}
        </div>
      ) : null}

      {runs.isPending ? (
        <p className="px-4 py-8 text-readout text-chassis-600 sm:px-6">
          reading the index…
        </p>
      ) : runs.error ? (
        <Failure what="run index" error={runs.error} />
      ) : selected === null ? (
        <div
          data-testid="compare-none"
          className="max-w-[74ch] px-4 py-8 text-readout text-chassis-600 sm:px-6"
        >
          <p className="text-chassis-900">
            This runs directory holds no compare runs.
          </p>
          <p className="mt-2">
            `evalyn compare --a &lt;run&gt; --b &lt;run&gt;` writes one, and it
            appears here. The cockpit indexes what is on disk; it has nothing to
            draw until a comparison has been made.
          </p>
        </div>
      ) : (
        <Board runId={selected} />
      )}
    </section>
  );
}

/**
 * One board, read off `RunDetail.compare`.
 *
 * A component rather than a branch so `useRunDetail` is never called with a
 * run id that does not exist — an empty index must ask the server nothing.
 */
function Board({ runId }: { runId: string }) {
  const detail = useRunDetail(runId);

  if (detail.isPending) {
    return (
      <p className="px-4 py-8 text-readout text-chassis-600 sm:px-6">
        reading the board…
      </p>
    );
  }
  if (detail.error) return <Failure what="compare run" error={detail.error} />;

  const board = detail.data.compare;
  if (!board) {
    return (
      <p
        data-testid="compare-unreadable"
        className="max-w-[74ch] px-4 py-8 text-readout text-chassis-600 sm:px-6"
      >
        This run is a comparison but carries no scoreboard.{" "}
        {detail.data.degraded_reason ??
          "The artifact was read, and the compare section was not in it."}
      </p>
    );
  }

  return <BoardFace runId={runId} board={board} />;
}

function BoardFace({ runId, board }: { runId: string; board: Scoreboard }) {
  const model = buildCompareModel(board);

  return (
    <div data-testid="compare-board">
      <p
        data-testid="compare-readout"
        className="engrave-b px-4 py-3 text-legend text-chassis-600 sm:px-6"
      >
        <span className="break-all text-chassis-900">{runId}</span>
        <Dot />
        {board.pack_name ?? "pack not recorded"}
        <Dot />
        {formatUtc(board.created_at)}
        <Dot />
        {board.judge_usd === null ? (
          "judge spend unrecorded"
        ) : (
          <>
            judge spend{" "}
            <span className="tabular-nums text-chassis-900">
              {formatUsd(board.judge_usd)}
            </span>
          </>
        )}
        <Dot />
        <span className="tabular-nums text-chassis-900">
          {model.criteriaJudged}
        </span>{" "}
        {model.criteriaJudged === 1 ? "criterion" : "criteria"} judged
        {board.redacted ? (
          <>
            <Dot />
            {/* Driven off the flag, never off marker text in a field. */}
            values on this board passed through the redactor
          </>
        ) : null}
      </p>

      <div
        data-testid="compare-sides"
        className="engrave-b grid gap-x-10 gap-y-4 px-4 py-3 sm:grid-cols-2 sm:px-6"
      >
        <Side
          side="A"
          label={board.label_a}
          createdAt={board.created_at_a}
          source={board.source_a}
        />
        <Side
          side="B"
          label={board.label_b}
          createdAt={board.created_at_b}
          source={board.source_b}
        />
      </div>

      {board.rubric_scores_untrusted ? (
        <p
          data-testid="compare-untrusted"
          className="engrave-b flex items-start gap-2 px-4 py-3 text-readout text-chassis-900 sm:px-6"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="max-w-[74ch]">
            Rubric scores are untrusted: this comparison was judged against a
            stale calibration, so the verdicts below rest on agreement nobody
            re-measured. Judge Trust reports what the judge was last measured at.
          </span>
        </p>
      ) : null}

      <Verdicts model={model} />
      <Metrics model={model} />

      <p
        data-testid="compare-advisory"
        className="max-w-[74ch] px-4 py-4 text-legend text-chassis-600 sm:px-6"
      >
        {ADVISORY}
      </p>
    </div>
  );
}

function Side({
  side,
  label,
  createdAt,
  source,
}: {
  side: string;
  label: string;
  createdAt: string | null;
  source: string | null;
}) {
  return (
    <div>
      <h2 className="text-legend uppercase tracking-legend text-chassis-600">
        {side}
      </h2>
      <p className="mt-1 break-words text-readout text-chassis-900">{label}</p>
      <p className="mt-0.5 text-legend text-chassis-600">
        {createdAt === null ? "run time not recorded" : formatUtc(createdAt)}
        <Dot />
        {/* A CLI-given path, which the redactor may have replaced wholesale.
            It is shown because "which artifact was this?" has no other answer
            on the board, and it wraps because a scrubbed marker is long. */}
        <span className="break-all">{source ?? "source not recorded"}</span>
      </p>
    </div>
  );
}

const VERDICT_COLUMNS = [
  "Category",
  "A wins",
  "B wins",
  "Ties",
  "Unsure",
  "Flips",
  "Flip rate",
  "Criteria judged",
];

function Verdicts({ model }: { model: ReturnType<typeof buildCompareModel> }) {
  return (
    <section data-testid="compare-verdicts" className="engrave-b rule-major">
      <div className="px-4 pt-4 sm:px-6">
        <Legend>Pairwise verdicts</Legend>
        <p className="mt-1 max-w-[74ch] text-legend text-chassis-600">
          each rubric criterion judged twice, in both orders — a flip is the
          judge disagreeing with itself when the sides were swapped
        </p>
      </div>

      {model.verdictAbsence === null ? (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[48rem] border-collapse text-left">
            <caption className="sr-only">
              Per-category verdict tallies. Advisory, and never combined with
              the hard metrics below.
            </caption>
            <thead>
              <tr className="engrave-b">
                {VERDICT_COLUMNS.map((column, index) => (
                  <th
                    key={column}
                    scope="col"
                    className={`whitespace-nowrap py-2 text-legend font-normal uppercase tracking-legend text-chassis-600 ${
                      index === 0 ? "pl-4 pr-3 sm:pl-6" : "pr-3 text-right"
                    } ${index === VERDICT_COLUMNS.length - 1 ? "sm:pr-6" : ""}`}
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {model.verdicts.map((row) => (
                <VerdictCells key={row.category} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p
          data-testid="compare-verdicts-empty"
          className="mt-3 max-w-[74ch] px-4 pb-4 text-readout text-chassis-700 sm:px-6"
        >
          {model.verdictAbsence}
        </p>
      )}

      {model.exclusion === null ? null : (
        <p className="max-w-[74ch] px-4 py-3 text-legend text-chassis-600 sm:px-6">
          {model.exclusion} An excluded pair is one the judge was never asked
          about, so it is in no tally above.
        </p>
      )}
    </section>
  );
}

function VerdictCells({ row }: { row: VerdictRow }) {
  const figures = [
    row.winsA,
    row.winsB,
    row.ties,
    row.unsure,
    row.flips,
  ] as const;

  return (
    <tr
      data-testid={`verdict-row-${row.category}`}
      className="engrave-b last:border-b-0"
    >
      <td className="py-2 pl-4 pr-3 text-readout text-chassis-900 sm:pl-6">
        {row.category}
      </td>
      {figures.map((figure, index) => (
        <td
          key={VERDICT_COLUMNS[index + 1]}
          className="whitespace-nowrap py-2 pr-3 text-right text-readout tabular-nums text-chassis-900"
        >
          {figure}
        </td>
      ))}
      <td className="whitespace-nowrap py-2 pr-3 text-right text-readout tabular-nums text-chassis-700">
        {formatFlipRate(row.flipRate)}
      </td>
      <td className="whitespace-nowrap py-2 pr-3 text-right text-readout tabular-nums text-chassis-700 sm:pr-6">
        {row.criteriaJudged}
      </td>
    </tr>
  );
}

function Metrics({ model }: { model: ReturnType<typeof buildCompareModel> }) {
  return (
    <section data-testid="compare-metrics">
      <div className="px-4 pt-4 sm:px-6">
        <Legend>Hard metrics</Legend>
        <p className="mt-1 max-w-[74ch] text-legend text-chassis-600">
          from the trial records only, never blended with the verdicts above.{" "}
          {DELTA_LEGEND}
        </p>
      </div>

      {model.metricAbsence === null ? (
        model.metrics.map((block) => <MetricTable key={block.category} block={block} />)
      ) : (
        <p
          data-testid="compare-metrics-empty"
          className="mt-3 max-w-[74ch] px-4 pb-4 text-readout text-chassis-700 sm:px-6"
        >
          {model.metricAbsence}
        </p>
      )}
    </section>
  );
}

const METRIC_COLUMNS = ["Measurement", "A", "B", "B − A"];

function MetricTable({ block }: { block: MetricBlock }) {
  return (
    <div
      data-testid={`metric-block-${block.category}`}
      className="engrave-b px-4 py-3 sm:px-6"
    >
      <h3 className="text-legend uppercase tracking-legend text-chassis-900">
        {block.category}
      </h3>
      <div className="mt-1 overflow-x-auto">
        <table className="w-full min-w-[28rem] max-w-[46rem] border-collapse text-left">
          <caption className="sr-only">
            Hard metrics for the {block.category} category, A beside B.
          </caption>
          <thead>
            <tr className="engrave-b">
              {METRIC_COLUMNS.map((column, index) => (
                <th
                  key={column}
                  scope="col"
                  className={`whitespace-nowrap py-2 pr-3 text-legend font-normal uppercase tracking-legend text-chassis-600 ${
                    index === 0 ? "" : "text-right"
                  }`}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row) => (
              <tr
                key={row.key}
                data-testid={`metric-row-${block.category}-${row.key}`}
                className="engrave-b last:border-b-0"
              >
                <td className="py-2 pr-3 text-readout text-chassis-900">
                  {row.label}
                </td>
                <td className="whitespace-nowrap py-2 pr-3 text-right text-readout tabular-nums text-chassis-900">
                  <Reading value={row.a} unit={row.unit} absence={row.absence} />
                </td>
                <td className="whitespace-nowrap py-2 pr-3 text-right text-readout tabular-nums text-chassis-900">
                  <Reading value={row.b} unit={row.unit} absence={row.absence} />
                </td>
                <td className="whitespace-nowrap py-2 pr-3 text-right text-readout tabular-nums text-chassis-700">
                  {row.delta === null ? (
                    <Flatline
                      variant="n/a"
                      word="no difference"
                      reason="a difference needs both sides, and one of them was never recorded"
                    />
                  ) : (
                    formatDelta(row.delta, row.unit)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** One measured value, or the stated absence of one. Never a zero standing in. */
function Reading({
  value,
  unit,
  absence,
}: {
  value: number | null;
  unit: MetricBlock["rows"][number]["unit"];
  absence: string;
}) {
  if (value === null) return <Flatline word="unrecorded" reason={absence} />;
  return <>{formatValue(value, unit)}</>;
}
