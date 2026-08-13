/**
 * A key that snaps to one of a closed set of positions.
 *
 * This is the surface's **signature interaction** — controls behave like
 * knurled hardware, snapping to discrete positions with one short, confident
 * transition and no intermediate rendition. It lives here rather than inside
 * one page because a signature that exists twice is not a signature: the launch
 * console's mode selector and the trends page's metric and pack selectors are
 * the same control, and the day one of them grows a hover state the other one
 * does not, the world has quietly split in two.
 *
 * `disabled` + `reason` is the launch console's case — a mode this server
 * cannot run is *shown*, refused, and says why, the same rule the legend strip
 * follows for unshipped destinations. A selector whose every position is
 * reachable simply omits both.
 */
export function Detent({
  selected,
  disabled = false,
  reason = null,
  onClick,
  children,
}: {
  selected: boolean;
  disabled?: boolean;
  reason?: string | null;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      data-testid="detent"
      data-value={children}
      aria-pressed={selected}
      disabled={disabled}
      title={reason ?? `Select ${children}`}
      /*
       * The scenario table's key shape, reused rather than reinvented: the
       * engraved rule beneath is the control's only boundary, and the position
       * is discrete — there is no intermediate rendition between two modes.
       *
       * The rule is measured by hand; the contrast guard reads `text-` and
       * `bg-` prefixes only and cannot see a rule set this way (R4-24). On the
       * face at chassis-25: chassis-900 16.37 (selected and hover),
       * chassis-500 4.03 (resting, >= 3:1 for a graphical object),
       * chassis-300 1.55 (disabled, the 1.4.3 inactive-control exemption).
       */
      className={`engrave-b px-3 py-2 text-legend uppercase tracking-legend transition-colors duration-state ${
        disabled
          ? "cursor-not-allowed text-chassis-500 [--rule:theme(colors.chassis.300)]"
          : selected
            ? "text-chassis-900 [--rule:theme(colors.chassis.900)]"
            : "text-chassis-700 hover:text-chassis-900 [--rule:theme(colors.chassis.500)] hover:[--rule:theme(colors.chassis.900)]"
      }`}
      onClick={onClick}
    >
      {children}
      {disabled && reason ? (
        // A disabled control is out of the tab order and its `title` is not
        // announced reliably, so the reason travels as text too.
        <span className="sr-only">{` — ${reason}`}</span>
      ) : null}
    </button>
  );
}
