# caelum

Headless capture engine for (not only) allsky cameras. Owns the camera, computes
sky state (sun/moon altitude, twilight period), drives exposure/gain, processes
frames in RAM, and persists/uploads only what's decided to be kept.

See `../caelum-web` for the local and remote React frontends, and
`/home/roman/.claude/plans/pot-eboval-bych-zde-zalo-it-cuddly-squid.md` for the
full architecture writeup.

## Development

```bash
uv sync --group dev
uv run pytest
```

No real camera is required for development — the mock backend
(`CAELUM_CAMERA_BACKEND=mock`, the default outside a Raspberry Pi) generates
synthetic frames with simulated exposure/gain-dependent brightness.

```bash
uv run caelum
```

### Testing with a real webcam

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

### Local systemd service (optional)

There's no systemd unit active anywhere by default — local dev just runs
`scripts/dev_run.sh` / `uv run caelum` directly, and `systemd/caelum.service.template`
is a template for a real Raspberry Pi deployment (`WorkingDirectory`,
`.venv` path, and `caelum` user need adjusting for wherever it's installed).
To run it as a persistent local service instead (e.g. to leave a webcam
test running in the background), copy the template, fill in the paths, and
`systemctl --user enable --now` it — ask first if you'd like this set up,
since it changes what starts automatically on this machine.

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
