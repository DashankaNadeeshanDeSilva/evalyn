import { act } from "@testing-library/react";

import type { EventName } from "../api/types";

/**
 * A stand-in for `EventSource`, because jsdom ships none.
 *
 * `typeof window.EventSource` is `undefined` under the pinned jsdom 29, so this
 * is not a case of preferring a double to the real thing — without it the live
 * path has no coverage at all, and the bug it protects against is silent:
 * `EventSource` dispatches `event: run.started` to a listener registered for
 * that exact name and **never** to `onmessage`, so a hook written the obvious
 * way receives nothing while the run completes.
 *
 * It implements only what `useRunEvents` actually uses — construction with a
 * URL, `addEventListener` by event name, `close()`, and the one `readyState`
 * constant the error branch reads — and nothing it does not.
 *
 * Lifted here so the hook test and the page test drive one fake rather than two
 * that can drift apart.
 */

type Frame = MessageEvent<string>;

export class FakeEventSource {
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

/** Installs the fake for one test file. Call at module scope. */
export function useFakeEventSource() {
  beforeEach(() => {
    FakeEventSource.instances = [];
    (globalThis as { EventSource?: unknown }).EventSource = FakeEventSource;
  });

  afterEach(() => {
    (globalThis as { EventSource?: unknown }).EventSource = realEventSource;
  });
}

/** The one socket a test expects to exist, or a named failure. */
export function onlySocket(): FakeEventSource {
  const one = FakeEventSource.instances[0];
  expect(one, "nothing subscribed to the run's event stream").toBeDefined();
  return one!;
}
