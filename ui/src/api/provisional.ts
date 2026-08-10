/**
 * Shapes the cockpit needs that **`models.py` does not yet freeze**.
 *
 * They live here, not in `types.ts`, on purpose: `types.ts` is a mirror and its
 * drift test treats it as one. Everything below is the frontend's best guess at
 * a contract that Tasks 11 (`/api/packs`, `/validate`, `/axes`) and 20
 * (`POST /api/runs`) will actually fix. Treat these as provisional — when the
 * Python side lands, the corresponding model should be added to `models.py` and
 * the type **moved** into `types.ts`, not duplicated.
 *
 * Consumers: import from here so the seam stays visible in the import list.
 */

import type { RunId } from "./types";

/**
 * One entry of `GET /api/packs` — the start-time allowlist built from
 * `evalyn ui --target <path>`.
 *
 * `id` is an **index into that allowlist**, never a path: it is the only pack
 * identifier a browser is allowed to name, which is what stops a request from
 * pointing the engine at an arbitrary file. `name` is what `LaunchRequest.confirm`
 * must echo.
 */
export interface PackRow {
  id: string;
  name: string;
  /** Display-safe (`~`-collapsed), like `MetaResponse.packs`. Never a real path. */
  path: string;
  version: string | null;
  probe_count: number;
  has_calibration: boolean;
}

/** `POST /api/packs/{pack_id}/validate` — the real `ValidationReport` fields. */
export interface ValidationReport {
  pack_id: string;
  ok: boolean;
  errors: string[];
  warnings: string[];
}

/** `GET /api/packs/{pack_id}/axes` — what a `discover` launch can select from. */
export interface PackAxes {
  pack_id: string;
  objectives: string[];
  personas: string[];
  playbooks: string[];
  /** The pack's own per-run ceiling. A launch is clamped down to it, never up. */
  max_usd_per_run: number | null;
}

/**
 * `POST /api/runs` on success.
 *
 * The `run_id` here is the stem of the artifact that will later appear in
 * `runs/` — it is minted before the process starts so the SPA can subscribe to
 * `/api/runs/{id}/events` immediately, without polling for the file.
 */
export interface LaunchAccepted {
  run_id: RunId;
}

/**
 * `POST /api/runs/{id}/control` on success.
 *
 * A 202 here is **not** the acknowledgement — the matching `control.*` SSE
 * event is. Do not flip the UI to "paused" off this response.
 */
export interface ControlAccepted {
  run_id: RunId;
  accepted: boolean;
}
