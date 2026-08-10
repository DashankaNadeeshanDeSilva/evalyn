import { NavLink, Outlet } from "react-router-dom";

import { useMeta } from "../api/client";
import { shippedDestinations } from "../nav";
import { IconAlert } from "./InstrumentIcon";
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
 *
 * ## The terminating edge (maintainer ruling R4-19)
 *
 * The face **sits on** the page rather than **being** the page. Without a
 * defined edge, "one continuous instrument face" degrades into "a plain admin
 * page with no container", and the object-ness the direction depends on is
 * carried by nothing at all.
 *
 * The edge is exactly two things: a **max-width** and a **hairline rule**. The
 * darker `chassis-100` ground is the desk; the face is the lighter `chassis-25`
 * panel inset into it, bounded by a 1px `chassis-400` rule on each side — the
 * same major-division weight used everywhere else on the surface.
 *
 * **No bevel, no shadow, no simulated bezel, no rounded corner.** The
 * anti-pastiche rule is absolute: the bench supplies vocabulary and hierarchy,
 * never texture, and a treatment that exists only to look like hardware is cut.
 * A rule and a measure are both.
 *
 * The inset starts at `lg`. Below it the face runs full-bleed, because on a
 * narrow viewport 32px of desk on each side costs legibility and buys nothing —
 * there is no "object on a desk" read to protect at phone width. The 100rem cap
 * is deliberately below the 1440px projection width, so the edge is visible in
 * the room on 2026-08-14 rather than only on an ultrawide monitor.
 *
 * The face keeps `min-h-screen` so the rules run the full height: a panel
 * inserted into the desk, not a card floating on it. That is also why the desk
 * has horizontal padding only — vertical padding here would produce exactly the
 * floating slab the direction refuses.
 */
export function AppShell() {
  const meta = useMeta();
  const destinations = shippedDestinations();

  return (
    <div className="min-h-screen bg-chassis-100 font-mono text-chassis-900 lg:px-8">
      <div className="mx-auto min-h-screen max-w-[100rem] border-x border-chassis-400 bg-chassis-25">
        <header className="engrave-b rule-major bg-chassis-50">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2 px-4 py-2.5 sm:px-6">
            <span className="text-panel font-semibold uppercase leading-none tracking-panel">
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
                          "block border-b-2 pb-0.5 text-legend uppercase tracking-legend transition-colors duration-state",
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
              className="ml-auto flex items-center gap-2 text-legend text-chassis-600"
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
                /*
                 * The previous ink here was wrong twice over.
                 *
                 * It measured 4.34:1 on the strip's `chassis-50` — below AA for
                 * 12px text, and the exact failure `tailwind.config.ts` predicts
                 * by name ("status text may only sit on chassis-25"). It was
                 * also a *vocabulary* error: the status palette is keyed to
                 * `RunStatus` members, and "the server is unreachable" is not a
                 * run state. Borrowing an enum-keyed token for a non-enum
                 * meaning is how the enum stops being the authority.
                 *
                 * `chassis-900` measures 15.51:1 here, and the glyph carries the
                 * alarm so the message is never colour alone.
                 */
                <span className="flex items-center gap-1.5 text-chassis-900">
                  <IconAlert className="h-4 w-4 shrink-0" />
                  server unreachable
                </span>
              ) : (
                // The previous ink was 3.82:1 on this ground. Same rule and
                // same fix as the `gate ` prefix: secondary prose is
                // chassis-600 (5.66:1 here).
                <span className="text-chassis-600">reading server…</span>
              )}
            </p>
          </div>
        </header>

        {meta.data ? <RedactionBanner redaction={meta.data.redaction} /> : null}

        <main>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
