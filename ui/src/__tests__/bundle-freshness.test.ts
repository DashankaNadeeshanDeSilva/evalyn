import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { shippedDestinations } from "../nav";

/**
 * The bundle-staleness guard.
 *
 * `evalyn ui` serves a **committed, pre-built** bundle out of
 * `src/evalyn/ui/static/`. The source of truth is `ui/src/**`; the served
 * artifact only changes when somebody runs `npm run build`. Those two have
 * drifted four separate times here — a page written, tested green and merged,
 * with the browser still serving the previous bundle — and the entire UI suite
 * passes in that state, because every other test imports the *source*. This
 * file is the only one that reads the *artifact*.
 *
 * Two properties are load-bearing, and both were measured against the committed
 * bundle rather than assumed:
 *
 * - **Comments do not survive minification.** Strings that exist only in source
 *   prose read zero after a perfect build, so a probe keyed to one reports
 *   staleness that isn't there. `data-testid` *values* are runtime strings and
 *   do survive — verified: all six markers below are present in the bundle as
 *   committed, while comment-only phrases from the same files are absent.
 * - **The delimiters are not double quotes.** This bundle's minifier emits
 *   string literals in backticks (`"data-testid":` + backtick + value), so a
 *   search for the double-quoted value reads zero after a perfect build — the
 *   same false alarm in a different costume. The marker is matched delimited by
 *   any of the three JS quote characters, which also stops `compare-board` from
 *   being satisfied by `compare-boards`.
 *
 * The map is driven off `shippedDestinations()`, never a hand-written six, so a
 * seventh page reds here until someone maps it.
 */
const PAGE_MARKERS: Readonly<Record<string, string>> = {
  "/runs": "runs-page",
  "/launch": "launch-refusal",
  "/discoveries": "discoveries-bench",
  "/compare": "compare-boards",
  "/trends": "trends-readout",
  "/trust": "trust-readout",
};

/**
 * `EVALYN_BUNDLE_DIR` exists so this guard can be *calibrated* — pointed at a
 * copy of the bundle with one page's markers removed — without ever mutating
 * the committed artifact. Unset in every normal run.
 */
// `fileURLToPath` is handed a *string*: under the jsdom environment the global
// `URL` is whatwg-url's, and node rejects that object as "not of scheme file".
const bundleDir =
  process.env.EVALYN_BUNDLE_DIR ??
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../../../src/evalyn/ui/static/assets",
  );

const bundle = readdirSync(bundleDir)
  .filter((entry) => entry.endsWith(".js"))
  .map((entry) => readFileSync(join(bundleDir, entry), "utf8"))
  .join("\n");

/**
 * Occurrences, never lines: the bundle is minified onto a handful of lines, so
 * any line-based count is meaningless. An unmapped destination counts zero
 * rather than searching for the string `undefined`, which the bundle contains.
 */
function occurrences(marker: string | undefined): number {
  if (marker === undefined) return 0;
  return bundle.match(new RegExp(`["'\`]${marker}["'\`]`, "g"))?.length ?? 0;
}

describe("the committed bundle", () => {
  it("maps a page marker for every shipped destination", () => {
    const unmapped = shippedDestinations()
      .map((destination) => destination.path)
      .filter((path) => !(path in PAGE_MARKERS));

    expect(
      unmapped,
      `unmapped shipped destination(s): ${unmapped.join(", ")}. Add a page-unique data-testid from that page's source to PAGE_MARKERS.`,
    ).toEqual([]);
  });

  it.each(shippedDestinations().map((destination) => destination.path))(
    "still carries the page served at %s",
    (path) => {
      const marker = PAGE_MARKERS[path];

      // Measured, not assumed: an unmapped destination yields `undefined`, and
      // `"undefined"` genuinely occurs quoted in the bundle — so without this
      // line the per-page assertion goes *green* for a page nobody mapped.
      expect(
        marker,
        `no page marker mapped for ${path}. Add a page-unique data-testid from that page's source to PAGE_MARKERS.`,
      ).toBeTypeOf("string");

      expect(
        occurrences(marker),
        `the committed bundle has no trace of ${path} (marker "${marker}"). The served bundle is stale: rebuild it with \`cd ui && npm run build\` and commit the result.`,
      ).toBeGreaterThan(0);
    },
  );
});
