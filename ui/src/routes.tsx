import { Link, Navigate, type RouteObject } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";

/**
 * The router's table — and the other half of the legend strip's gate.
 *
 * `nav.ts` says which destinations exist; this file says which ones a page
 * actually answers, and `AppShell.test.tsx` asserts the two agree. Adding a
 * page here without flipping its `shipped` flag reds, and flipping the flag
 * without adding the page reds too, so the strip cannot advertise a 404 in
 * either direction.
 *
 * The catch-all is last and deliberately says what happened rather than
 * inventing a destination.
 */
function NoSuchPage() {
  return (
    <section className="px-4 py-8 sm:px-6">
      <h1 className="text-display uppercase tracking-display">No such page</h1>
      <p className="mt-2 text-readout text-chassis-600">
        The cockpit has no view at this address.{" "}
        <Link
          to="/runs"
          className="text-chassis-900 underline decoration-chassis-400 underline-offset-4"
        >
          Back to runs
        </Link>
        .
      </p>
    </section>
  );
}

export const appRoutes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      // The cockpit's front door is the history, not a dashboard.
      { index: true, element: <Navigate to="/runs" replace /> },
      { path: "/runs", element: <RunsPage /> },
      { path: "/runs/:runId", element: <RunDetailPage /> },
      { path: "*", element: <NoSuchPage /> },
    ],
  },
];
