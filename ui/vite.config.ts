import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Vite config for the Evalyn cockpit SPA.
 *
 * Three settings here are load-bearing and must not be changed casually — the
 * built bundle is **committed to the repository** and shipped inside the Python
 * wheel, so every byte of build output is code review surface:
 *
 * - `base: "/"` — **absolute asset URLs, and this is load-bearing.**
 *   `server.py` mounts the bundle's assets at `/assets` on the **server root**
 *   (`app.mount("/assets", StaticFiles(...))`), and `evalyn ui` binds
 *   `127.0.0.1` at root with no configurable prefix, so an absolute path is
 *   always correct.
 *
 *   This setting was `"./"`, justified by a mount prefix that does not exist.
 *   A relative base breaks **every route deeper than `/`**: the browser
 *   resolves `./assets/index-*.js` against the current path, so `/runs/<id>`
 *   asks for `/runs/assets/index-*.js`, the SPA catch-all answers with HTML,
 *   and the page renders blank. It never reproduced under `npm run dev`
 *   because Vite serves assets from the root in dev — which is exactly how a
 *   comment gets trusted beyond its reach for four tasks.
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
  base: "/",
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
