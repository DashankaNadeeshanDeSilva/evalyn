import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Vite config for the Evalyn cockpit SPA.
 *
 * Three settings here are load-bearing and must not be changed casually — the
 * built bundle is **committed to the repository** and shipped inside the Python
 * wheel, so every byte of build output is code review surface:
 *
 * - `base: "./"` — the SPA is served from a `StaticFiles` mount under whatever
 *   prefix `evalyn ui` picks. Absolute `/assets/...` URLs would 404 the moment
 *   the mount is not the server root.
 * - `build.sourcemap: false` — sourcemaps are the single biggest source of
 *   cross-machine diff noise in a committed bundle (absolute paths, differing
 *   line offsets). A reviewer must be able to read the diff.
 * - `build.outDir: "../src/evalyn/ui/static"` with `emptyOutDir: true` — the
 *   bundle lands directly in the Python package, so `hatchling` picks it up
 *   with no copy step. `static/` is deliberately **not** gitignored: hatchling
 *   respects `.gitignore` and would otherwise ship an empty directory.
 *
 * `publicDir` is switched off for `build` on purpose. The only thing in
 * `public/` is MSW's generated service worker, which is a development mock and
 * has no business inside a released wheel.
 */
export default defineConfig(({ command }) => ({
  base: "./",
  plugins: [react()],
  publicDir: command === "serve" ? "public" : false,
  build: {
    outDir: "../src/evalyn/ui/static",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      // `npm run dev` talks to a real `evalyn ui --port 8765` when one is
      // running; MSW handles the requests when one is not.
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
}));
