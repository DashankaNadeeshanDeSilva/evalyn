import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "../mocks/server";

/**
 * One MSW server for the whole Vitest run.
 *
 * `onUnhandledRequest: "error"` is the point of the exercise: a component that
 * calls an endpoint nobody mocked fails loudly instead of hanging on a pending
 * promise. Every route in the frozen contract has a handler, so an unhandled
 * request means either a typo in a URL or a route Task 1 never froze — both
 * worth a red.
 */
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));

/**
 * `scrollIntoView`, which jsdom does not ship.
 *
 * jsdom implements no layout, so every scrolling API is absent —
 * `HTMLElement.prototype.scrollIntoView` is `undefined` under the pinned
 * version (probed, not assumed). A real browser always has it, so the
 * production code calls it unguarded and the *environment* supplies it here,
 * exactly as `FakeEventSource` supplies the `EventSource` jsdom also lacks.
 *
 * A no-op is the honest stand-in: there is nothing to scroll. Tests that care
 * spy on it to read back the element and the behaviour it was asked for.
 */
Element.prototype.scrollIntoView = function scrollIntoView() {};

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => server.close());
