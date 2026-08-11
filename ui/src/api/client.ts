import {
  QueryClient,
  useInfiniteQuery,
  useQuery,
} from "@tanstack/react-query";

import type {
  ErrorCode,
  ErrorEnvelope,
  MetaResponse,
  RunDetail,
  RunId,
  RunListPage,
  RunMode,
} from "./types";

/**
 * The cockpit's only door to the server.
 *
 * Two rules are enforced here rather than left to each caller:
 *
 * 1. **Every non-2xx body is an `ErrorEnvelope`.** The server re-wraps even
 *    FastAPI's own 422s into `{"error": {code, message, detail}}`, so there is
 *    exactly one error parser and pages switch on `code`, never on status text.
 * 2. **A cursor is opaque.** `useRuns` hands `next_cursor` straight back as
 *    `?before=`. Nothing in this file parses, compares or constructs one; the
 *    bare-timestamp form is tie-unsafe and the server rejects it loudly.
 */

/**
 * The API is mounted at the server root, which is where `evalyn ui` serves it.
 * Asset URLs are relative (`base: "./"`) because the SPA is a `StaticFiles`
 * mount, but API calls are not assets — they are absolute so a client-side
 * route like `/runs/<id>` cannot turn `api/meta` into `/runs/api/meta`.
 */
export const API_ROOT = "/api";

/** A non-2xx response, parsed. `code` is the thing worth switching on. */
export class ApiFailure extends Error {
  readonly status: number;
  readonly code: ErrorCode | null;
  readonly detail: string | null;

  constructor(
    status: number,
    code: ErrorCode | null,
    message: string,
    detail: string | null,
  ) {
    super(message);
    this.name = "ApiFailure";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function toFailure(res: Response): Promise<ApiFailure> {
  try {
    const body = (await res.json()) as ErrorEnvelope;
    const err = body.error;
    if (err && typeof err.message === "string") {
      // `?? null` makes the declared `string | null` actually true. The server
      // renders every envelope with `exclude_none=True`, so a refusal with no
      // extra context omits `detail` rather than sending null — and a caller
      // that trusted the declared type printed the word "undefined" at the end
      // of every real refusal it rendered.
      return new ApiFailure(res.status, err.code, err.message, err.detail ?? null);
    }
  } catch {
    // Fall through: a body that is not the envelope is itself the anomaly.
  }
  return new ApiFailure(res.status, null, `HTTP ${res.status}`, null);
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_ROOT}${path}`, {
    headers: { Accept: "application/json" },
    ...init,
  });
  if (!res.ok) throw await toFailure(res);
  return (await res.json()) as T;
}

/**
 * The write side. Two routes use it: launch and control.
 *
 * Both bodies are `extra="forbid"` server-side, which is a **safety guard**
 * rather than tidiness — `LaunchRequest` has no field for a pack path, so a
 * body carrying one is rejected rather than ignored. Nothing here adds a field
 * of its own for that reason, and callers pass the frozen request models.
 *
 * A 202 from either route means "well-formed and written", never "done": the
 * matching `control.*` event is the acknowledgement, and `LaunchResponse.run_id`
 * names a run whose process has not started yet.
 */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await toFailure(res);
  return (await res.json()) as T;
}

/**
 * One client per app instance, never a module-level singleton — a shared cache
 * would leak state between tests and between mounts.
 *
 * `retry: false` is deliberate: this server is `127.0.0.1`. A failed request is
 * a real answer worth showing the operator immediately, not a flaky network to
 * paper over with three silent retries.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        staleTime: 5_000,
      },
    },
  });
}

export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => apiGet<MetaResponse>("/meta"),
    // The server cannot change its runs_dir or redaction settings while it is
    // running; re-asking is pure noise.
    staleTime: Infinity,
  });
}

export interface RunsFilter {
  mode?: RunMode;
  pack?: string;
}

/**
 * The runs list, paginated by the opaque `(created_at, run_id)` cursor.
 *
 * The page param IS the server's `next_cursor`, carried verbatim. There is no
 * client-side cursor construction anywhere in this codebase, which is what
 * keeps the tie-unsafe bare-timestamp form from being reintroduced.
 */
export function useRuns(filter: RunsFilter = {}) {
  return useInfiniteQuery({
    queryKey: ["runs", filter.mode ?? null, filter.pack ?? null],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const query = new URLSearchParams();
      if (filter.mode) query.set("mode", filter.mode);
      if (filter.pack) query.set("pack", filter.pack);
      if (pageParam !== null) query.set("before", pageParam);
      const qs = query.toString();
      return apiGet<RunListPage>(`/runs${qs ? `?${qs}` : ""}`);
    },
    // `null` means the end of the list, and TanStack Query reads a nullish
    // result as "no next page" — the two agree exactly.
    getNextPageParam: (last: RunListPage) => last.next_cursor,
  });
}

export function useRunDetail(runId: RunId) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => apiGet<RunDetail>(`/runs/${encodeURIComponent(runId)}`),
  });
}
