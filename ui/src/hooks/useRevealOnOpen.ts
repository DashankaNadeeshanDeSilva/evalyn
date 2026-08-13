import { useEffect, useRef } from "react";

/**
 * Bring a panel that just opened to the operator, and hand it focus.
 *
 * The trial drill-down keys sit on a probe row; the panels they open render
 * below the *whole* probe table. Measured in a live rehearsal: the clicked row
 * at document top 2258, the panel's heading at 2822, viewport 891px — so on any
 * ordinary viewport the panel opened past the bottom edge, nothing scrolled,
 * and focus stayed on the page root. Clicking appeared to do nothing, and a
 * screen reader was told nothing at all.
 *
 * Both halves matter and neither substitutes for the other:
 *
 * - **Into view**, because the answer to the operator's click is 500px below
 *   the fold and they have no reason to look there.
 * - **Focus**, because that is the only thing that says "the panel is now the
 *   thing you are reading" to anyone not watching the pixels — and it also puts
 *   the keyboard inside the new region rather than back at the top of the page.
 *
 * `focus()` is asked not to scroll so that the one scroll performed is this
 * one, with the behaviour chosen below rather than the user agent's.
 *
 * ## Why the media query is read here rather than left to CSS
 *
 * `index.css` already forces `scroll-behavior: auto` under reduced motion, and
 * it does not reach this: a `behavior` passed to `scrollIntoView` overrides the
 * computed `scroll-behavior` by specification. So an operator who asked for no
 * animation would get 500px of animated travel anyway. The preference is read
 * directly, and `matchMedia` is optional because a non-browser host may not
 * have it — including the test environment, where jsdom ships none.
 *
 * `key` is what re-opens the panel: pass the identity of what is being shown,
 * not a boolean. The single-trial panel is **not remounted** when the operator
 * moves from trial 1 to trial 4 — same component, same position, one changed
 * prop — so a mount-only reveal would fire once and then stay silent for every
 * later key on the row, which is the more common gesture.
 */
export function useRevealOnOpen(key: string) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const panel = ref.current;
    if (panel === null) return;
    panel.focus({ preventScroll: true });
    panel.scrollIntoView({
      block: "start",
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }, [key]);

  return ref;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}
