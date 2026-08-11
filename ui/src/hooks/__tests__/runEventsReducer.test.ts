import { describe, expect, it } from "vitest";

import type { EventName } from "../../api/types";
import {
  initialRunEventsState,
  runEventsReducer,
  type RunEvent,
  type RunEventsState,
} from "../useRunEvents";

/**
 * The live stream's fold, tested without a DOM.
 *
 * `runEventsReducer` is exported pure precisely so this file can exist: jsdom
 * ships no `EventSource` at all (verified — `typeof window.EventSource` is
 * `undefined` under jsdom 29), so the hook around it cannot be exercised here.
 * Keeping every decision in the fold means the part that can be wrong is the
 * part that is covered.
 *
 * Four properties are load-bearing and each has a test that fails without it:
 *
 * 1. **Events apply in `seq` order.** The `id:` field of the SSE frame is the
 *    sink's sequence number, and it is the only ordering authority.
 * 2. **A replayed event is idempotent.** `GET /api/runs/{id}/events` replays
 *    history from the start for a finished run, and the browser's own
 *    `EventSource` reconnects on its own schedule, so the same frame arriving
 *    twice is the normal case rather than the pathological one.
 * 3. **`run.finished` is terminal.** A control ack that lands after it must not
 *    put a finished run back on the air.
 * 4. **A gap in `seq` is a lost connection**, not a silently thinner run. The
 *    fold says so; the hook resubscribes with `Last-Event-ID`.
 */

function frame(
  seq: number,
  name: EventName,
  data: Record<string, unknown> = {},
): RunEvent {
  return { seq, name, data };
}

function applyAll(
  state: RunEventsState,
  frames: readonly RunEvent[],
): RunEventsState {
  return frames.reduce(
    (acc: RunEventsState, one: RunEvent) => runEventsReducer(acc, one),
    state,
  );
}

/**
 * A short gate run, in the shape the mock SSE handler emits it.
 *
 * Deliberately not imported from the mocks: the fold's contract is the frame,
 * not the fixture, and a test that reads its own expectations out of the thing
 * under test proves nothing.
 */
const SCRIPT: readonly RunEvent[] = [
  frame(1, "run.started", { run_id: "r", mode: "gate", pack: "example" }),
  frame(2, "trial.started", { probe_id: "grounding-work-history", epoch: 1 }),
  frame(3, "turn.sent", { probe_id: "grounding-work-history", epoch: 1, turn: 1 }),
  frame(4, "turn.received", {
    probe_id: "grounding-work-history",
    epoch: 1,
    turn: 1,
  }),
  frame(5, "probe.scored", { probe_id: "grounding-work-history", pass_k: 1.0 }),
  frame(6, "spend.updated", { judge_usd: 0.01377 }),
  frame(7, "artifact.written", { run_id: "r" }),
  frame(8, "run.finished", { run_id: "r", exit_code: 1 }),
];

describe("runEventsReducer", () => {
  it("folds a run's events in seq order", () => {
    const state = applyAll(initialRunEventsState, SCRIPT.slice(0, 7));

    expect(state.lastSeq).toBe(7);
    expect(state.phase).toBe("running");
    expect(state.connection).toBe("open");
    expect(state.trials).toBe(1);
    expect(state.judgeUsd).toBeCloseTo(0.01377, 5);
    expect(state.artifactWritten).toBe(true);
    expect(state.probes).toEqual([
      { probeId: "grounding-work-history", passK: 1 },
    ]);
    expect(state.missedEvents).toBe(0);
  });

  /**
   * The property the replay endpoint makes mandatory. Folding the same history
   * twice must land exactly where folding it once did — and the once-folded
   * state must not be the initial one, or a reducer that ignores every event
   * would satisfy this by doing nothing.
   */
  it("is idempotent under a full replay of the same history", () => {
    const once = applyAll(initialRunEventsState, SCRIPT);
    const twice = applyAll(once, SCRIPT);

    expect(once).not.toEqual(initialRunEventsState);
    expect(twice).toEqual(once);
  });

  it("returns the state untouched for an event it has already seen", () => {
    const state = applyAll(initialRunEventsState, SCRIPT.slice(0, 6));
    // A stale spend figure replayed after a newer one must not roll the meter
    // backwards, and the identity check proves nothing was rebuilt either.
    const replayed = runEventsReducer(state, frame(6, "spend.updated", {
      judge_usd: 0.00001,
    }));

    expect(replayed).toBe(state);
    expect(replayed.judgeUsd).toBeCloseTo(0.01377, 5);
  });

  it("sets a terminal phase and records the exit code on run.finished", () => {
    const state = applyAll(initialRunEventsState, SCRIPT);

    expect(state.phase).toBe("finished");
    expect(state.exitCode).toBe(1);
    // Terminal means the stream is done: the hook closes it rather than
    // letting the browser reconnect into an endless replay of the same run.
    expect(state.connection).toBe("closed");
  });

  it("will not put a finished run back on the air", () => {
    const finished = applyAll(initialRunEventsState, SCRIPT);
    const late = runEventsReducer(finished, frame(9, "control.paused", {}));

    expect(late.phase).toBe("finished");
    expect(late.lastSeq).toBe(9);
  });

  it("reads a gap in seq as a lost connection, and counts what it missed", () => {
    const state = applyAll(initialRunEventsState, SCRIPT.slice(0, 2));
    const jumped = runEventsReducer(
      state,
      frame(6, "spend.updated", { judge_usd: 0.5 }),
    );

    expect(jumped.connection).toBe("reconnecting");
    expect(jumped.missedEvents).toBe(3);
    // The event that revealed the gap is still real data and still applies.
    expect(jumped.judgeUsd).toBeCloseTo(0.5, 5);
    expect(jumped.lastSeq).toBe(6);
  });

  it("treats the first event of a resumed stream as contiguous", () => {
    const state = applyAll(initialRunEventsState, SCRIPT.slice(0, 4));
    const resumed = runEventsReducer(state, SCRIPT[4]!);

    expect(resumed.connection).toBe("open");
    expect(resumed.missedEvents).toBe(0);
  });

  it("clears the reconnecting flag once contiguous events resume", () => {
    const gapped = runEventsReducer(
      applyAll(initialRunEventsState, SCRIPT.slice(0, 2)),
      frame(6, "spend.updated", { judge_usd: 0.5 }),
    );
    const recovered = runEventsReducer(
      gapped,
      frame(7, "artifact.written", { run_id: "r" }),
    );

    expect(recovered.connection).toBe("open");
    // What was already missed stays missed — the count is a fact about the
    // run, not a spinner that resets itself.
    expect(recovered.missedEvents).toBe(3);
  });

  it("counts a probe once even when it is scored twice", () => {
    const state = applyAll(initialRunEventsState, [
      frame(1, "probe.scored", { probe_id: "injection-exfil", pass_k: null }),
      frame(2, "probe.scored", { probe_id: "injection-exfil", pass_k: 0 }),
    ]);

    expect(state.probes).toEqual([{ probeId: "injection-exfil", passK: 0 }]);
  });

  it("ignores an event name it does not know, but still advances the sequence", () => {
    const state = runEventsReducer(
      initialRunEventsState,
      // A real `EventName` this fold has no rendition for. Unknown is ignored
      // rather than fatal (`types.ts` §4), and the sequence still moves so the
      // next event is not misread as a gap.
      frame(1, "pair.judged", { pair: "a-vs-b" }),
    );

    expect(state.lastSeq).toBe(1);
    expect(state.phase).toBe("connecting");
    expect(state.connection).toBe("open");
  });

  /**
   * Event payload shapes are NOT frozen — Task 18 writes the emit sites, and
   * `models.EventName` freezes only the names. So a field that is absent, or
   * arrives as the wrong type, must leave the readout showing the last figure
   * it actually measured rather than `NaN` or `null`.
   */
  it("leaves a figure alone when the payload does not carry it", () => {
    const spent = applyAll(initialRunEventsState, [
      frame(1, "spend.updated", { judge_usd: 0.25 }),
      frame(2, "spend.updated", {}),
      frame(3, "spend.updated", { judge_usd: "0.99" }),
    ]);

    expect(spent.judgeUsd).toBeCloseTo(0.25, 5);
  });

  /**
   * Found by rendering the finished run in a browser, not by reasoning.
   *
   * The scripted stream ends and the server closes it; `EventSource` reports
   * that teardown through `onerror` with `readyState` still `CONNECTING`,
   * because it is already scheduling the reconnect this hook is about to
   * cancel. The window therefore read **"Reconnecting"** under the word
   * FINISHED — an alarm about a socket that was closed on purpose.
   */
  it("does not raise a reconnect alarm over a run that already finished", () => {
    const finished = applyAll(initialRunEventsState, SCRIPT);
    const teardown = runEventsReducer(finished, { connection: "reconnecting" });

    expect(teardown.connection).toBe("closed");
    expect(teardown.phase).toBe("finished");
  });

  it("takes a connection transition without touching the sequence", () => {
    const state = applyAll(initialRunEventsState, SCRIPT.slice(0, 2));
    const dropped = runEventsReducer(state, { connection: "reconnecting" });

    expect(dropped.connection).toBe("reconnecting");
    expect(dropped.lastSeq).toBe(state.lastSeq);
    expect(dropped.phase).toBe(state.phase);
  });

  it("moves the phase on each control acknowledgement", () => {
    const running = applyAll(initialRunEventsState, SCRIPT.slice(0, 1));
    const paused = runEventsReducer(running, frame(2, "control.paused", {}));
    const resumed = runEventsReducer(paused, frame(3, "control.resumed", {}));
    const cancelling = runEventsReducer(
      resumed,
      frame(4, "control.cancelled", {}),
    );

    expect(running.phase).toBe("running");
    expect(paused.phase).toBe("paused");
    expect(resumed.phase).toBe("running");
    // Not "cancelled": the ack says the engine took the request, and in-flight
    // trials are still finishing — and still spending. `run.finished` is what
    // says it stopped.
    expect(cancelling.phase).toBe("cancelling");
  });
});
