import { setupServer } from "msw/node";

import { handlers } from "./handlers";

/** The Node-side mock API, started once per Vitest run by `src/test/setup.ts`. */
export const server = setupServer(...handlers);
