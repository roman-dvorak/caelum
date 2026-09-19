# caelum-web

Frontend monorepo for [caelum](../caelum), a headless allsky/astro camera
capture backend. Two apps share one component/client library:

- **`apps/local-web`** — full interactive control, talking to a live caelum
  backend on the same device (e.g. a Raspberry Pi) over its REST API and
  `/ws/stream` WebSocket. Built to `apps/local-web/dist`, which
  `caelum/src/caelum/main.py` serves directly at `/` if present.
- **`apps/remote-web`** — read-only, multi-camera visualization. Talks only
  to static JSON/JPEG files (no backend at all) served from an Apache host
  that caelum's uploader rsyncs data to.
- **`packages/ui`** (`@caelum/ui`) — shared React components, most notably
  the image+overlay viewer used identically by both apps.
- **`packages/api-client`** (`@caelum/api-client`) — typed REST/WS client
  for local-web, a typed static-file client for remote-web, and the shared
  TypeScript types for the backend contract (`AppConfig`, `FrameMetadata`, …).

## Toolchain

pnpm workspaces, React 19, Vite, TypeScript, Tailwind CSS 4, ESLint flat
config — matching the conventions used in this org's other React project
(`stel_control/app`).

## Getting started

```sh
pnpm install

# local-web dev server, proxying /api and /ws to a caelum backend
# (defaults to http://localhost:8000 — override with CAELUM_BACKEND_URL)
pnpm --filter local-web dev

# remote-web dev server (talks to static files only — see
# apps/remote-web/.env.example for pointing it at a data tree)
pnpm --filter remote-web dev
```

## Building

```sh
pnpm -r build   # typechecks both packages, builds both apps to dist/
pnpm -r lint    # lints every package/app
```

Each app also has its own `dev` / `build` / `lint` / `preview` scripts,
runnable via `pnpm --filter local-web <script>` / `pnpm --filter remote-web <script>`.

## Layout

```
caelum-web/
  packages/
    ui/           @caelum/ui — shared React components
    api-client/   @caelum/api-client — typed clients + shared types
  apps/
    local-web/    live control UI, built to apps/local-web/dist
    remote-web/   read-only static-data viewer
```

`packages/*` export TypeScript source directly (no separate bundling step)
— Vite compiles it as part of each app's own build, and `pnpm -r build`
typechecks each package standalone via `tsc --noEmit`.

## Backend contract

The exact REST/WS/static-file shapes this frontend is built against are
documented as TypeScript types in `packages/api-client/src/types.ts`, kept
in sync with `caelum/src/caelum/api/schemas.py`,
`caelum/src/caelum/config/schema.py` and
`caelum/src/caelum/capture/metadata.py`.
