import { describe, expect, it } from "vitest";

import { CURSOR_SEPARATOR, parseCursor } from "../../api/types";
import type {
  ControlResponse,
  DiscoveryListPage,
  ErrorEnvelope,
  FindingDetail,
  LaunchResponse,
  MetaResponse,
  PackAxes,
  PackListPage,
  RunDetail,
  RunListPage,
  TrustReport,
  ValidationReport,
} from "../../api/types";
import { MOCK_PAGE_SIZE } from "../handlers";
import {
  FINDING_ROWS,
  PACK_ID_EXAMPLE,
  PACKS,
  RUN_ID_GATE,
  RUN_ID_LEGACY,
  RUN_SUMMARIES,
} from "../fixtures";

/**
 * These assertions are about the *contract*, not about MSW. Each one is a
 * behaviour a later page can get wrong, pinned here so the mock cannot quietly
 * become more forgiving than the server it stands in for.
 */

// Handlers are declared with path-relative predicates (`/api/...`), which MSW
// resolves against the document origin. Anything else silently misses.
const BASE = window.location.origin;

async function get(path: string, init?: RequestInit) {
  return fetch(`${BASE}${path}`, init);
}

describe("/api/meta", () => {
  it("returns display-safe labels, never real paths", async () => {
    const meta = (await (await get("/api/meta")).json()) as MetaResponse;
    expect(meta.runs_dir.startsWith("~")).toBe(true);
    for (const p of meta.packs) expect(p.startsWith("~")).toBe(true);
    // Rendering these is fine. Joining them, or sending them back, is not.
    expect(meta.runs_dir).not.toMatch(/^\/(Users|home)\//);
    expect(meta.redaction.enabled).toBe(true);
    expect(meta.redaction.reveal_required).toBe(true);
  });
});

/**
 * The fixtures the wiring pass caught lying.
 *
 * These are not assertions about MSW either: each one is a value the SPA
 * branches on, pinned to what a **real** `evalyn ui` returns. A mock that
 * disagrees does not merely fail to catch a bug — it makes whole branches of
 * the surface unreachable, so no test and no human ever sees them.
 */
describe("the fixtures answer what a real server answers", () => {
  /** `launcher.pack_id_for`: `"pack-" + sha256(name).hexdigest()[:8]`. */
  async function packIdFor(name: string): Promise<string> {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(name),
    );
    return `pack-${[...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("")
      .slice(0, 8)}`;
  }

  /**
   * `pack-0` is a *position*, and the real server deliberately refuses to mint
   * one: a position is stable only while the command line is, so adding one
   * `--target` silently renumbers every pack and an id a browser still holds
   * then names a different pack (`launcher.pack_id_for`). The digest is stable
   * across restart, reorder, cwd change and moving the pack.
   */
  it("names a pack by a digest of its name, never by its position in the allowlist", async () => {
    const body = (await (await get("/api/packs")).json()) as PackListPage;
    expect(body.items.length).toBeGreaterThan(0);
    for (const pack of body.items) {
      expect(pack.id).toMatch(/^pack-[0-9a-f]{8}$/);
      expect(pack.id).toBe(await packIdFor(pack.name));
    }
  });

  /**
   * Both wrong values made a real branch unreachable. `version: "1.0.0"` meant
   * `Launch.tsx`'s "unversioned" rendition had **never once rendered**, and
   * `TargetSpec` has no version field at all — the server sends `null` for
   * every pack there is. `has_calibration: true` said the opposite of what the
   * shipped packs answer: `pack_rows` reads `calibration.json` off disk, and
   * neither `packs/example` nor `packs/twincore-injection` has one.
   */
  it("reports a pack with no version and no calibration record, as both shipped packs are", async () => {
    const body = (await (await get("/api/packs")).json()) as PackListPage;
    for (const pack of body.items) {
      expect(pack.version).toBeNull();
      expect(pack.has_calibration).toBe(false);
    }
  });

  /**
   * `MetaResponse.allow_discover` is `False` by default in `models.py` and only
   * `evalyn ui --allow-discover` turns it on. The fixture said `true`, which
   * made the launch console's discover refusal — and every axes lookup behind
   * it — unreachable against a default server.
   */
  it("describes a server that was not started with --allow-discover", async () => {
    const meta = (await (await get("/api/meta")).json()) as MetaResponse;
    expect(meta.allow_discover).toBe(false);
  });
});

describe("/api/runs pagination", () => {
  it("pages with an opaque composite cursor, not a bare timestamp", async () => {
    const first = (await (await get("/api/runs")).json()) as RunListPage;
    expect(first.items).toHaveLength(MOCK_PAGE_SIZE);
    expect(first.next_cursor).not.toBeNull();

    // Opaque to the SPA — but it must be the tie-safe composite, and the two
    // halves must be the last row's key.
    const [createdAt, runId] = parseCursor(first.next_cursor!);
    const last = first.items[first.items.length - 1]!;
    expect([createdAt, runId]).toEqual([last.created_at, last.run_id]);

    const next = (await (
      await get(`/api/runs?before=${encodeURIComponent(first.next_cursor!)}`)
    ).json()) as RunListPage;
    const seen = [...first.items, ...next.items].map((r) => r.run_id);
    // Every row exactly once: no tie dropped, none repeated.
    expect(seen).toEqual(RUN_SUMMARIES.map((r) => r.run_id));
    expect(new Set(seen).size).toBe(seen.length);
    expect(next.next_cursor).toBeNull();
  });

  it("rejects the tie-unsafe bare-timestamp cursor with an error envelope", async () => {
    const res = await get("/api/runs?before=2026-08-06T09:10:11.000000%2B00:00");
    expect(res.status).toBe(404);
    const body = (await res.json()) as ErrorEnvelope;
    expect(body.error.code).toBe("not_found");
    expect(body.error.detail).toContain(CURSOR_SEPARATOR);
  });

  it("returns rows in (created_at, run_id) descending order", async () => {
    const page = (await (await get("/api/runs")).json()) as RunListPage;
    const stamps = page.items.map((r) => r.created_at);
    expect([...stamps].sort().reverse()).toEqual(stamps);
  });
});

describe("degradation, not failure", () => {
  it("the legacy row validates, is degraded, and explains itself", async () => {
    const page = (await (await get("/api/runs")).json()) as RunListPage;
    const legacy = [...page.items].find((r) => r.run_id === RUN_ID_LEGACY);
    const row =
      legacy ??
      ((
        (await (
          await get(
            `/api/runs?before=${encodeURIComponent(page.next_cursor!)}`,
          )
        ).json()) as RunListPage
      ).items.find((r) => r.run_id === RUN_ID_LEGACY) ??
        null);
    expect(row).not.toBeNull();
    expect(row!.degraded).toBe(true);
    // A greyed row with no reason is the failure mode the field exists to stop.
    expect(row!.degraded_reason).toBeTruthy();
    // null is "cannot tell you", never 0.
    expect(row!.judge_usd).toBeNull();
    expect(row!.capabilities.trial_records).toBe(false);
  });
});

describe("capabilities gate the drill-down", () => {
  it("404s the trial view on an artifact with no trial records", async () => {
    const res = await get(`/api/runs/${RUN_ID_LEGACY}/trials/grounding/1`);
    expect(res.status).toBe(404);
    const body = (await res.json()) as ErrorEnvelope;
    expect(body.error.code).toBe("not_found");
  });

  it("serves the trial view when the capability is present", async () => {
    const res = await get(`/api/runs/${RUN_ID_GATE}/trials/grounding/1`);
    expect(res.status).toBe(200);
  });
});

describe("run_id is a path segment, never a path", () => {
  it("rejects traversal with the error envelope, not a 422", async () => {
    const res = await get("/api/runs/..%2F..%2Fetc%2Fpasswd");
    expect(res.status).toBe(404);
    const body = (await res.json()) as ErrorEnvelope;
    expect(body.error.code).toBe("not_found");
  });
});

describe("VerdictTier is a string on the wire", () => {
  it("never serialises a tier as a number", async () => {
    const detail = (await (
      await get(`/api/runs/${RUN_ID_GATE}`)
    ).json()) as RunDetail;
    const tiers = detail.probes.flatMap((p) => p.checks.map((c) => c.tier));
    expect(tiers.length).toBeGreaterThan(0);
    for (const t of tiers) expect(typeof t).toBe("string");
    // `abstained` is a member, which is why an integer form was never possible.
    expect(tiers).toContain("abstained");
  });

  it("an abstained check has passed: null, not false", async () => {
    const detail = (await (
      await get(`/api/runs/${RUN_ID_GATE}`)
    ).json()) as RunDetail;
    const abstained = detail.probes
      .flatMap((p) => p.checks)
      .find((c) => c.tier === "abstained")!;
    expect(abstained.passed).toBeNull();
    expect(abstained.score).toBeNull();
  });
});

describe("discover findings are redacted by default", () => {
  const probeId = "discovered-hallucination-abcd1234";

  it("hides the captured value behind the marker without a reveal token", async () => {
    const body = (await (
      await get(`/api/discoveries/${probeId}`)
    ).json()) as FindingDetail;
    expect(body.redacted).toBe(true);
    expect(JSON.stringify(body)).not.toContain("Acme Robotics");
    expect(body.probe_yaml).toContain("«redacted:org»");
  });

  it("reveals per-object when the token is present", async () => {
    const body = (await (
      await get(`/api/discoveries/${probeId}`, {
        headers: { "X-Evalyn-Reveal": "mock-token" },
      })
    ).json()) as FindingDetail;
    expect(body.redacted).toBe(false);
    expect(body.probe_yaml).toContain("Acme Robotics");
  });
});

describe("the list endpoints are envelopes, never bare arrays", () => {
  // A page that does `(await res.json()).map(...)` works against a bare array
  // and breaks the day the contract grows a field. Both lists carry the
  // `RunListPage` shape from the start so that day never comes.

  it("/api/packs returns {items, next_cursor}", async () => {
    const body = (await (await get("/api/packs")).json()) as PackListPage;
    expect(Array.isArray(body)).toBe(false);
    expect(body.items.map((p) => p.id)).toEqual(PACKS.map((p) => p.id));
    expect(body.next_cursor).toBeNull();
    // `path` is a display-safe label. `id` is the only thing that names a pack.
    for (const p of body.items) expect(p.path.startsWith("~")).toBe(true);
  });

  it("/api/discoveries returns {items, next_cursor} and filters by objective", async () => {
    const body = (await (await get("/api/discoveries")).json()) as DiscoveryListPage;
    expect(Array.isArray(body)).toBe(false);
    expect(body.items).toHaveLength(FINDING_ROWS.length);
    expect(body.items.length).toBeLessThanOrEqual(MOCK_PAGE_SIZE);
    expect(body.next_cursor).toBeNull();

    const pii = (await (
      await get("/api/discoveries?objective=pii")
    ).json()) as DiscoveryListPage;
    expect(pii.items.map((f) => f.objective_id)).toEqual(["pii"]);
  });

  it("/api/discoveries rejects the tie-unsafe cursor exactly as /api/runs does", async () => {
    const res = await get("/api/discoveries?before=2026-08-05T10:11:12.000000%2B00:00");
    expect(res.status).toBe(404);
    const body = (await res.json()) as ErrorEnvelope;
    expect(body.error.code).toBe("not_found");
    expect(body.error.detail).toContain(CURSOR_SEPARATOR);
  });
});

describe("packs and the write-side acknowledgements", () => {
  it("echoes the pack_id back on validate, so a response is attributable", async () => {
    const body = (await (
      await get(`/api/packs/${PACK_ID_EXAMPLE}/validate`, { method: "POST" })
    ).json()) as ValidationReport;
    expect(body.pack_id).toBe(PACK_ID_EXAMPLE);
    expect(body.ok).toBe(true);
  });

  it("reports a budget ceiling that is a number, never null", async () => {
    const body = (await (
      await get(`/api/packs/${PACK_ID_EXAMPLE}/axes`)
    ).json()) as PackAxes;
    expect(typeof body.max_usd_per_run).toBe("number");
    expect(body.objectives.length).toBeGreaterThan(0);
  });

  it("mints the run_id in the 202, before anything has run", async () => {
    const res = await get("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: "gate",
        pack_id: PACK_ID_EXAMPLE,
        confirm: "example",
      }),
    });
    expect(res.status).toBe(202);
    const body = (await res.json()) as LaunchResponse;
    // The stem of the artifact that later appears — the id a page subscribes to.
    expect(body.run_id).toBe(RUN_ID_GATE);
  });

  it("answers control with accepted, which is NOT the acknowledgement", async () => {
    const res = await get(`/api/runs/${RUN_ID_GATE}/control`, { method: "POST" });
    expect(res.status).toBe(202);
    const body = (await res.json()) as ControlResponse;
    expect(body).toEqual({ run_id: RUN_ID_GATE, accepted: true });
    // The `control.*` SSE event is the ack. Nothing here says the run paused.
    expect(Object.keys(body)).not.toContain("status");
  });
});

describe("judge trust", () => {
  it("answers 200 with a null agreement for a never-calibrated pack", async () => {
    const res = await get("/api/trust?pack=uncalibrated");
    expect(res.status).toBe(200);
    const body = (await res.json()) as TrustReport;
    expect(body.agreement).toBeNull();
    expect(body.stale_reason).toBe("never calibrated");
  });

  it("never labels agreement as kappa", async () => {
    const body = await (await get("/api/trust?pack=example")).text();
    expect(body.toLowerCase()).not.toContain("kappa");
  });
});

describe("every contract route has a handler", () => {
  // `onUnhandledRequest: "error"` in setup.ts turns a missing handler into a
  // rejected fetch, so this is a real coverage check rather than a list.
  const routes: [string, RequestInit | undefined][] = [
    ["/api/meta", undefined],
    ["/api/health", undefined],
    ["/api/runs", undefined],
    [`/api/runs/${RUN_ID_GATE}`, undefined],
    [`/api/runs/${RUN_ID_GATE}/gate`, undefined],
    [`/api/runs/${RUN_ID_GATE}/report`, undefined],
    [`/api/runs/${RUN_ID_GATE}/stderr`, undefined],
    [`/api/runs/${RUN_ID_GATE}/events`, undefined],
    [`/api/runs/${RUN_ID_GATE}/trials/grounding-work-history/1`, undefined],
    [
      "/api/runs",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "gate",
          pack_id: PACK_ID_EXAMPLE,
          confirm: "example",
        }),
      },
    ],
    [`/api/runs/${RUN_ID_GATE}/control`, { method: "POST" }],
    ["/api/packs", undefined],
    [`/api/packs/${PACK_ID_EXAMPLE}/validate`, { method: "POST" }],
    [`/api/packs/${PACK_ID_EXAMPLE}/axes`, undefined],
    ["/api/discoveries", undefined],
    ["/api/discoveries/discovered-hallucination-abcd1234", undefined],
    ["/api/compare/20260806T091011000000-9f8e7d6c-example-compare", undefined],
    ["/api/trends?pack=example&metric=pass_k", undefined],
    ["/api/trust?pack=example", undefined],
  ];

  it.each(routes)("%s is handled", async (path, init) => {
    const res = await get(path, init);
    expect(res.status).toBeLessThan(400);
  });
});
