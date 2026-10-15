# caelum

**Headless allsky / astro camera engine for Raspberry Pi and Linux.**

caelum owns the camera, knows where the Sun and Moon are, drives exposure and
gain through day, twilight and night, processes every frame in RAM and writes
or uploads only what is worth keeping. It runs unattended as a systemd
service and is controlled from a web UI.

- **Cameras** — Raspberry Pi HQ/Global/Module cameras via picamera2/libcamera,
  any UVC/V4L2 webcam via OpenCV, and a mock backend for development.
  Switchable at runtime, without a restart.
- **Sky-aware auto-exposure** — closed-loop exposure/gain control with
  separate presets for day, civil/nautical/astronomical twilight and night;
  Sun/Moon positions from astropy's builtin ephemeris, fully offline.
- **RAM-first pipeline** — thumbnails, JSON metadata sidecars and raw FITS,
  dark-frame and lens/white-balance calibration, configurable overlays.
- **Plugins** — keograms, meteor detection, timelapses, telescope-position
  overlay; third-party plugins use the same interface.
- **Storage and archive** — rotating local cache with retention policy and an
  rsync uploader to a permanent remote archive, viewable as a static
  multi-camera gallery.
- **Web UI** — live view, recordings by night, file browser, settings, live
  logs, web terminal; accounts with admin/viewer roles.

The web frontends (local control UI, static remote gallery, documentation
site) live in a separate repository, `caelum-web`.

## Installation

Pick one:

| | For | How |
| --- | --- | --- |
| [A. System install](#a-system-install-raspberry-pi--debian) | a camera in the field — Raspberry Pi OS, Debian, Ubuntu | `scripts/install-system.sh` → systemd service |
| [B. Manual / pip](#b-manual-install) | other distros, custom layouts, containers | `pip install` + your own service |
| [C. Development](#c-development) | working on caelum itself | `uv sync` + mock camera |

Requirements: Linux, Python ≥ 3.11, Redis (optional but recommended — without
it caelum runs off the on-disk config only). On a Raspberry Pi, use
**Raspberry Pi OS Bookworm (64-bit)**; a Pi 4 or 5 is recommended.

### A. System install (Raspberry Pi / Debian)

```bash
sudo apt install -y git
sudo git clone https://github.com/roman-dvorak/caelum /opt/caelum
sudo /opt/caelum/scripts/install-system.sh --web-dist /path/to/local-web/dist
```

The script is idempotent and does everything a field install needs:

1. installs `redis-server`, `python3-venv`, `rsync` and — for the Pi camera —
   `python3-picamera2` from apt,
2. creates a `caelum` system user (in the `video` group),
3. builds a virtualenv in `/opt/caelum/.venv` and installs caelum into it,
4. creates `/etc/caelum` (config, accounts, `caelum.env`) and
   `/var/lib/caelum` (captured data),
5. seeds `config.json` with the right camera backend, copies in the web UI,
6. installs and starts `caelum.service`.

Options (`--help` for the full list):

| Option | Meaning |
| --- | --- |
| `--camera picamera2\|opencv\|mock` | camera backend for a *new* config; default `picamera2` on a Raspberry Pi, `mock` elsewhere |
| `--web-dist DIR` | a built `caelum-web/apps/local-web/dist` to serve at `/` |
| `--user NAME` | service account name (default `caelum`) |
| `--no-start` | install, but do not enable/start the service |

Then open `http://<camera-ip>:8000/`, log in as `admin` with the password from
`/etc/caelum/initial-admin-password.txt`, change it on the Accounts page,
delete the file, and set the camera's location in Settings (the shipped
default is Prague). See [Accounts and access control](#accounts-and-access-control).

```bash
sudo cat /etc/caelum/initial-admin-password.txt
journalctl -u caelum -f
```

**Web UI.** The control UI is a separate static build from `caelum-web`.
Without `--web-dist` caelum still runs, API-only. Build it on any machine with
Node ≥ 22 and pnpm (not on the Pi — there is no need) and copy it over:

```bash
cd caelum-web && pnpm install && pnpm --filter local-web build
rsync -a apps/local-web/dist/ pi@camera:/tmp/local-web-dist/
```

then pass `--web-dist /tmp/local-web-dist` to the installer (or re-run it
with that option later).

**Upgrade** — pull and re-run; config, accounts and data are kept,
`default.json` and the unit file are refreshed:

```bash
sudo git -C /opt/caelum pull
sudo /opt/caelum/scripts/install-system.sh
```

**Uninstall:**

```bash
sudo systemctl disable --now caelum
sudo rm /etc/systemd/system/caelum.service
sudo rm -rf /opt/caelum /etc/caelum   # code, config and accounts
sudo rm -rf /var/lib/caelum           # captured data — only if you mean it
sudo userdel caelum
```

#### Why the Pi install pins numpy

Raspberry Pi OS's camera stack (`python3-picamera2` + `python3-libcamera` from
apt) is compiled against the *system* Python (3.11 on Bookworm) and the
*system* numpy (1.24.x) — there is no PyPI wheel for `libcamera` itself, so
apt is the only way to get it. The installer therefore creates the venv with
`--system-site-packages` (so it sees apt's picamera2) and installs with
`scripts/constraints-rpi.txt`, which pins numpy 1.24.2, astropy 6.1.7 (the
newest line supporting numpy 1.x) and opencv < 4.12. A numpy 2.x in that venv
*imports* fine but crashes with `numpy.dtype size changed` the moment
picamera2 pulls in `simplejpeg`. The full test suite passes under exactly
these pins on Python 3.11.

### B. Manual install

caelum is a normal Python package with a `caelum` console script:

```bash
python3 -m venv .venv
.venv/bin/pip install git+https://github.com/roman-dvorak/caelum
```

(On a Raspberry Pi with the Pi camera, add `--system-site-packages` to the
venv and `-c scripts/constraints-rpi.txt` to pip — see above.)

It is configured by a handful of environment variables, all optional (see
`.env.example`; a `.env` in the working directory is read too):

| Variable | Default | |
| --- | --- | --- |
| `CAELUM_CONFIG_DIR` | `./config` | `config.json`, `auth.json`; put `config/default.json` from this repo here |
| `CAELUM_DATA_DIR` | `./data` | captured frames, derivatives |
| `CAELUM_WEB_DIR` | `../caelum-web/apps/local-web/dist` relative to a source checkout | built web UI, served at `/` |
| `CAELUM_HTTP_HOST` / `CAELUM_HTTP_PORT` | `0.0.0.0` / `8000` | |
| `CAELUM_REDIS_URL` | `redis://127.0.0.1:6379/0` | |
| `CAELUM_CAMERA_BACKEND` | unset | force a backend regardless of config (dev/CI) |
| `CAELUM_TERMINAL_SHELL` | `$SHELL`, else `/bin/bash` | shell for the web terminal |
| `CAELUM_LOG_LEVEL` | `INFO` | |

For a service, `systemd/caelum.service.template` is the unit the installer
renders — replace the `@...@` placeholders by hand.

### C. Development

```bash
uv sync --group dev
uv run pytest
./scripts/dev_run.sh        # seeds ./config + ./data, starts redis if needed, runs on the mock camera
```

No real camera is required — the mock backend (`CAELUM_CAMERA_BACKEND=mock`)
generates synthetic frames with simulated exposure/gain-dependent brightness.
With `caelum-web` checked out next to this repository and
`pnpm --filter local-web build` run there, the UI is served automatically;
for frontend work use its Vite dev server instead.

#### Testing with a real webcam

Set `camera.backend` to `"opencv"` (or `CAELUM_CAMERA_BACKEND=opencv` to
override for one run) to capture from any UVC/V4L2 webcam via OpenCV —
useful for exercising the real capture pipeline on a PC with no astro
hardware attached. `camera.sensor_id` doubles as the device selector: `"0"`
opens `/dev/video0`, or give an explicit path.

Manual exposure/gain support varies a lot across consumer webcam drivers —
treat this backend as a pipeline-testing tool, not a source of accurate
photometry. In particular, the default `exposure_policy.day` preset
(0.1–10ms) is tuned for a bright daytime sky and will read as a black frame
indoors; either widen that preset for a local test config, or use
`POST /api/camera/exposure-override` with something like
`{"exposure_us": 100000}` to see a normally-lit room.

## Configuration

Runtime config is a single JSON document (see `config/default.json` for the
shape), kept in sync between disk (`config/config.json`, the durable source of
truth) and Redis (fast runtime reads + pub/sub change notifications) — see
`src/caelum/config/manager.py`. Copy `.env.example` to `.env` to override
bootstrap paths/ports.

## Accounts and access control

The API and web UI are behind a login. On first start, if there is no account
database, caelum creates an `admin` account with a random password and writes
it to `<config_dir>/initial-admin-password.txt` (mode 0600) — log in with it,
change the password from the Accounts page, then delete the file.

Accounts live in `<config_dir>/auth.json`, deliberately **not** in
`config.json`: `GET /api/config` returns the whole config document and the
Settings page renders it as an editable JSON tree, so credentials there would
be visible to anyone who can open that page. Copying a config between cameras
therefore never carries credentials with it.

Two roles:

| Role | Can do |
| --- | --- |
| `admin` | everything — config, camera control, plugins, deletes, terminal |
| `viewer` | read-only preview: status, sky state, live stream, browsing stored output |

The `auth` config section holds policy only:

- `enabled` — set to `false` to disable authentication entirely and treat every
  caller as an admin. For a trusted LAN, or for recovering from a lockout.
- `preview_access` — `"public"` (no login for the preview at all), `"viewer"`
  (any account, the default) or `"admin"` (viewers cannot see it either).
  Control endpoints are admin-only regardless.
- `terminal_enabled` — see below.
- `session_ttl_hours`.

Changing a password invalidates that user's sessions everywhere except the tab
that made the change. Sessions are stateless signed tokens, so they survive a
restart and a Redis flush.

**Forgotten admin password**: stop caelum, delete the `admin` entry from
`auth.json` (or move the whole file aside), start it again — caelum recreates a
bootstrap admin and writes a fresh password file. Removing just the admin entry
keeps any viewer accounts intact.

### Web terminal

`/ws/terminal` is a real PTY: an interactive shell running as the user caelum
runs as, with that user's full privileges. It is admin-only, and it is the one
switch worth turning off on any host reachable from a network you do not
control:

```json
{ "auth": { "terminal_enabled": false } }
```

The shell is `$CAELUM_TERMINAL_SHELL`, else `$SHELL`, else `/bin/bash`, started
in the data directory.

Note also that the session cookie is not marked `secure`, because the common
deployment is plain HTTP on a LAN address where a secure-only cookie would
never be sent at all. Put caelum behind a TLS reverse proxy if the network is
not trusted.

## Browsing stored output

Two endpoints back the web UI's file and recording views, both with reads at
preview level and deletes admin-only:

- `/api/files` — the data directory as it sits on disk: listing, download,
  recursive delete, and per-category usage plus free space. Every path is
  resolved and confined to the data directory before use, symlinks included.
  `/api/files/preview` renders any image *including FITS* as a downscaled PNG
  with a percentile stretch, which is the only way to look at a raw frame in a
  browser.
- `/api/frames` — the same files seen as a time series instead of a tree. One
  capture is up to three files in three directories (thumbnail, `.json`
  sidecar, raw FITS); this collapses them into one row per capture, and
  supports deleting a whole date, a selection of captures, or just the raw
  frames of a night (which is where the gigabytes are).

## Switching cameras without a restart

`CaptureWorker` reopens the camera whenever `config.camera` changes, checked
between exposures (never mid-capture) so a switch is safe regardless of how
long an exposure was running. Change `camera.backend` / `camera.sensor_id`
through `PUT /api/config` (or the Settings page's camera picker, which also
lists detected `/dev/video*` devices) and the new device opens on the next
cycle — up to one capture interval later, not immediately.

`GET /api/camera/options` reports both `configured` (what the config says)
and `active` (what is actually open right now); `applied` is false in the gap
between the two, which is how the UI shows "pending" instead of claiming
success the moment the config write returns. If a bad device path is
configured, `active`/`applied` simply never catch up — the capture loop logs
the failure and keeps retrying rather than crashing.

The `CAELUM_CAMERA_BACKEND` env var still overrides `config.camera.backend`
unconditionally (dev/CI convenience, pins a machine to `mock` regardless of
what's configured) but no longer freezes the camera for the process
lifetime — the override is reapplied every time the config-driven camera is
rebuilt.

## Plugins

`keogram` and `meteor_detection` are ordinary plugins, loaded through
`PluginLoader` exactly like a third-party one would be — not special-cased.
`AppConfig.plugins["keogram"]` / `["meteor_detection"]` control them via the
usual `enabled` / `order` / `settings` fields (see `/api/plugins` and the
Plugins page), and each declares a `config_schema` validating its own
settings (column width and live-flush interval for the keogram; diff
threshold, downscale size, and streak-shape thresholds for the detector).

Changing a plugin's config takes effect on the next captured frame:
`ConfigManager.on_change` triggers a full reload or the whole worker set,
which is deliberate — a worker's accumulated state (a keogram buffer sized
by the old `strip_height`, a detector's previous frame at the old `max_dim`)
would not make sense under new settings, so it is rebuilt from scratch
rather than patched in place. The one visible cost: an in-progress keogram
restarts if its own settings change mid-night.

## Logs

The web UI's Logs page is a live tail of everything caelum has logged since
it started — `journalctl -u caelum -f`, reachable from a browser instead of
a shell. Backed by an in-memory ring buffer (`logging_conf.LogBuffer`,
default 2000 lines) attached to the root logger, so it needs nothing beyond
the process already running: no log file, no journald dependency. Restart
the process and the buffer restarts empty — it is not a substitute for
`journalctl`/a log file when you need history from before the last restart.

`GET /api/logs` returns the current buffer as JSON (admin-only, handy for a
quick `curl` check); `/ws/logs` streams the same backlog on connect and then
every new line live. Plain HTTP request lines (`GET /api/status 200`, …) are
deliberately excluded — uvicorn logs those through its own handler that
doesn't propagate to the root logger, and the frontend's own polling would
otherwise fill the buffer with noise within minutes. What you see is
`caelum.*` application logging: capture cycles, config/plugin changes,
terminal sessions, upload/retention activity.
