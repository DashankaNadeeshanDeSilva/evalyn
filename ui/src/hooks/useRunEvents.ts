import { useEffect, useReducer } from "react";

import { API_ROOT } from "../api/client";
import { EVENT_NAMES, type EventName, type RunId } from "../api/types";

/**
 * The live run stream: one pure fold, and the thinnest possible adapter over
 * the browser's own `EventSource`.
 *
 * ## Why the fold is exported separately
 *
 * jsdom ships no `EventSource` — verified, `typeof window.EventSource` is
 * `undefined` under the pinned jsdom 29 — so a hook that owned the decisions
 * would be a hook nothing could test. Every decision therefore lives in
 * `runEventsReducer`, which is pure and covered; the hook below only converts
 * DOM events into reducer input and closes the socket at the right moment.
 *
 * ## `Last-Event-ID` is the browser's protocol, not ours
 *
 * `EventSource` reconnects on its own schedule and replays the last `id:` it
 * saw in a `Last-Event-ID` request header. Task 20's `event_stream` resumes by
 * skipping `seq <= N`, which is why `id:` **is** the sink's sequence number and
 * why nothing here builds a resume cursor by hand.
 *
 * Two consequences fall out of that, and both are handled in the fold rather
 * than here:
 *
 * - **A replayed frame must be a no-op.** The endpoint replays a finished run's
 *   history from the top for any new subscriber, and a browser reconnect can
 *   re-deliver the tail. `seq <= lastSeq` returns the state untouched.
 * - **A gap in `seq` means frames were lost**, so the fold says
 *   `connection: "reconnecting"` and counts what went missing rather than
 *   quietly reporting a thinner run than actually happened.
 *
 * ## The one thing this hook must do itself
 *
 * **Close the socket when the run ends.** A server that closes a finished
 * stream is, to `EventSource`, a connection drop — it will reconnect, get the
 * whole history replayed, and do it again forever. `close()` on a terminal
 * phase is what stops that, and it is why `phase` is in the effect's
 * dependency list.
 *
 * ## Event payloads are NOT frozen
 *
 * `models.EventName` freezes the nineteen *names*; the `data:` bodies are
 * written by Task 18's emit sites and do not exist yet. Every reader below is
 * therefore defensive: a missing or wrongly-typed field leaves the previous
 * reading in place instead of writing `null` or `NaN` into the readout.
 *
 * ## Deferred — the live checks this cannot make (prerequisite: Tasks 18-20)
 *
 * Nothing here has ever met a real event stream; the only stream it has seen is
 * the scripted MSW handler, which emits eight frames and closes. When Tasks 18,
 * 19 and 20 land, the pass that wires them must verify, against a real
 * `evalyn ui`:
 *
 * 1. `id:` carries the sink's `seq`, and a reconnect with `Last-Event-ID: N`
 *    resumes at `N + 1` rather than replaying from 1.
 * 2. The `data:` payload keys this fold reads are the keys the emit sites
 *    actually write: `judge_usd` on `spend.updated`; `probe_id` and `pass_k` on
 *    `probe.scored`; `probe_id`/`epoch` on `trial.started`; `turn` on
 *    `turn.sent`/`turn.received`; `exit_code` on `run.finished`.
 * 3. A heartbeat every `MetaResponse.heartbeat_seconds` keeps the connection
 *    open through an idle run, and the `: idle-timeout` comment frame does not
 *    reach a named listener.
 * 4. The three `control.*` acks arrive after their 202, and a cancel that is
 *    never acknowledged still ends as an honest `interrupted` run (ruling
 *    R4-11) rather than a UI stuck on "cancelling".
 * 5. `artifact.written` lands before `run.finished`, so the refetch this hook's
 *    consumer fires finds the artifact on disk.
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/**
 * What the run is doing, as the *stream* sees it.
 *
 * Deliberately **not** `RunStatus`. `derive_status` in `ui/index.py` is the one
 * place a run's status is decided, and it decides from the artifact and the
 * sidecar together — a mapping this client cannot reproduce from an exit code
 * without inventing one. So the live window reports the phase it can actually
 * observe, and the authoritative status still comes from `GET /api/runs/{id}`
 * once the artifact lands.
 */
export const RUN_PHASES = [
  "connecting",
  "running",
  "paused",
  /** The cancel ack landed. In-flight trials are still finishing, and billing. */
  "cancelling",
  "finished",
] as const;
export type RunPhase = (typeof RUN_PHASES)[number];

export const CONNECTION_STATES = [
  "connecting",
  "open",
  "reconnecting",
  "closed",
] as const;
export type ConnectionState = (typeof CONNECTION_STATES)[number];

/** One probe the stream has seen scored. `passK` is `null` when unknown. */
export interface LiveProbe {
  readonly probeId: string;
  readonly passK: number | null;
}

/**
 * The most recent frame worth naming on screen.
 *
 * Kept as fields rather than a rendered sentence: the fold is pure and the copy
 * rules live in the components, so the words are chosen where they can be read
 * beside the rest of the surface's language.
 */
export interface Activity {
  readonly name: EventName;
  readonly probeId: string | null;
  readonly epoch: number | null;
  readonly turn: number | null;
}

export interface RunEventsState {
  /** The highest `seq` applied. `0` means nothing has arrived yet. */
  readonly lastSeq: number;
  readonly connection: ConnectionState;
  readonly phase: RunPhase;
  /** From `run.finished`. Never mapped to a `RunStatus` here — see `RUN_PHASES`. */
  readonly exitCode: number | null;
  /** Evalyn's own judge spend so far. `null` = not reported, never `0`. */
  readonly judgeUsd: number | null;
  readonly probes: readonly LiveProbe[];
  readonly trials: number;
  readonly artifactWritten: boolean;
  readonly activity: Activity | null;
  /** How many frames the sequence proves were lost. Never resets to zero. */
  readonly missedEvents: number;
}

/** One SSE frame: `id:` is the seq, `event:` the name, `data:` the parsed body. */
export interface RunEvent {
  readonly seq: number;
  readonly name: EventName;
  readonly data: unknown;
}

/** A client-side transition — the socket opened, dropped, or was closed. */
export interface ConnectionChange {
  readonly connection: ConnectionState;
}

export type RunEventsInput = RunEvent | ConnectionChange;

export const initialRunEventsState: RunEventsState = {
  lastSeq: 0,
  connection: "connecting",
  phase: "connecting",
  exitCode: null,
  judgeUsd: null,
  probes: [],
  trials: 0,
  artifactWritten: false,
  activity: null,
  missedEvents: 0,
};

// ---------------------------------------------------------------------------
// Payload readers — every one of them tolerant, because the shapes are unfrozen
// ---------------------------------------------------------------------------

function field(data: unknown, key: string): unknown {
  return typeof data === "object" && data !== null
    ? (data as Record<string, unknown>)[key]
    : undefined;
}

function num(data: unknown, key: string): number | null {
  const value = field(data, key);
  // `"0.99"` is not a number: a string that happens to parse is exactly the
  // kind of near-miss that would put a wrong figure on a money readout.
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(data: unknown, key: string): string | null {
  const value = field(data, key);
  return typeof value === "string" && value !== "" ? value : null;
}

/**
 * The names this fold has a rendition for, proved against the frozen enum.
 *
 * `satisfies` is the point: a typo, or a name invented rather than added to
 * `models.EventName` first, fails to compile. Every other member of the enum
 * reaches the fold and is ignored, which is the behaviour `types.ts` §4
 * specifies for a name the SPA does not know.
 */
const EV = {
  runStarted: "run.started",
  runFinished: "run.finished",
  spendUpdated: "spend.updated",
  artifactWritten: "artifact.written",
  trialStarted: "trial.started",
  turnSent: "turn.sent",
  turnReceived: "turn.received",
  probeScored: "probe.scored",
  controlPaused: "control.paused",
  controlResumed: "control.resumed",
  controlCancelled: "control.cancelled",
} as const satisfies Record<string, EventName>;

/** `probe.scored` for a probe already in the list replaces it, never appends. */
function withProbe(
  probes: readonly LiveProbe[],
  probeId: string,
  passK: number | null,
): readonly LiveProbe[] {
  const at = probes.findIndex((probe) => probe.probeId === probeId);
  if (at === -1) return [...probes, { probeId, passK }];
  const next = [...probes];
  next[at] = { probeId, passK };
  return next;
}

// ---------------------------------------------------------------------------
// The fold
// ---------------------------------------------------------------------------

export function runEventsReducer(
  state: RunEventsState,
  input: RunEventsInput,
): RunEventsState {
  if ("connection" in input) {
    /*
     * A terminal run's connection is settled, and the transition is ignored.
     *
     * Measured in a browser, not reasoned about: when the server closes a
     * finished stream, `EventSource` reports the teardown through `onerror`
     * with `readyState` still `CONNECTING` — it is already scheduling the
     * reconnect this hook is one render away from cancelling. Taking that at
     * face value put "Reconnecting" under the word FINISHED, which is an alarm
     * about a socket that was closed on purpose.
     */
    const settled = state.phase === "finished" ? "closed" : input.connection;
    return settled === state.connection
      ? state
      : { ...state, connection: settled };
  }

  const { seq, name, data } = input;
  // Out of order, replayed, or unsequenced (a frame with no `id:` leaves
  // `lastEventId` holding the previous one). All three mean "already applied".
  if (!Number.isInteger(seq) || seq <= state.lastSeq) return state;

  const lost = seq - state.lastSeq - 1;
  const terminal = state.phase === "finished";

  let next: RunEventsState = {
    ...state,
    lastSeq: seq,
    // A frame in hand *is* an open connection, unless the sequence proves the
    // stream lost frames on the way here. `run.finished` closes it below.
    connection: lost > 0 ? "reconnecting" : "open",
    missedEvents: state.missedEvents + Math.max(lost, 0),
  };

  const activity = (): Activity => ({
    name,
    probeId: str(data, "probe_id"),
    epoch: num(data, "epoch"),
    turn: num(data, "turn"),
  });

  switch (name) {
    case EV.runStarted:
      // A control ack that lands after `run.finished` must not put a finished
      // run back on the air, so every phase move is gated on the same guard.
      if (!terminal) next = { ...next, phase: "running", activity: activity() };
      break;
    case EV.runFinished:
      next = {
        ...next,
        phase: "finished",
        exitCode: num(data, "exit_code") ?? state.exitCode,
        // Terminal means done: the consumer closes the socket rather than
        // letting the browser reconnect into an endless replay of this run.
        connection: "closed",
        activity: activity(),
      };
      break;
    case EV.spendUpdated:
      next = { ...next, judgeUsd: num(data, "judge_usd") ?? state.judgeUsd };
      break;
    case EV.artifactWritten:
      next = { ...next, artifactWritten: true, activity: activity() };
      break;
    case EV.trialStarted:
      next = { ...next, trials: state.trials + 1, activity: activity() };
      break;
    case EV.turnSent:
    case EV.turnReceived:
      next = { ...next, activity: activity() };
      break;
    case EV.probeScored: {
      const probeId = str(data, "probe_id");
      if (probeId !== null) {
        next = {
          ...next,
          probes: withProbe(state.probes, probeId, num(data, "pass_k")),
          activity: activity(),
        };
      }
      break;
    }
    case EV.controlPaused:
      if (!terminal) next = { ...next, phase: "paused", activity: activity() };
      break;
    case EV.controlResumed:
      if (!terminal) next = { ...next, phase: "running", activity: activity() };
      break;
    case EV.controlCancelled:
      if (!terminal) next = { ...next, phase: "cancelling", activity: activity() };
      break;
    default:
      // An `EventName` this fold has no rendition for — `pair.judged`,
      // `finding.staged`, `heartbeat`. Ignored, never fatal, and the sequence
      // still advances so the next frame is not misread as a gap.
      break;
  }

  return next;
}

// ---------------------------------------------------------------------------
// The adapter
// ---------------------------------------------------------------------------

function parseData(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    // A frame this build cannot parse is one frame's worth of detail lost, not
    // a reason to tear down a live run's readout.
    return null;
  }
}

export interface UseRunEventsOptions {
  /**
   * Subscribe at all. `false` opens no socket — which is what lets the live
   * panel mount unconditionally (React needs the hook order stable) and stay
   * silent for a run that finished long before this page was opened.
   */
  enabled?: boolean;
}

export function useRunEvents(
  runId: RunId,
  options: UseRunEventsOptions = {},
): RunEventsState {
  const enabled = options.enabled ?? true;
  const [state, dispatch] = useReducer(runEventsReducer, initialRunEventsState);
  const finished = state.phase === "finished";

  useEffect(() => {
    if (!enabled || finished) return;

    const source = new EventSource(
      `${API_ROOT}/runs/${encodeURIComponent(runId)}/events`,
    );

    // Named events never reach `onmessage`: `EventSource` dispatches `event:
    // run.started` to a listener registered for that exact name. Registering
    // the frozen list is what makes an unknown-to-us-but-real name reach the
    // fold, where it is ignored deliberately rather than by omission.
    for (const name of EVENT_NAMES) {
      source.addEventListener(name, (raw: MessageEvent<string>) => {
        dispatch({
          seq: Number(raw.lastEventId),
          name,
          data: parseData(raw.data),
        });
      });
    }

    source.onopen = () => dispatch({ connection: "open" });
    source.onerror = () => {
      // `EventSource` reports both "the connection dropped, I am retrying" and
      // "I have given up" through the same handler; only `readyState` tells
      // them apart, and the operator needs to know which one they are in.
      dispatch({
        connection:
          source.readyState === EventSource.CLOSED ? "closed" : "reconnecting",
      });
    };

    return () => source.close();
  }, [runId, enabled, finished]);

  return state;
}
