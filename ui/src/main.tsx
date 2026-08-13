import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./index.css";

/**
 * SPA entry point.
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

void enableMocking().then(() => {
  const root = document.getElementById("root");
  if (!root) throw new Error("#root missing from index.html");
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
