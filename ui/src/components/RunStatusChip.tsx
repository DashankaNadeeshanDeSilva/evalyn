import type { RunStatus } from "../api/types";
import { StatusIcon } from "./InstrumentIcon";

/**
 * A run's state, as glyph AND word AND colour — never colour alone.
 *
 * That rule is load-bearing rather than decorative here: this product's central
 * output is a pass/fail verdict and red/green is the most common colourblind
 * failure pair. Strip the colour from this chip and it still reads correctly.
 *
 * The word is the `RunStatus` member **verbatim** in the DOM, uppercased only
 * in CSS. An operator reading the cockpit and an operator reading the artifact
 * JSON see the same token, and a test can assert against the enum rather than
 * against a display string that would drift from it.
 */

/**
 * Ink per status member, written out in full because Tailwind reads source
 * text: a computed `text-status-${status}` would emit no CSS at all and every
 * chip would render in the inherited ink. Being a `Record<RunStatus, string>`
 * also makes a new enum member a compile error rather than a silent black chip.
 *
 * All nine measure >= 4.5:1 on `chassis-25`, which is why status ink is only
 * ever placed on the lightest chassis step (see `tailwind.config.ts`).
 */
const STATUS_INK: Record<RunStatus, string> = {
  passed: "text-status-passed",
  gate_failed: "text-status-gate_failed",
  invalid: "text-status-invalid",
  running: "text-status-running",
  paused: "text-status-paused",
  cancelled: "text-status-cancelled",
  interrupted: "text-status-interrupted",
  failed_to_start: "text-status-failed_to_start",
  unreadable: "text-status-unreadable",
};

export function RunStatusChip({
  status,
  unverified = false,
}: {
  status: RunStatus;
  /**
   * This status survived a salvage read and is not fully trusted: show it, but
   * withdraw the colour claim.
   *
   * Named for the **fact**, not the presentation. It was `muted` first, which
   * described what the pixels do rather than what is true — and as Tasks 15, 16
   * and 17 acquire their own reported-but-unverified states, a boolean called
   * `muted` accretes unrelated meanings until it means "grey" and nothing else.
   *
   * Used on a degraded row, where `status` survived the salvage read but the
   * artifact behind it did not fully parse. A saturated green `✓ passed`
   * sitting on a row whose readouts are flat-lined is the single most
   * misreadable thing this page could show — especially on a projector, where
   * a green tick is what the room sees first. Muted, the fact is still stated
   * and still carries glyph and word; only the emphasis is withdrawn.
   *
   * `chassis-600` measures 5.98:1, so nothing is traded for the honesty.
   */
  unverified?: boolean;
}) {
  return (
    <span
      data-testid="status-chip"
      className={`inline-flex items-center gap-1.5 whitespace-nowrap text-legend uppercase tracking-legend ${
        unverified ? "text-chassis-600" : STATUS_INK[status]
      }`}
    >
      <StatusIcon status={status} className="h-4 w-4 shrink-0" />
      {status}
    </span>
  );
}
