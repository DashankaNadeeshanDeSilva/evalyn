import type { Config } from "tailwindcss";

/**
 * Tailwind v3 (not v4) is deliberate: the task brief specifies a
 * `tailwind.config.ts`, which is the v3 shape. v4 is CSS-first and would move
 * this file's contents into `index.css`. Six later tasks build pages against
 * this scaffold, so the conservative, best-documented major wins.
 *
 * The palette below is the cockpit's semantic vocabulary. Status colours are
 * named after `RunStatus` members, not after hues, so a component reads
 * `bg-status-gate_failed` and cannot drift from the enum.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
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
    },
  },
  plugins: [],
} satisfies Config;
