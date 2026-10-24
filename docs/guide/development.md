---
description: 'Running caelum from a source checkout: requirements, the mock camera, environment variables, building the web interface and running the tests.'
---

# Running from source

For development, or to try caelum on a laptop. The `mock` camera backend
produces synthetic frames, so the whole pipeline — exposure loop, storage,
plugins, API and web interface — runs with no camera attached. To install
caelum on a camera, use the [installer](/guide/installation) instead.

## Requirements

- **Python 3.11 or newer.** `pyproject.toml` declares
  `requires-python = ">=3.11"` (Raspberry Pi OS Bookworm's Python); older interpreters
  will not resolve.
- **[uv](https://docs.astral.sh/uv/)** for dependency management. The project
  ships a `uv.lock` and uses `uv_build` as its build backend.
- **Redis**, reachable over TCP. It is not strictly required — the process logs
  a warning and runs off the disk config alone if it cannot connect — but you
  want it for config change notifications and fast reads.
- **rsync**, if you intend to upload to a remote archive.
- **Node 22.13+ and pnpm**, only if you want to build the web UI.

Everything else is a Python dependency: FastAPI, uvicorn, pydantic, redis,
numpy, `opencv-python-headless`, astropy, python-dotenv. There is no ephemeris
file to download and no runtime network access needed for sky calculations —
astropy's bundled analytic ephemeris is used with IERS auto-download disabled.

## Install

```bash
git clone <your-remote>/caelum.git
cd caelum
uv sync                 # runtime deps only
uv sync --group dev     # add pytest, ruff, httpx
```

On a Raspberry Pi, add the `picamera2` extra to get the libcamera stack. It is
declared with an ARM marker (`aarch64` / `armv7l`), so it is simply skipped
on a development laptop:

```bash
uv sync --extra picamera2
```

Create the local directories and seed the config file from the shipped
defaults:

```bash
./scripts/install.sh
```

That creates `./data/raw`, `./data/thumbnails`, `./data/derivatives`,
`./data/pending-upload` and `./config`, and copies `config/default.json` to
`config/config.json` if the latter does not exist yet.

## Environment variables

These are bootstrap-only settings, read once from the environment (and from a
`.env` file, via python-dotenv) at process start. They are deliberately
separate from the runtime `AppConfig`: they are the handful of things the
process needs *before* it can open the config store, and they are not expected
to change without a restart. Copy `.env.example` to `.env` to set them.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CAELUM_CONFIG_DIR` | `./config` | Directory holding `config.json` (durable source of truth) and `default.json` (fallback if `config.json` is missing). Also where `auth.json` and the initial admin password file live. |
| `CAELUM_DATA_DIR` | `./data` | Root of the on-disk frame tree — `raw/`, `thumbnails/`, `derivatives/`, `darks/`. |
| `CAELUM_HTTP_HOST` | `0.0.0.0` | Bind address for the HTTP server. |
| `CAELUM_HTTP_PORT` | `8000` | Bind port. |
| `CAELUM_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis connection URL for the config store. |
| `CAELUM_CAMERA_BACKEND` | *(unset)* | Overrides `camera.backend` from the config for one run. Unset by default — see below. |
| `CAELUM_LOG_LEVEL` | `INFO` | Root log level; also passed to uvicorn, lowercased. |

Paths are expanded (`~`) and resolved to absolute paths at load.

::: tip
`CAELUM_CAMERA_BACKEND` is not an auto-detect. `config.json`'s `camera.backend`
is authoritative; this variable exists so a developer or CI run can force
`mock` or `opencv` without touching the config. On real hardware, leave it
unset and configure the backend properly.
:::

## First run

```bash
uv run caelum
```

The `caelum` console script is declared in `pyproject.toml` and points at
`caelum.main:run`. On startup you will see a line like:

```
caelum starting: camera=mock http=0.0.0.0:8000 local-web=not built
```

For local development there is a convenience runner that starts (or reuses) a
local Redis, runs `scripts/install.sh`, and forces the mock backend:

```bash
./scripts/dev_run.sh
```

## The initial admin password

On first start, if no user database exists, caelum creates an `admin` account
with a randomly generated password and writes it to:

```
<config_dir>/initial-admin-password.txt
```

Read it, log in, change the password, then delete the file.

```bash
cat ./config/initial-admin-password.txt
```

Accounts live in `<config_dir>/auth.json`, deliberately *not* in the main
config document — that keeps password hashes out of the config editor in the
web UI and out of anything that reads or exports `config.json`. See
[Security](/guide/security) for roles and the `auth` config section.

## Opening the web UI

Point a browser at `http://<host>:8000/`. If `apps/local-web/dist` has been
built, FastAPI mounts it at `/` as static files and you get the full UI. If it
has not, the API is still there — `GET /api/status`, `GET /api/skystate`,
`GET /api/config`, `GET /api/frame/latest.jpg`, and the `/ws/stream`
WebSocket — and the startup line says `local-web=not built`.

Useful first checks without a UI:

```bash
curl -s localhost:8000/api/status
curl -s localhost:8000/api/skystate
curl -s localhost:8000/api/frame/latest.jpg -o latest.jpg
```

## Building the frontend

The frontend lives in `web/` in the same repository; a source checkout serves
the built assets from `web/apps/local-web/dist`. (A release wheel carries its
own copy instead — see [Deployment](/guide/deployment).)

```bash
cd web
pnpm install
pnpm -r build          # typechecks packages, builds both apps to dist/
```

Restart caelum afterwards; the static mount is decided once at startup.

For frontend development you do not need to rebuild on every change — run the
Vite dev server instead, which proxies `/api` and `/ws` through to a running
backend:

```bash
pnpm --filter local-web dev
# against a Pi on the LAN:
CAELUM_BACKEND_URL=http://raspberrypi.local:8000 pnpm --filter local-web dev
```

## Tests

```bash
uv run pytest
```

The suite runs entirely against the mock backend and temporary directories —
no camera, no Redis, no network.
