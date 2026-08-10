import { NavLink, Outlet } from "react-router-dom";

import { useMeta } from "../api/client";
import { shippedDestinations } from "../nav";
import { RedactionBanner } from "./RedactionBanner";

/**
 * The instrument's chassis: a thin legend strip over one continuous face.
 *
 * Explicitly **not** a sidebar. A left nav that owns a third of the projector
 * spends the surface's most valuable region on six words that never change,
 * and it puts navigation above the run history in the visual hierarchy when the
 * operator came here for the history. The strip is the height of one legend and
 * then gets out of the way.
 *
 * Only shipped destinations appear (see `nav.ts`). The strip's right edge
 * carries the server's own identifying legend — version and the runs directory
 * this cockpit is serving — which is the one thing that tells an operator with
 * two terminals open which one they are looking at.
 */
export function AppShell() {
  const meta = useMeta();
  const destinations = shippedDestinations();

  return (
    <div className="min-h-screen bg-chassis-25 font-mono text-chassis-900">
      <header className="engrave-b rule-major bg-chassis-50">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-2 px-4 py-2.5 sm:px-6">
          <span className="text-panel font-semibold uppercase leading-none">
            Evalyn
          </span>

          <nav aria-label="Cockpit sections">
            <ul className="flex items-center gap-6">
              {destinations.map((destination) => (
                <li key={destination.path}>
                  <NavLink
                    to={destination.path}
                    className={({ isActive }) =>
                      [
                        // The marker sits at a position rather than sliding
                        // between them; only its ink transitions.
                        "block border-b-2 pb-0.5 text-legend uppercase transition-colors duration-state",
                        isActive
                          ? "border-chassis-900 text-chassis-900"
                          : "border-transparent text-chassis-600 hover:text-chassis-900",
                      ].join(" ")
                    }
                  >
                    {destination.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>

          <p
            data-testid="meta-legend"
            className="ml-auto flex items-center gap-2 text-legend tracking-normal text-chassis-600"
          >
            {meta.data ? (
              <>
                <span className="tabular-nums">v{meta.data.version}</span>
                <span aria-hidden="true" className="text-chassis-400">
                  ·
                </span>
                {/* A display-safe label with $HOME collapsed to `~`. Never a
                    real path: never joined onto anything, never sent back. */}
                <span className="break-all">{meta.data.runs_dir}</span>
              </>
            ) : meta.isError ? (
              <span className="text-status-unreadable">server unreachable</span>
            ) : (
              <span className="text-chassis-500">reading server…</span>
            )}
          </p>
        </div>
      </header>

      {meta.data ? <RedactionBanner redaction={meta.data.redaction} /> : null}

      <main>
        <Outlet />
      </main>
    </div>
  );
}
