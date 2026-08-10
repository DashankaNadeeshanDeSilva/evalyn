import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import type { MetaResponse } from "./api/types";

/**
 * SPA entry point.
 *
 * Task 8 replaces `<Boot/>` with the real `<App/>` (shell, router, TanStack
 * Query). Until then this renders enough to prove the seam end to end: the
 * bundle builds, mounts, and reads `/api/meta` from either the mock worker or a
 * real `evalyn ui`.
 *
 * MSW is started **before** the first render and **only** in dev, when
 * `VITE_MSW=1`. Starting it after render would let the first fetch escape the
 * worker; shipping it at all would put a development mock inside a released
 * wheel (`vite.config.ts` drops `public/` from the build for the same reason).
 */
async function enableMocking(): Promise<void> {
  if (!import.meta.env.DEV || import.meta.env["VITE_MSW"] !== "1") return;
  const { worker } = await import("./mocks/browser");
  await worker.start({ onUnhandledRequest: "bypass" });
}

/**
 * Data lives in state, not in a `getElementById` after `render()`.
 *
 * React 18's `createRoot().render()` is concurrent and returns before the DOM
 * exists, so the imperative version raced the mount and silently rendered
 * nothing. Later tasks fetch through TanStack Query; the rule is the same.
 */
function Boot() {
  const [line, setLine] = useState("loading…");

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await fetch(new URL("/api/meta", window.location.origin));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const meta = (await res.json()) as MetaResponse;
        // `runs_dir` is a display-safe label with `$HOME` collapsed to `~`.
        // Display only — never join it onto anything, never send it back.
        if (live) setLine(`v${meta.version} · runs_dir ${meta.runs_dir}`);
      } catch (err) {
        if (live) setLine(`no API yet (${String(err)})`);
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  return (
    <main className="p-8 font-mono text-sm">
      <h1 className="text-lg font-semibold">Evalyn</h1>
      <p className="mt-2 text-neutral-600">
        Cockpit scaffold. The shell lands in Task 8.
      </p>
      <pre id="meta" className="mt-4 rounded bg-neutral-100 p-3">
        {line}
      </pre>
    </main>
  );
}

void enableMocking().then(() => {
  const root = document.getElementById("root");
  if (!root) throw new Error("#root missing from index.html");
  createRoot(root).render(
    <StrictMode>
      <Boot />
    </StrictMode>,
  );
});
