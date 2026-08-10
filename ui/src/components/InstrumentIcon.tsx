import type { ReactElement, ReactNode, SVGProps } from "react";

import type { RunStatus } from "../api/types";

/**
 * The cockpit's icon family — authored, not borrowed and not typed.
 *
 * One family, one grid, one stroke weight. Every glyph is drawn on a 16x16
 * viewBox, inscribed in a 12px optical circle, stroked at 1.5 in `currentColor`
 * with round caps and joins, and filled nowhere. That uniformity is the whole
 * point: a status column where one mark is heavier than its neighbour reads as
 * two instruments bolted together.
 *
 * Deliberately NOT unicode. `✓ ✗ ⚠ ●` would have been quicker, but `⚠` and `●`
 * carry emoji presentation on several platforms, which lands a colour cartoon
 * in the middle of a monochrome instrument face and hands the operator a glyph
 * whose weight and size the design does not control. The surface brief settles
 * this directly: one family, one stroke weight, SVG only, never emoji.
 *
 * Colour is never applied here — the caller owns it via `currentColor`, so the
 * status-keyed ink and the glyph can never disagree.
 */

type IconProps = Omit<SVGProps<SVGSVGElement>, "children" | "viewBox"> & {
  /**
   * An accessible name for the rare mark that stands alone. Omit it and the
   * glyph is `aria-hidden`, which is the right default: every icon in this
   * build sits beside its own word.
   */
  title?: string;
};

function Glyph({ title, children, ...rest }: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      // Decorative by default: every icon in this build sits beside its own
      // word, so the accessible name lives in the text, never in the mark.
      aria-hidden={title ? undefined : true}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

/** ✓ — the gate held. */
function IconCheck(props: IconProps) {
  return (
    <Glyph {...props}>
      <path d="M3 8.4 6.2 11.6 13 4.6" />
    </Glyph>
  );
}

/** ✗ — the gate failed. Deliberately the heaviest mark in the set. */
function IconCross(props: IconProps) {
  return (
    <Glyph {...props}>
      <path d="M4 4 12 12M12 4 4 12" />
    </Glyph>
  );
}

/** A ruled triangle — the artifact completed but means nothing. */
function IconAlert(props: IconProps) {
  return (
    <Glyph {...props}>
      <path d="M8 2.2 14.6 13.4H1.4Z" />
      <path d="M8 6.4v2.6" />
      <path d="M8 11.4h.01" />
    </Glyph>
  );
}

/** A live dot inside its ring — something is happening right now. */
function IconLive(props: IconProps) {
  return (
    <Glyph {...props}>
      <circle cx="8" cy="8" r="5.6" />
      <circle cx="8" cy="8" r="1.9" fill="currentColor" stroke="none" />
    </Glyph>
  );
}

/** Two bars — held, and (per the product) still billing. */
function IconPause(props: IconProps) {
  return (
    <Glyph {...props}>
      <path d="M6 3.8v8.4M10 3.8v8.4" />
    </Glyph>
  );
}

/** A struck circle — stopped on purpose. */
function IconBarred(props: IconProps) {
  return (
    <Glyph {...props}>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M4.1 11.9 11.9 4.1" />
    </Glyph>
  );
}

/** A broken trace — it vanished mid-flight. */
function IconBreak(props: IconProps) {
  return (
    <Glyph {...props}>
      <path d="M1.6 8h3.2l1.6-3.4 2 8 1.6-4.6h4.4" />
    </Glyph>
  );
}

/** A circled cross — it never got started at all. */
function IconAborted(props: IconProps) {
  return (
    <Glyph {...props}>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M6.1 6.1 9.9 9.9M9.9 6.1 6.1 9.9" />
    </Glyph>
  );
}

/** A queried page — the bytes are there, this build cannot read them. */
function IconUnreadable(props: IconProps) {
  return (
    <Glyph {...props}>
      <path d="M3.6 2.4h5.2l3.6 3.6v7.6H3.6Z" />
      <path d="M8.8 2.4v3.6h3.6" />
      <path d="M6.6 8.5a1.5 1.5 0 1 1 1.6 1.9v.8" />
      <path d="M8.2 12.3h.01" />
    </Glyph>
  );
}

/**
 * A dead channel: the trace flat-lined between its end stops. This is the mark
 * for a degraded row and for every readout it cannot fill.
 *
 * It breaks the 16x16 grid on purpose, and it is the only mark that does. A
 * flat line inscribed in a square reads as a stray dash at instrument scale —
 * it did, in the first render — because the trace has to be long enough to
 * read as a *span* of nothing rather than as a glyph. Stroke weight, caps and
 * ink are unchanged, so it still belongs to the family.
 */
export function IconFlatline({ title, ...rest }: IconProps) {
  return (
    <svg
      viewBox="0 0 40 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      <path d="M2.5 8h35" />
      <path d="M2.5 4.4v7.2M37.5 4.4v7.2" />
    </svg>
  );
}

/** The redaction mark: a closed shackle over a solid body. */
export function IconRedacted(props: IconProps) {
  return (
    <Glyph {...props}>
      <path d="M5.2 7V5.2a2.8 2.8 0 0 1 5.6 0V7" />
      <rect x="3.4" y="7" width="9.2" height="6.4" rx="0.8" />
    </Glyph>
  );
}

/**
 * One mark per `RunStatus` member, exhaustive by type. Adding a member to the
 * enum without drawing its glyph is a compile error, not a blank column.
 */
const STATUS_GLYPHS: Record<
  RunStatus,
  (props: IconProps) => ReactElement
> = {
  passed: IconCheck,
  gate_failed: IconCross,
  invalid: IconAlert,
  running: IconLive,
  paused: IconPause,
  cancelled: IconBarred,
  interrupted: IconBreak,
  failed_to_start: IconAborted,
  unreadable: IconUnreadable,
};

export function StatusIcon({
  status,
  ...rest
}: IconProps & { status: RunStatus }) {
  const Mark = STATUS_GLYPHS[status];
  return <Mark {...rest} />;
}
