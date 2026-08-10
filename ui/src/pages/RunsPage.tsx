import { useMemo } from "react";

import { ApiFailure, useRuns } from "../api/client";
import { RunsTable } from "../components/RunsTable";

/**
 * The runs list — the cockpit's ground floor.
 *
 * Every number on this page is derived from what the server actually returned.
 * Ruling R4-6: the run count changes whenever an eval runs, so a literal
 * anywhere — component, test or assertion — is wrong on the day it is written.
 * The readout says "loaded", not "total", because with a cursor open the client
 * genuinely does not know the total and must not imply that it does.
 */
export function RunsPage() {
  const runs = useRuns();

  const rows = useMemo(
    () => runs.data?.pages.flatMap((page) => page.items) ?? [],
    [runs.data],
  );
  const degradedCount = rows.filter((row) => row.degraded).length;

  return (
    <section className="pb-16">
      <div className="engrave-b flex flex-wrap items-baseline gap-x-6 gap-y-1 px-4 py-3 sm:px-6">
        <h1 className="text-panel uppercase">Runs</h1>

        <p className="text-legend tracking-normal text-chassis-600">
          {runs.isPending ? (
            "reading the index…"
          ) : runs.isError ? (
            // Never "0 loaded" on a failed read: zero is a measurement, and
            // the client does not have one. Say what is actually true.
            "the index could not be read"
          ) : (
            <>
              <span className="tabular-nums text-chassis-900">
                {rows.length}
              </span>{" "}
              loaded
              {runs.hasNextPage ? ", more available" : ""}
              <span aria-hidden="true" className="mx-2 text-chassis-400">
                ·
              </span>
              <span className="tabular-nums text-chassis-900">
                {degradedCount}
              </span>{" "}
              degraded
            </>
          )}
        </p>

        {/* The runs directory is deliberately NOT repeated here: the legend
            strip carries it a few pixels above, and two copies of the same
            label in one viewport is noise, not reassurance. */}
      </div>

      {runs.isError ? (
        <p className="engrave-b px-4 py-8 text-readout text-status-unreadable sm:px-6">
          {runs.error instanceof ApiFailure
            ? `The index could not be read (${runs.error.code ?? runs.error.status}): ${runs.error.message}`
            : "The cockpit could not reach its server. Is `evalyn ui` still running?"}
        </p>
      ) : runs.isPending ? (
        // A skeleton, not a spinner: the columns are already known, so the
        // layout does not jump when the rows land.
        <div className="px-4 py-4 sm:px-6" aria-hidden="true">
          {[0, 1, 2, 3, 4, 5].map((slot) => (
            <div key={slot} className="engrave-b h-9 bg-chassis-50/60" />
          ))}
          <span className="sr-only">Reading the run index…</span>
        </div>
      ) : (
        <RunsTable runs={rows} />
      )}

      {runs.hasNextPage ? (
        <div className="px-4 py-4 sm:px-6">
          <button
            type="button"
            onClick={() => void runs.fetchNextPage()}
            disabled={runs.isFetchingNextPage}
            className="border border-chassis-400 px-4 py-1.5 text-legend uppercase text-chassis-900 transition-colors duration-detent hover:bg-chassis-100 disabled:cursor-not-allowed disabled:border-chassis-300 disabled:text-chassis-500"
          >
            {runs.isFetchingNextPage ? "Loading…" : "Load older runs"}
          </button>
        </div>
      ) : null}
    </section>
  );
}
