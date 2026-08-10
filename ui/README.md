# `ui/` — the Evalyn cockpit SPA

React + TypeScript + Vite + Tailwind. Built output is committed into
`src/evalyn/ui/static/` and shipped inside the Python wheel; `evalyn ui` serves
it from there. Everything in this directory is build *input* and never ships.

## Toolchain (pinned — later tasks inherit these)

| | version | why pinned |
| --- | --- | --- |
| Node | `22.18.0` (`.nvmrc`) | exact, matching the dev machine |
| Vite | `8.2.1` | with `@vitejs/plugin-react` `6.0.5` (peers `vite ^8`) |
| React | `18.3.1` | React 18 per the plan, not 19 |
| TypeScript | `5.9.3` | the long-stable line. TS 7 (the native compiler) is current, but a scaffold six tasks depend on is the wrong place to lead |
| Tailwind | `3.4.19` | **v3, not v4.** v4 is CSS-first and has no `tailwind.config.ts`; the plan specifies one |
| Vitest | `4.1.10` | + `jsdom` `29.1.1` — jsdom 30 requires Node ≥ 22.22, which the pinned Node is not |
| MSW | `2.15.0` | mock API for both the browser (dev) and Node (tests) |

Every dependency is pinned to an **exact** version, and `package-lock.json` is
committed. CI uses `npm ci`, never `npm install`.

## Commands

```sh
nvm use                 # or any Node 22.18.0
npm ci                  # never `npm install` in CI
npm run dev             # dev server on :5173, proxying /api to 127.0.0.1:8765
VITE_MSW=1 npm run dev  # ...or serve the whole API from MSW instead
npm run test -- --run   # Vitest
npm run typecheck       # tsc --noEmit
npm run build           # typecheck, then emit into ../src/evalyn/ui/static/
```

`npm run build` **is** the commit artifact step: source and bundle are committed
together, so a PR that changes a component and forgets to rebuild is visible.

## Layout

```
src/api/types.ts        hand-written mirror of src/evalyn/ui/models.py
src/api/provisional.ts  shapes models.py does not freeze yet (packs, launch)
src/mocks/handlers.ts   MSW handlers for every route in the contract
src/mocks/fixtures.ts   the four-run corpus, mirroring tests/fixtures/ui_runs/
src/test/setup.ts       jest-dom + one MSW server per Vitest run
```

## Things that will bite you

**`types.ts` is hand-written, not generated.** `src/api/__tests__/types.test.ts`
is the only thing holding it to `models.py`: it pastes every enum as a frozen
literal *and* parses `models.py` at test time, so a self-consistent TypeScript
edit still goes red. If it fails, read the Python change before touching the
literals.

**`VerdictTier` is a string on the wire** — `"1" | "2" | "3" | "abstained"`.
Never `tier === 1`. `abstained` is a member, so an integer form was never
expressible.

**`next_cursor` is opaque** — the composite `"<created_at>|<run_id>"`, not a
timestamp. Hand it back verbatim. Never build one; the server rejects the
bare-timestamp form because it drops or duplicates rows that share a second.

**Every response model is `extra="forbid"` server-side.** An unexpected key is a
server bug, not something to tolerate. Mirror exactly.

**Disable affordances off `capabilities`, never truthiness.** An empty
transcript list means "not captured", not "the conversation was empty", and a
`null` metric means "this run cannot tell you" — never `0`.

**`/api/meta`'s `runs_dir` and `packs` are display-safe labels** with `$HOME`
collapsed to `~`. Render them; never join them onto a path or send them back.

**A degraded row still renders.** It carries a real `run_id`, `created_at` and
`mode`, plus a `degraded_reason` that must reach the operator — a greyed row
with no explanation is the failure mode that field exists to prevent.

## Build settings you should not change casually

- `base: "./"` — the SPA is served from a mount that is not guaranteed to be the
  server root; absolute `/assets/...` would 404.
- `build.sourcemap: false` — the bundle is committed, and sourcemaps are the
  biggest source of cross-machine diff noise.
- `src/evalyn/ui/static/` is **deliberately not gitignored**: hatchling honours
  `.gitignore`, so a gitignored bundle would ship an empty wheel. `.gitattributes`
  marks it `-text -diff` so reviews stay readable.
- `publicDir` is off for `build`, keeping MSW's service worker out of the wheel.
  Regenerate it with `npm run msw:init` if it goes missing.
