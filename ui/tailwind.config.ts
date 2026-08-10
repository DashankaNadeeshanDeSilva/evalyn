import type { Config } from "tailwindcss";

/**
 * Tailwind v3 (not v4) is deliberate: the task brief specifies a
 * `tailwind.config.ts`, which is the v3 shape. v4 is CSS-first and would move
 * this file's contents into `index.css`. Six later tasks build pages against
 * this scaffold, so the conservative, best-documented major wins.
 *
 * The palette below is the cockpit's semantic vocabulary — THE BENCH INSTRUMENT
 * (`.impeccable/surfaces/ui-src.md`). Status colours are named after `RunStatus`
 * members, not after hues, so a component reads `text-status-gate_failed` and
 * cannot drift from the enum.
 *
 * ## Measured, not assumed
 *
 * Every value that carries text was measured against WCAG 2.1 AA on the page
 * field `chassis-25 (#fafbfc)`, which is the only ground status text sits on:
 *
 *   chassis-900 16.37   chassis-800 12.54   chassis-700  8.70   chassis-600 5.98
 *   status-passed 4.84  gate_failed  6.24   invalid      4.75   running     6.47
 *   paused        6.86  cancelled    7.54   interrupted  5.00   failed_to_start 7.74
 *   unreadable    4.58
 *
 * Two consequences are load-bearing and must survive later edits:
 *
 * - **`chassis-500` measures 4.03 and is therefore NOT a body-text colour.**
 *   Secondary prose uses `chassis-600` (5.98). 400/500 are for rules, icons and
 *   disabled affordances only.
 * - **Status text may only sit on `chassis-25`.** `status-unreadable` drops to
 *   4.34 on `chassis-50`, so table rows keep the lightest ground and the tinted
 *   `chassis-50` is reserved for the legend strip and column headers, which
 *   carry no status ink.
 *
 * ## Cool, and provably so
 *
 * The direction bans the warm-neutral band (cream, sand, bone, parchment) by
 * name. Every step of the ramp has B >= G >= R with a 2-13 point blue-over-red
 * delta, which is what makes it read cool at near-zero chroma. A step whose red
 * channel climbs above its blue has left the world.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        /**
         * The instrument chassis. One continuous face, divided by engraved
         * panel lines — `chassis-300` for a minor rule, `chassis-400` for a
         * major division. Never a card border, never a shadow.
         */
        chassis: {
          25: "#fafbfc",
          50: "#f3f5f6",
          100: "#e9ecee",
          200: "#dde1e4",
          300: "#c8cdd1",
          400: "#a2a9ae",
          500: "#767d83",
          600: "#5b6268",
          700: "#434a4f",
          800: "#2c3236",
          900: "#191d20",
        },
        /**
         * The one inset window: the single dark, recessed field that carries
         * LIVE state. RESERVED — it appears only when a run is actually
         * running, which is Task 21's live view. Nothing in Task 8 uses it, and
         * it must not become a decorative slab.
         */
        inset: {
          DEFAULT: "#12171a",
          ink: "#e9ecee",
          rule: "#2c3236",
        },
        /**
         * Safety orange. RESERVED, exclusively, for actions that spend money or
         * interrupt work — launch and cancel. Nothing else in the interface may
         * use it, and Task 8 carries no such action, so Task 8 uses no orange
         * at all. Rendered as a filled key with near-black ink on top:
         * white-on-orange typically fails AA.
         */
        safety: {
          DEFAULT: "#f97316",
          ink: "#191d20",
        },
        status: {
          passed: "#15803d",
          gate_failed: "#b91c1c",
          invalid: "#a16207",
          running: "#1d4ed8",
          paused: "#6d28d9",
          cancelled: "#525252",
          interrupted: "#c2410c",
          failed_to_start: "#9f1239",
          unreadable: "#737373",
        },
        // Degraded rows are greyed, never hidden — the row still carries a
        // real run_id, created_at and mode.
        //
        // Measures 2.43:1 on chassis-25, so it is never text and never the sole
        // carrier of meaning. Its only use is the flat-line stroke drawn
        // through a dead readout, which is redundant beside the DEGRADED chip
        // and the stated reason next to it.
        degraded: "#a3a3a3",
      },
      fontFamily: {
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        // A fixed rem scale, not a fluid one: an operator reads this at a
        // consistent DPI, and the 2026-08-14 projection constrains scale
        // upward rather than making it responsive.
        legend: ["0.75rem", { lineHeight: "1rem", letterSpacing: "0.12em" }],
        readout: ["0.875rem", { lineHeight: "1.25rem" }],
        panel: ["1rem", { lineHeight: "1.5rem", letterSpacing: "0.14em" }],
      },
      transitionDuration: {
        // Motion is state change, not decoration: one short, confident
        // transition, the detent snapping into position.
        detent: "160ms",
      },
    },
  },
  plugins: [],
} satisfies Config;
