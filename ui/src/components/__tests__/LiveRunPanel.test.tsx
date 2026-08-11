import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../../api/client";
import type { EventName, RunStatus } from "../../api/types";
import { RUN_ID_GATE } from "../../mocks/fixtures";
import { LiveRunPanel } from "../LiveRunPanel";

/**
 * The seam: a real socket's events, folded into the one inset window.
 *
 * ## Why there is a fake here at all
 *
 * **jsdom ships no `EventSource`** — `typeof window.EventSource` is `undefined`
 * under the pinned jsdom 29 — so this is not a case of preferring a double to
 * the real thing. Without one, the only untested code on the live path would be
 * exactly the part most likely to be wrong: named SSE events never reach
 * `onmessage`, so a listener registered the obvious way receives nothing at all
 * and the window sits silent forever while the run completes.
 *
 * The fake implements only what the hook actually uses, and nothing it does not:
 * construction with a URL, `addEventListener` by event name, `close()`, and a
 * `readyState` with the one constant the error branch reads.
 *
 * ## DEFERRED — owed to Tasks 18, 19 and 20
 *
 * No real event stream exists yet. Against a live `evalyn ui`, the wiring pass
 * must verify: that `id:` carries the sink's `seq`; that a reconnect resumes at
 * `Last-Event-ID + 1` rather than replaying from 1; that the payload keys the
 * fold reads are the keys the emit sites write; and that a `control.*` ack
 * actually follows its 202. The list is enumerated in full at the head of
 * `hooks/useRunEvents.ts` and `components/LiveRunPanel.tsx`.
 */

type Frame = MessageEvent<string>;

class FakeEventSource {
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = 0;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private readonly listeners = new Map<string, ((event: Frame) => void)[]>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, handler: (event: Frame) => void) {
    const existing = this.listeners.get(name) ?? [];
    this.listeners.set(name, [...existing, handler]);
  }

  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  /** One server frame: `id:` is the seq, exactly as the sink writes it. */
  emit(seq: number, name: EventName, data: Record<string, unknown>) {
    const frame = new MessageEvent(name, {
      data: JSON.stringify(data),
      lastEventId: String(seq),
    }) as Frame;
    act(() => {
      for (const handler of this.listeners.get(name) ?? []) handler(frame);
    });
  }
}

const realEventSource = globalThis.EventSource;

beforeEach(() => {
  FakeEventSource.instances = [];
  (globalThis as { EventSource?: unknown }).EventSource = FakeEventSource;
});

afterEach(() => {
  (globalThis as { EventSource?: unknown }).EventSource = realEventSource;
});

function renderPanel(status: RunStatus) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <LiveRunPanel runId={RUN_ID_GATE} status={status} />
    </QueryClientProvider>,
  );
}

function socket(): FakeEventSource {
  const one = FakeEventSource.instances[0];
  expect(one, "nothing subscribed to the run's event stream").toBeDefined();
  return one!;
}

describe("the live run panel", () => {
  it("subscribes to the run's own stream while a process is attached", () => {
    renderPanel("running");

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(socket().url).toBe(
      `/api/runs/${encodeURIComponent(RUN_ID_GATE)}/events`,
    );
    expect(screen.getByTestId("live-window")).toBeInTheDocument();
  });

  it("opens no socket, and shows no window, for a run that already ended", () => {
    renderPanel("passed");

    expect(FakeEventSource.instances).toHaveLength(0);
    expect(screen.queryByTestId("live-window")).toBeNull();
  });

  /**
   * The bug this test exists for: `EventSource` dispatches `event: run.started`
   * to a listener registered for that exact name and **never** to `onmessage`.
   * A hook that only sets `onmessage` compiles, runs, and reports nothing.
   */
  it("folds named frames into the readout", () => {
    renderPanel("running");

    socket().emit(1, "run.started", { run_id: RUN_ID_GATE, mode: "gate" });
    socket().emit(2, "trial.started", { probe_id: "grounding", epoch: 1 });
    socket().emit(3, "spend.updated", { judge_usd: 0.0138 });
    socket().emit(4, "probe.scored", { probe_id: "grounding", pass_k: 1 });

    const window = screen.getByTestId("live-window");
    expect(window.getAttribute("data-phase")).toBe("running");
    expect(window.querySelector('[data-numeric="judge_usd"]')?.textContent).toBe(
      "$0.0138",
    );
    expect(
      window.querySelector('[data-numeric="probes_scored"]')?.textContent,
    ).toBe("1");
    expect(screen.getByTestId("live-activity").textContent).toContain(
      "grounding",
    );
  });

  /**
   * A server that closes a finished stream looks, to `EventSource`, exactly
   * like a dropped connection: it reconnects, gets the whole history replayed,
   * and does it again forever. Closing on a terminal phase is the only thing
   * that stops that.
   */
  it("closes the socket when the run ends", () => {
    renderPanel("running");

    socket().emit(1, "run.started", { run_id: RUN_ID_GATE });
    expect(socket().closed).toBe(false);

    socket().emit(2, "run.finished", { run_id: RUN_ID_GATE, exit_code: 1 });

    expect(socket().closed).toBe(true);
    expect(screen.getByTestId("live-window").getAttribute("data-phase")).toBe(
      "finished",
    );
    // No second subscription — the point of closing is that nothing reconnects.
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  /**
   * "It appears only when something is actually running **or has just
   * finished**." The refetch fired on `artifact.written` flips the run's status
   * to a terminal one, and a window that re-read that status would vanish in
   * the same frame the run ended — taking the exit code with it.
   */
  it("stays on screen after the run it was watching ends", () => {
    const view = renderPanel("running");

    socket().emit(1, "run.finished", { run_id: RUN_ID_GATE, exit_code: 0 });
    view.rerender(
      <QueryClientProvider client={createQueryClient()}>
        <LiveRunPanel runId={RUN_ID_GATE} status="passed" />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("live-window")).toBeInTheDocument();
    expect(screen.getByTestId("live-window").getAttribute("data-phase")).toBe(
      "finished",
    );
  });

  it("does not believe its own 202 — the control event is the acknowledgement", async () => {
    const user = userEvent.setup();
    renderPanel("running");
    socket().emit(1, "run.started", { run_id: RUN_ID_GATE });

    await user.click(
      screen.getByRole("button", { name: /Pause \(finishes in-flight trials\)/ }),
    );

    // The mock answers 202 `accepted: true` immediately. The window must still
    // read `running`, and say it is waiting.
    await waitFor(() =>
      expect(screen.getByTestId("control-waiting").textContent).toContain(
        "waiting for the engine to acknowledge",
      ),
    );
    expect(screen.getByTestId("live-window").getAttribute("data-phase")).toBe(
      "running",
    );

    socket().emit(2, "control.paused", {});

    expect(screen.getByTestId("live-window").getAttribute("data-phase")).toBe(
      "paused",
    );
    expect(screen.queryByTestId("control-waiting")).toBeNull();
    expect(screen.getByRole("button", { name: /Resume/ })).toBeInTheDocument();
  });
});
