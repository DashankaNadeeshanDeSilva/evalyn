import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * The one dangerous key.
 *
 * Safety orange is rationed, by the surface brief, to actions that **spend
 * money or interrupt work** — launch and cancel, and nothing else in the whole
 * interface. This component exists so that ration is a fact about the codebase
 * rather than a rule people remember: the orange lives in exactly one file, and
 * a `grep` for its importers is the complete list of dangerous actions.
 *
 * There is **one primary dangerous action per screen**: LAUNCH on the launch
 * console, CANCEL inside the live readout window. Two orange keys on one screen
 * means the ration has been spent and the direction has been broken.
 *
 * ## Measured by hand, because the guard cannot see this key
 *
 * The contrast guard reasons per file and this key is rendered inside two very
 * different grounds — the pale chassis on the launch console, and the dark
 * inset readout window on the run page. It paints its own opaque ground across
 * its full extent in both, so no ink here ever meets the ground behind it,
 * which is why the inventory names its own resting fill as what it inherits.
 *
 *   safety-ink on safety orange        6.05:1   the label       (AA text)
 *   safety-ink on chassis-200         12.90:1   never rendered — the disabled
 *                                               rendition replaces the label
 *   chassis-500 on chassis-200         3.17:1   the disabled label (1.4.3)
 *   safety orange on the inset window  6.44:1   the key's own edge against the
 *                                               dark field it sits in (1.4.11)
 *   safety orange on chassis-25        2.71:1   the same edge on the pale face
 *
 * That last number is why the key carries a word and a glyph and is never
 * identified by its fill: 2.71 clears nothing, and an operator who cannot
 * distinguish the orange still reads CANCEL.
 *
 * **White on orange is refused** — it measures 2.36:1 and is the default this
 * palette was built to avoid. The ink is near-black.
 */
type SafetyKeyProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "className" | "children"
> & {
  children: ReactNode;
  /**
   * Why the key is refusing, when it is disabled. Announced, because a disabled
   * control is out of the tab order and its `title` is not read reliably — and
   * because a dangerous action that refuses without saying why is worse than
   * one that refuses loudly.
   */
  refusal?: string;
};

export function SafetyKey({
  children,
  disabled = false,
  refusal,
  type = "button",
  ...rest
}: SafetyKeyProps) {
  return (
    <button
      type={type}
      disabled={disabled}
      data-testid="safety-key"
      data-armed={disabled ? "false" : "true"}
      /*
       * A hard rectangle: no radius, no shadow, no bevel, no gradient. The
       * bench supplies vocabulary and hierarchy, never texture.
       *
       * Hover and press draw a rule *inside* the key in its own ink rather than
       * shifting the fill. A hue shift would need a second orange the palette
       * deliberately does not define, and a shadow is the pastiche this world
       * refuses outright. The rule appears instantly: a key snapping to a
       * discrete position is the signature interaction, and a fading edge is
       * exactly the fuzzy intermediate state it exists to avoid.
       */
      className={`inline-flex items-center gap-2 px-4 py-2 text-legend font-semibold uppercase tracking-legend ${
        disabled
          ? "cursor-not-allowed bg-chassis-200 text-chassis-500"
          : "bg-safety text-safety-ink hover:outline hover:outline-2 hover:outline-safety-ink hover:outline-offset-[-4px] active:outline-offset-[-6px]"
      }`}
      {...rest}
    >
      {children}
      {disabled && refusal ? (
        <span className="sr-only">{` — ${refusal}`}</span>
      ) : null}
    </button>
  );
}
