import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, useRoutes } from "react-router-dom";

import { createQueryClient } from "./api/client";
import { appRoutes } from "./routes";

/**
 * The application root.
 *
 * `AppRoutes` is exported separately from `App` so tests can mount the real
 * route table inside a `MemoryRouter` at any entry point, without a second,
 * drifting copy of the routes living in the test file.
 */
export function AppRoutes() {
  return useRoutes(appRoutes);
}

/**
 * The query client is created once per `App` instance rather than at module
 * scope: a module-level singleton would share its cache across every mount in a
 * test run, and one test's stale runs list would answer another test's query.
 */
export function App() {
  const [client] = useState(createQueryClient);

  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
