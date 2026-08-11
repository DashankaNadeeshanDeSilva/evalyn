/**
 * MSW handlers for every route in the frozen contract.
 *
 * This is the seam that lets Tasks 8, 9, 15, 16 and 17 build real pages before
 * the Python endpoints exist. It is a **mock of the contract, not a convenience
 * stub**: it reproduces the behaviours a page can get wrong.
 *
 * - Errors are the `ErrorEnvelope` shape, always — including for a bad path
 *   parameter, which the real server answers `not_found` (the resource cannot
 *   exist, and saying so leaks nothing about the filesystem).
 * - `/api/runs` paginates with the opaque `(created_at, run_id)` cursor and
 *   compares the *parsed tuples*, never the joined strings.
 * - `/api/discoveries/{probe_id}` is redacted unless the request carries the
 *   `X-Evalyn-Reveal` token.
 * - `/api/runs/{id}/trials/...` 404s on the legacy artifact, because it has no
 *   trial records — a page that offered the drill-down anyway read truthiness
 *   instead of `capabilities.trial_records`, and this is where it finds out.
 *
 * Cursors are *constructed* here only because this file is standing in for the
 * server. Application code must never build one.
 */

import { http, HttpResponse } from "msw";

import {
  CURSOR_SEPARATOR,
  isRunId,
  parseCursor,
  type ControlResponse,
  type DiscoveryListPage,
  type ErrorCode,
  type ErrorEnvelope,
  type FindingRow,
  type LaunchResponse,
  type PackAxes,
  type PackListPage,
  type RunListPage,
  type RunSummary,
  type ValidationReport,
} from "../api/types";
import {
  FINDING_DETAIL,
  FINDING_DETAIL_REVEALED,
  FINDING_ROWS,
  GATE_VERDICT,
  HEALTH,
  META,
  PACK_AXES,
  PACKS,
  RUN_DETAILS,
  RUN_ID_GATE,
  RUN_SUMMARIES,
  SCOREBOARD,
  TREND_SERIES,
  TRIAL_VIEW,
  TRUST_NEVER_CALIBRATED,
  TRUST_REPORT,
  VALIDATION_REPORT,
} from "./fixtures";

/** Page size, deliberately smaller than the corpus so pagination is exercised. */
export const MOCK_PAGE_SIZE = 3;

const STATUS_FOR: Record<ErrorCode, number> = {
  not_found: 404,
  unreadable_artifact: 500,
  pack_error: 400,
  launch_refused: 400,
  busy: 409,
};

function fail(code: ErrorCode, message: string, detail: string | null = null) {
  const body: ErrorEnvelope = { error: { code, message, detail } };
  return HttpResponse.json(body, { status: STATUS_FOR[code] });
}

/** Ordering key for a row, matching `models.parse_cursor`'s tuple. */
function key(row: RunSummary): [string, string] {
  return [row.created_at, row.run_id];
}

/**
 * The same, for a finding. Both halves are nullable on `FindingRow` — a row
 * salvaged without its run has neither — and an empty string sorts first under
 * the descending order, which is where an unattributable row belongs.
 */
function findingKey(row: FindingRow): [string, string] {
  return [row.created_at ?? "", row.run_id ?? ""];
}

/**
 * The refusal for a `?before=` that fails its grammar. Shared by both
 * paginated routes so they cannot drift into two different rejections: the
 * real server answers `not_found` for a bad query parameter, not a 422 — the
 * resource cannot exist, and saying so leaks nothing about the filesystem.
 */
function badCursor() {
  return fail(
    "not_found",
    "invalid cursor",
    `?before= must be the opaque '<created_at>${CURSOR_SEPARATOR}<run_id>' composite`,
  );
}

/** Descending tuple comparison. Never compares the joined cursor strings. */
function isBefore(a: [string, string], b: [string, string]): boolean {
  if (a[0] !== b[0]) return a[0] < b[0];
  return a[1] < b[1];
}

export const handlers = [
  // -------------------------------------------------------------------------
  // Server meta — the two routes exempt from the redaction chokepoint
  // -------------------------------------------------------------------------

  http.get("/api/meta", () => HttpResponse.json(META)),
  http.get("/api/health", () => HttpResponse.json(HEALTH)),

  // -------------------------------------------------------------------------
  // Runs
  // -------------------------------------------------------------------------

  http.get("/api/runs", ({ request }) => {
    const url = new URL(request.url);
    const mode = url.searchParams.get("mode");
    const pack = url.searchParams.get("pack");
    const before = url.searchParams.get("before");

    let rows = [...RUN_SUMMARIES];
    if (mode) rows = rows.filter((r) => r.mode === mode);
    if (pack) rows = rows.filter((r) => r.pack_name === pack);

    if (before !== null) {
      let cursor: [string, string];
      try {
        cursor = parseCursor(before);
      } catch {
        // The real server rejects the tie-unsafe bare-timestamp form.
        return badCursor();
      }
      rows = rows.filter((r) => isBefore(key(r), cursor));
    }

    const page = rows.slice(0, MOCK_PAGE_SIZE);
    const last = page[page.length - 1];
    const more = rows.length > page.length;
    const body: RunListPage = {
      items: page,
      next_cursor:
        more && last ? `${last.created_at}${CURSOR_SEPARATOR}${last.run_id}` : null,
    };
    return HttpResponse.json(body);
  }),

  http.get("/api/runs/:runId", ({ params }) => {
    const runId = String(params["runId"]);
    if (!isRunId(runId)) return fail("not_found", `no such run: ${runId}`);
    const detail = RUN_DETAILS[runId];
    if (!detail) return fail("not_found", `no such run: ${runId}`);
    return HttpResponse.json(detail);
  }),

  http.get("/api/runs/:runId/gate", ({ params }) => {
    const runId = String(params["runId"]);
    const detail = RUN_DETAILS[runId];
    if (!detail) return fail("not_found", `no such run: ${runId}`);
    if (detail.mode !== "gate") {
      return fail("not_found", `run ${runId} is not a gate run`);
    }
    return HttpResponse.json({ ...GATE_VERDICT, run_id: runId });
  }),

  // Markdown, not JSON — the SPA renders it, so it must not be double-encoded.
  http.get("/api/runs/:runId/report", ({ params }) => {
    const runId = String(params["runId"]);
    if (!RUN_DETAILS[runId]) return fail("not_found", `no such run: ${runId}`);
    return HttpResponse.text(GATE_VERDICT.report_md, {
      headers: { "Content-Type": "text/markdown; charset=utf-8" },
    });
  }),

  http.get("/api/runs/:runId/stderr", ({ params }) => {
    const runId = String(params["runId"]);
    if (!RUN_DETAILS[runId]) return fail("not_found", `no such run: ${runId}`);
    return HttpResponse.text(
      "evalyn: gate: 2 probes, 6 trials\nevalyn: gate: FAIL\n",
      { headers: { "Content-Type": "text/plain; charset=utf-8" } },
    );
  }),

  http.get("/api/runs/:runId/trials/:probeId/:epoch", ({ params }) => {
    const runId = String(params["runId"]);
    const detail = RUN_DETAILS[runId];
    if (!detail) return fail("not_found", `no such run: ${runId}`);
    // The legacy artifact has no trial records. A 404 here is a *bug* in the
    // caller — `capabilities.trial_records` said so before the click.
    if (!detail.capabilities.trial_records) {
      return fail(
        "not_found",
        "this artifact has no trial records",
        "capabilities.trial_records is false — the drill-down should be disabled",
      );
    }
    return HttpResponse.json({
      ...TRIAL_VIEW,
      run_id: runId,
      probe_id: String(params["probeId"]),
      epoch: Number(params["epoch"]),
    });
  }),

  /**
   * SSE. Emits a short scripted run and closes on `run.finished`, so a test
   * that forgets to unsubscribe still terminates. The `id:` field is the
   * sequence number a `Last-Event-ID` resume skips past.
   */
  http.get("/api/runs/:runId/events", () => {
    const script: [string, unknown][] = [
      ["run.started", { run_id: RUN_ID_GATE, mode: "gate", pack: "example" }],
      ["trial.started", { probe_id: "grounding-work-history", epoch: 1 }],
      ["turn.sent", { probe_id: "grounding-work-history", epoch: 1, turn: 1 }],
      ["turn.received", { probe_id: "grounding-work-history", epoch: 1, turn: 1 }],
      ["probe.scored", { probe_id: "grounding-work-history", pass_k: 1.0 }],
      ["spend.updated", { judge_usd: 0.01377 }],
      ["artifact.written", { run_id: RUN_ID_GATE }],
      ["run.finished", { run_id: RUN_ID_GATE, exit_code: 1 }],
    ];
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        script.forEach(([event, data], i) => {
          controller.enqueue(
            encoder.encode(
              `id: ${i + 1}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
            ),
          );
        });
        controller.close();
      },
    });
    return new HttpResponse(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  }),

  /**
   * Launch. Mirrors the two refusals that matter: `confirm` must echo the
   * pack's name, and `pack_id` must be in the start-time allowlist. A body
   * carrying a pack *path* is rejected by `extra="forbid"` upstream of any
   * handler, which is why nothing here looks for one.
   */
  http.post("/api/runs", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    const pack = PACKS.find((p) => p.id === body["pack_id"]);
    if (!pack) {
      return fail("launch_refused", "unknown pack_id", "not in the --target allowlist");
    }
    if (body["confirm"] !== pack.name) {
      return fail(
        "launch_refused",
        "confirm must equal the pack name",
        `expected ${JSON.stringify(pack.name)}`,
      );
    }
    if (body["mode"] === "discover" && !META.allow_discover) {
      return fail("launch_refused", "discover requires --allow-discover");
    }
    const launched: LaunchResponse = { run_id: RUN_ID_GATE };
    return HttpResponse.json(launched, { status: 202 });
  }),

  /**
   * Control. The 202 is NOT the acknowledgement — the matching `control.*` SSE
   * event is. A UI that flips state off this response is wrong.
   */
  http.post("/api/runs/:runId/control", ({ params }) => {
    const runId = String(params["runId"]);
    if (!RUN_DETAILS[runId]) return fail("not_found", `no such run: ${runId}`);
    const body: ControlResponse = { run_id: runId, accepted: true };
    return HttpResponse.json(body, { status: 202 });
  }),

  // -------------------------------------------------------------------------
  // Packs
  // -------------------------------------------------------------------------

  // An envelope, not a bare array — the allowlist is short enough that
  // `next_cursor` is always null, but a frozen array could never grow a field.
  http.get("/api/packs", () => {
    const body: PackListPage = { items: PACKS, next_cursor: null };
    return HttpResponse.json(body);
  }),

  http.post("/api/packs/:packId/validate", ({ params }) => {
    const packId = String(params["packId"]);
    if (!PACKS.some((p) => p.id === packId)) {
      return fail("not_found", `no such pack: ${packId}`);
    }
    const body: ValidationReport = { ...VALIDATION_REPORT, pack_id: packId };
    return HttpResponse.json(body);
  }),

  http.get("/api/packs/:packId/axes", ({ params }) => {
    const packId = String(params["packId"]);
    if (!PACKS.some((p) => p.id === packId)) {
      return fail("not_found", `no such pack: ${packId}`);
    }
    const body: PackAxes = { ...PACK_AXES, pack_id: packId };
    return HttpResponse.json(body);
  }),

  // -------------------------------------------------------------------------
  // Discover findings
  // -------------------------------------------------------------------------

  // Paginated the same way `/api/runs` is — same envelope, same opaque
  // `(created_at, run_id)` cursor, same refusal for a malformed one.
  http.get("/api/discoveries", ({ request }) => {
    const url = new URL(request.url);
    const objective = url.searchParams.get("objective");
    const before = url.searchParams.get("before");

    let rows = objective
      ? FINDING_ROWS.filter((f) => f.objective_id === objective)
      : [...FINDING_ROWS];

    if (before !== null) {
      let cursor: [string, string];
      try {
        cursor = parseCursor(before);
      } catch {
        return badCursor();
      }
      rows = rows.filter((f) => isBefore(findingKey(f), cursor));
    }

    const page = rows.slice(0, MOCK_PAGE_SIZE);
    const last = page[page.length - 1];
    const more = rows.length > page.length;
    const body: DiscoveryListPage = {
      items: page,
      next_cursor: more && last ? findingKey(last).join(CURSOR_SEPARATOR) : null,
    };
    return HttpResponse.json(body);
  }),

  http.get("/api/discoveries/:probeId", ({ params, request }) => {
    const probeId = String(params["probeId"]);
    if (!FINDING_ROWS.some((f) => f.probe_id === probeId)) {
      return fail("not_found", `no such finding: ${probeId}`);
    }
    // Per-object reveal, gated on the token minted at server start. There is no
    // global off switch and no env var — a missing token is the normal case.
    const revealed = Boolean(request.headers.get("X-Evalyn-Reveal"));
    const body = revealed ? FINDING_DETAIL_REVEALED : FINDING_DETAIL;
    return HttpResponse.json({ ...body, probe_id: probeId });
  }),

  // -------------------------------------------------------------------------
  // Compare, trends, judge trust
  // -------------------------------------------------------------------------

  http.get("/api/compare/:runId", ({ params }) => {
    const runId = String(params["runId"]);
    const detail = RUN_DETAILS[runId];
    if (!detail || detail.mode !== "compare") {
      return fail("not_found", `no such compare run: ${runId}`);
    }
    return HttpResponse.json({ ...SCOREBOARD, run_id: runId });
  }),

  http.get("/api/trends", ({ request }) => {
    const url = new URL(request.url);
    const pack = url.searchParams.get("pack");
    const metric = url.searchParams.get("metric") ?? "pass_k";
    if (!pack) return fail("pack_error", "?pack= is required");
    return HttpResponse.json(
      TREND_SERIES.map((s) => ({ ...s, pack_name: pack, metric })),
    );
  }),

  http.get("/api/trust", ({ request }) => {
    const pack = new URL(request.url).searchParams.get("pack");
    if (!pack) return fail("pack_error", "?pack= is required");
    // A pack with no calibration.json is a legitimate 200, not a 404.
    if (pack !== TRUST_REPORT.pack_name) {
      return HttpResponse.json({ ...TRUST_NEVER_CALIBRATED, pack_name: pack });
    }
    return HttpResponse.json(TRUST_REPORT);
  }),
];
