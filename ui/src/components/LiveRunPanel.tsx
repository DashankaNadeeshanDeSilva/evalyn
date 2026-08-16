import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiFailure, apiGet, apiPost } from "../api/client";
import type {
  ControlAction,
  ControlResponse,
  PackAxes,
  PackListPage,
  RunId,
  RunStatus,
} from "../api/types";
import { useRunEvents } from "../hooks/useRunEvents";
import { ControlButtons } from "./ControlButtons";
import { LiveBanner } from "./LiveBanner";

/**
 * The seam between the live stream and the one inset window.
 *
 * ## Why it mounts even when there is nothing to show
 *
 * React needs a stable hook order, and the run detail page cannot know whether
 * a run is live until its query settles — so this component mounts
 * unconditionally and decides for itself. `useRunEvents` opens no socket when
 * disabled, so a run that finished last week costs one render and nothing else.
 *
 * ## Two questions, not two answers to one question
 *
 * There are genuinely two things to know, and conflating them is what shipped a
 * bug:
 *
 * - **`live`** — is a process attached *right now*? It comes from the caller,
 *   off the same `run.status` the page reads, and it decides the one thing two
 *   components can both do: report spend. One value, one render, so the chip
 *   and the window can never both show a figure and can never both hide one.
 * - **`watched`** — did this page ever see one? Latched at mount, because the
 *   surface brief's window appears "when something is actually running **or has
 *   just finished**". Re-reading it would make the window vanish in the very
 *   frame the run ended, taking the run's outcome with it.
 *
 * The first version had `live` latched here and recomputed on the page. The
 * moment a run finished, the refetch flipped the page's copy to `false` while
 * this one stayed `true`, and the artifact's chip came back **beside** the
 * stream's still-rendered figure — including the case where the artifact had no
 * spend to report, which put "unrecorded" next to a real number. Nothing here
 * answers a question the page also answers any more.
 *
 * ## The 202 is not the acknowledgement
 *
 * A control request that returns `accepted: true` has been *written*, not
 * *taken*. The state below records only that a request is outstanding; the
 * phase itself moves when the matching `control.*` event arrives, which is what
 * clears the wait. A UI that flipped to "paused" on the response would be
 * claiming the engine did something it may not have done for another minute —
 * or, if it never acknowledges, ever (ruling R4-11).
 *
 * ## Still owed — live checks this cannot make (prerequisite: Tasks 6, 7, 19, 20)
 *
 * The only stream this has met is the scripted MSW handler. Against a real
 * `evalyn ui` the wiring pass must verify:
 *
 * 1. ~~`GET /api/runs/{id}` answers for a run whose artifact does not exist
 *    yet.~~ **Discharged**: `server.py:_pending_detail` builds exactly that
 *    row, so the launch console can navigate here the moment the 202 lands
 *    without meeting a 404 or the detail page's "artifact could not be read"
 *    alarm. Kept rather than deleted because items 2–4 below are numbered
 *    against it in the register.
 * 2. The refetch fired on `artifact.written` finds the artifact on disk, and
 *    the status it returns is `running`/`paused` from the sidecar before that.
 * 3. A cancel that the engine never acknowledges leaves this window in
 *    `cancelling` and the run resolves as `interrupted` — never a UI stuck
 *    claiming a cancel that did not happen.
 * 4. `POST /api/runs/{id}/control` on a finished run refuses, and the refusal
 *    is a sentence the operator can act on rather than a bare 409.
 */

/**
 * The two statuses that mean a process is still attached to this run.
 *
 * Exported so there is **one** definition of "live" on the surface. There were
 * two, and they diverged: this file latched the answer at mount while the run
 * detail page recomputed it on every refetch, so the moment a run finished the
 * page believed it was over and this panel believed it was not — and both
 * rendered a spend figure.
 */
export const LIVE_STATUSES: readonly RunStatus[] = ["running", "paused"];

export function isLive(status: RunStatus): boolean {
  return LIVE_STATUSES.includes(status);
}

export function LiveRunPanel({
  runId,
  status,
  live,
  packName = null,
}: {
  runId: RunId;
  status: RunStatus;
  /**
   * Is a process attached **right now**, from the same `run.status` the page
   * reads? This governs the one question two components can both answer —
   * who reports spend — and it must be the caller's value, never a second
   * opinion computed here.
   */
  live: boolean;
  /** The run's pack, joined by name to the allowlist to read its ceiling. */
  packName?: string | null;
}) {
  /*
   * A *different* question from `live`, and the reason both exist.
   *
   * `live` asks "is a process attached now"; `watched` asks "did this page ever
   * see one". Only `watched` may decide whether the window is on screen,
   * because the surface brief's window appears "when something is actually
   * running **or has just finished**" — re-reading `live` here would make the
   * window vanish in the very frame the run ended, taking the run's own
   * outcome with it. Nothing else on the surface answers this question, so it cannot
   * diverge from anything the way the old latch did.
   */
  const [watched] = useState(() => isLive(status));
  const state = useRunEvents(runId, { enabled: watched });
  const queryClient = useQueryClient();
  const [requested, setRequested] = useState<ControlAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  const phase = state.phase;
  useEffect(() => {
    // The ack landed — whatever it said. The wait ends when the phase moves,
    // never when a response arrives.
    setRequested(null);
  }, [phase]);

  const written = state.artifactWritten;
  useEffect(() => {
    if (!watched) return;
    if (!written && phase !== "finished") return;
    // The artifact is the authority on status, verdict and probe rows;
    // `derive_status` decides it server-side and this client does not
    // reproduce that decision from an exit code.
    void queryClient.invalidateQueries({ queryKey: ["run", runId] });
  }, [watched, written, phase, queryClient, runId]);

  /*
   * The pack's per-run ceiling, joined by **name** — a run records a
   * `pack_name`, and the allowlist is the only place a browser may learn an
   * `id`. A run whose pack is not on this server's `--target` list therefore
   * has no ceiling available, and that is the demo's real case rather than a
   * hypothetical: the twincore runs in `runs/` were produced by a pack the
   * running server is unlikely to be serving.
   *
   * Same query keys and lifetimes as `CostChip`, so the two share one cache
   * entry and this costs no extra request.
   */
  const packs = useQuery({
    queryKey: ["packs"],
    enabled: watched,
    queryFn: () => apiGet<PackListPage>("/packs"),
    staleTime: Infinity,
  });
  const pack =
    packName === null
      ? undefined
      : packs.data?.items.find((row) => row.name === packName);
  const axes = useQuery({
    queryKey: ["pack-axes", pack?.id ?? null],
    enabled: pack !== undefined,
    queryFn: () =>
      apiGet<PackAxes>(`/packs/${encodeURIComponent(pack!.id)}/axes`),
    staleTime: Infinity,
  });
  const ceiling = axes.data?.max_usd_per_run ?? null;
  // "Still reading" is a different claim from "there is no ceiling", and the
  // window must not render the second while the first is true.
  const ceilingSettled =
    packName === null ||
    packs.isError ||
    (packs.isSuccess && pack === undefined) ||
    axes.isError ||
    axes.isSuccess;

  const send = useCallback(
    (action: ControlAction) => {
      setError(null);
      setRequested(action);
      apiPost<ControlResponse>(`/runs/${encodeURIComponent(runId)}/control`, {
        action,
      }).catch((failure: unknown) => {
        setRequested(null);
        setError(
          failure instanceof ApiFailure
            ? `${action} refused — ${failure.code ?? failure.status}: ${failure.message}`
            : `The cockpit could not reach its server to ${action} this run.`,
        );
      });
    },
    [runId],
  );

  if (!watched) return null;

  return (
    <LiveBanner
      state={state}
      /*
       * The spend reading belongs to whoever can actually answer for it, and
       * the artifact is the authority the moment it exists. So the stream
       * reports spend only while there is no artifact to report it — the same
       * `live` the page uses to decide whether to render its own chip, so the
       * two can never both be on screen and can never both be absent.
       */
      showSpend={live}
      ceiling={ceiling}
      ceilingSettled={ceilingSettled}
    >
      <ControlButtons
        phase={state.phase}
        requested={requested}
        error={error}
        onAction={send}
      />
    </LiveBanner>
  );
}
