/**
 * Readout formatting. The server sends values verbatim; the SPA formats.
 *
 * Everything here is locale-independent on purpose. An instrument reads the
 * same on every bench, and `toLocaleString` would make the same artifact render
 * differently depending on who opened it — and would make these values
 * un-assertable in a test.
 */

/**
 * `2026-08-04T08:15:44.953115+00:00` -> `2026-08-04 08:15:44Z`.
 *
 * Sub-second precision is real (it is what makes two runs in the same second
 * distinguishable) but it belongs in the `run_id`, not in a scan column.
 *
 * An unparseable stamp returns verbatim rather than `Invalid Date`: on a
 * degraded artifact `created_at` was recovered from the filename, and showing
 * the operator what was actually recovered beats showing them a JavaScript
 * error message.
 */
export function formatUtc(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return `${at.toISOString().slice(0, 19).replace("T", " ")}Z`;
}

/**
 * Evalyn's own judge spend, to four decimals.
 *
 * Four, not two, and the reason is Product Principle 4 — be honest about cost.
 * These are sub-dollar figures: a run that spent $0.0042 rendered to cents is
 * `$0.00`, which reads as "free" and is a lie the interface must not tell. A
 * fixed decimal count is also what keeps the column from jittering between
 * renders, which two decimals plus an occasional four would not.
 *
 * `null` is not zero — it means the artifact cannot tell you — so it never
 * reaches this function; the caller flat-lines the cell instead.
 */
export function formatUsd(value: number): string {
  return `$${value.toFixed(4)}`;
}
