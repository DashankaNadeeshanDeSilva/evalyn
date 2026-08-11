import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ApiFailure, apiPost } from "../api/client";
import type {
  ControlAction,
  ControlResponse,
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
 * ## Why "is this live" is decided once
 *
 * The surface brief: the window "appears only when something is actually
 * running or has just finished". Both halves matter. If the decision were
 * re-read on every render, the window would **vanish at the exact moment the
 * run ended** — the operator would watch a run finish and lose the readout and
 * the exit code in the same frame, because the refetch below flips the status
 * from `running` to `passed`. So the decision is taken from the first status
 * this page ever saw and then held.
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
 * ## Deferred — live checks this cannot make (prerequisite: Tasks 6, 7, 19, 20)
 *
 * The only stream this has met is the scripted MSW handler. Against a real
 * `evalyn ui` the wiring pass must verify:
 *
 * 1. `GET /api/runs/{id}` answers for a run whose artifact does **not exist
 *    yet** — the launch console navigates here the moment the 202 lands. If it
 *    404s instead, this panel owns that state and the run detail page must not
 *    render its "artifact could not be read" alarm over a healthy live run.
 * 2. The refetch fired on `artifact.written` finds the artifact on disk, and
 *    the status it returns is `running`/`paused` from the sidecar before that.
 * 3. A cancel that the engine never acknowledges leaves this window in
 *    `cancelling` and the run resolves as `interrupted` — never a UI stuck
 *    claiming a cancel that did not happen.
 * 4. `POST /api/runs/{id}/control` on a finished run refuses, and the refusal
 *    is a sentence the operator can act on rather than a bare 409.
 */

/** The two statuses that mean a process is still attached to this run. */
const LIVE_STATUSES: readonly RunStatus[] = ["running", "paused"];

export function LiveRunPanel({
  runId,
  status,
}: {
  runId: RunId;
  status: RunStatus;
}) {
  const [live] = useState(() => LIVE_STATUSES.includes(status));
  const state = useRunEvents(runId, { enabled: live });
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
    if (!live) return;
    if (!written && phase !== "finished") return;
    // The artifact is the authority on status, verdict and probe rows;
    // `derive_status` decides it server-side and this client does not
    // reproduce that decision from an exit code.
    void queryClient.invalidateQueries({ queryKey: ["run", runId] });
  }, [live, written, phase, queryClient, runId]);

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

  if (!live) return null;

  return (
    <LiveBanner state={state}>
      <ControlButtons
        phase={state.phase}
        requested={requested}
        error={error}
        onAction={send}
      />
    </LiveBanner>
  );
}
