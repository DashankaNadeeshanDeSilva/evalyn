export interface NavDestination { path: string; label: string; shipped: boolean }
export const NAV_DESTINATIONS: readonly NavDestination[] = [
  { path: "/runs", label: "Runs", shipped: false },
  { path: "/launch", label: "Launch", shipped: false },
];
