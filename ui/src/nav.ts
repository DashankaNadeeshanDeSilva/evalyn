/**
 * The legend strip's destination registry.
 *
 * `shipped` is a field rather than a hand-edited list of links because a legend
 * that names destinations which 404 reads as broken hardware — a hard
 * requirement of the surface brief, not a nicety. The strip renders exactly the
 * shipped entries, so the six-item plan lives here in full, visible, and
 * inactive until its page exists.
 *
 * **Flipping a flag is half the change.** `AppShell.test.tsx` asserts
 * `shipped` is true if and only if the router resolves a real page for that
 * path, so a flag flipped without a route reds, and a route added without the
 * flag reds too. Later tasks (9 · 15 · 16 · 17 · 20) land their page and flip
 * their flag in the same commit; nobody edits the strip's markup.
 *
 * Order is the operator's reading order, not the build order: what you look at,
 * then what you start, then what came out of it.
 */
export interface NavDestination {
  /** The route path, matched against the router's own table. */
  path: string;
  /** The legend text. Rendered uppercase in CSS, so this stays readable. */
  label: string;
  /** Does a real page answer `path` today? */
  shipped: boolean;
}

export const NAV_DESTINATIONS: readonly NavDestination[] = [
  { path: "/runs", label: "Runs", shipped: true },
  { path: "/launch", label: "Launch", shipped: true },
  { path: "/discoveries", label: "Discoveries", shipped: false },
  { path: "/compare", label: "Compare", shipped: false },
  { path: "/trends", label: "Trends", shipped: true },
  { path: "/trust", label: "Judge Trust", shipped: false },
];

export function shippedDestinations(): NavDestination[] {
  return NAV_DESTINATIONS.filter((destination) => destination.shipped);
}
