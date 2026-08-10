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

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => server.close());
