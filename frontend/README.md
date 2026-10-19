# VocalMind Frontend

React 18 + Vite 6 SPA (Tailwind v4, MUI 7, Radix/shadcn wrappers, react-router 7) for managers and agents. Code layout and routes: [docs/frontend/FRONTEND_ARCHITECTURE.md](../docs/frontend/FRONTEND_ARCHITECTURE.md).

## Package manager

Use **pnpm 10** (CI pins `version: 10` in `.github/workflows/frontend.yml`). Do not use npm or yarn; they bypass `pnpm-lock.yaml`.

## Commands (run in `frontend/`)

| Command | Purpose |
|---|---|
| `pnpm install` | Install dependencies (`make fe-install`) |
| `pnpm run dev` | Dev server on :3000 (`make fe-dev`) |
| `pnpm run build` | `tsc -b && vite build` (`make fe-build`) |
| `pnpm run preview` | Serve the build on :3000 |
| `pnpm run lint` | `tsc --noEmit` (`make fe-lint`) |
| `pnpm run test` | Vitest unit tests, `src/tests/` (13 files) |
| `pnpm run test:coverage` | Vitest with coverage (`make fe-test-cov` from repo root) |
| `pnpm run cy:run` / `cy:open` | Cypress, `cypress/e2e/` (14 specs); needs `preview` running on :3000 |

From the repo root:

- `make fe-test` builds, starts `preview`, and runs Cypress. E2E always runs against a build, never the dev server.
- `make fe-e2e-cov` builds with `CYPRESS_COVERAGE=true` (istanbul), runs Cypress against `preview` on :3005, and writes `frontend/coverage/index.html`.

Cypress stubs every API call with `cy.intercept` (`cypress/support/e2eApiFixtures.ts`, data in `src/app/data/e2eFixtureSamples.ts`), so no backend is needed.

## Environment variables

| Variable | Effect |
|---|---|
| `VITE_API_URL` | Unset: calls `http://localhost:8000/api/v1`. Empty string: same-origin `/api/v1` through the Vite proxy (compose default; works through ngrok on :3000). |
| `VITE_DEV_PROXY_TARGET` | Vite proxy target for `/api` (default `http://backend:8000`). |
| `VITE_USE_OFFLINE_DEMO` | `true` serves bundled demo data instead of the API (see the architecture doc). Ignored under Cypress. |
| `VITE_USE_OFFLINE_AUTH` | `true` enables hardcoded demo logins in `loginWithEmail` (`src/app/services/api.ts`). Ignored under Cypress. |

## Build notes

- `vite.config.ts` splits vendor chunks with `manualChunks` (mui, recharts, lucide, radix, other). Keep new heavy dependencies in a named chunk.
- `vercel.json` rewrites all paths to `index.html` for SPA routing.
