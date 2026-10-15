# caelum web frontends

The `web/` half of [caelum](../README.md) — a pnpm workspace next to the
Python backend in `../src/caelum`. Two apps share one component/client library:

- **`apps/local-web`** — full interactive control, talking to a live caelum
  backend on the same device (e.g. a Raspberry Pi) over its REST API and
  `/ws/stream` WebSocket. Built to `apps/local-web/dist`, which
  the backend serves at `/` in a source checkout; release wheels carry their
  own copy (`../scripts/build-release.sh`).
- **`apps/remote-web`** — read-only, multi-camera visualization. Talks only
  to static JSON/JPEG files (no backend at all) served from an Apache host
  that caelum's uploader rsyncs data to.
- **`packages/ui`** (`@caelum/ui`) — shared React components, most notably
  the image+overlay viewer used identically by both apps.
- **`apps/docs`** — the public documentation site (VitePress), deployed as
  static files alongside the gallery. The local UI deep-links into it, so
  its page paths are part of the contract (see below).
- **`packages/ui`** entries worth knowing: `AppShell` (the sidebar frame
  both apps use), `ThemeProvider`/`ThemeToggle` (light/dark, persisted in
  `localStorage`), and the token set in `src/theme.css`.
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
pnpm -r build   # typechecks both packages, builds every app to dist/
pnpm -r lint    # lints every package/app
```

Each app also has its own `dev` / `build` / `lint` / `preview` scripts,
runnable via `pnpm --filter <app> <script>`.

### Deployment paths

`local-web` is served by caelum itself from `apps/local-web/dist`, so it is
always at a document root and needs no path configuration.

The two static sites do:

- **`remote-web`** builds with a *relative* asset base and derives its data
  root from the directory its `index.html` was served from. One build
  therefore works at the document root or in any subdirectory, with no
  rebuild and no Apache configuration. (This is only safe because the app
  uses `HashRouter` — every route lives under the one `index.html`.)
- **`apps/docs`** is VitePress, which bakes an absolute base in at build
  time: pass `DOCS_BASE=/docs/` when it is not served from the root. It also
  emits real `.html` files (`cleanUrls: false`) so that extension-less URLs
  do not require `MultiViews` or a rewrite rule on the host.

`scripts/deploy-static.sh user@host:/var/www/allsky` builds both with the
right settings and rsyncs them into place, without touching the data tree
caelum's uploader syncs into the same directory.

## Layout

```
web/
  packages/
    ui/           @caelum/ui — shared React components
    api-client/   @caelum/api-client — typed clients + shared types
  apps/
    local-web/    live control UI, built to apps/local-web/dist
    remote-web/   read-only static-data viewer
    docs/         public documentation site (VitePress)
  scripts/
    deploy-static.sh   builds + rsyncs remote-web and docs to an Apache host
```

`packages/*` export TypeScript source directly (no separate bundling step)
— Vite compiles it as part of each app's own build, and `pnpm -r build`
typechecks each package standalone via `tsc --noEmit`.

## Backend contract

The exact REST/WS/static-file shapes this frontend is built against are
documented as TypeScript types in `packages/api-client/src/types.ts`, kept
in sync with `../src/caelum/api/schemas.py`,
`../src/caelum/config/schema.py` and
`../src/caelum/capture/metadata.py`.


## Documentation links from the UI

The local UI links into the documentation site at paths it expects to exist.
The base is per-deployment (`docs.base_url` in the backend config, and
`VITE_DOCS_URL` for remote-web), but these page paths are fixed:

| Link from | Target |
| --- | --- |
| Sidebar footer, both apps | `/` |
| Login page, "Forgot the password?" | `/guide/security.html` |
| Settings page, "What do these mean?" | `/guide/concepts.html` |

Renaming or moving those pages breaks the links silently — the docs build
cannot see them. Grep for `docs_url` and `docs.base_url` before doing so.
