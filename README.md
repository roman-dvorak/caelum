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

### Deploying to a real Raspberry Pi (picamera2)

Raspberry Pi OS's camera stack (`python3-picamera2` + `python3-libcamera` from
apt) is compiled against the *system* Python (3.11 on Bookworm) and the
*system* numpy (1.24.x) — there is no PyPI wheel for `libcamera` itself, so
this is the only way to get it. That drives the whole install recipe:

```bash
sudo apt install -y python3-picamera2 redis-server
python3.11 -m venv --system-site-packages .venv   # sees apt's picamera2/libcamera
.venv/bin/pip install -e . 'numpy==1.24.2' 'astropy==6.1.7'  # match the system ABI
```

`numpy>=2.1`/current `astropy` (this project's normal floors, fine on a dev
machine) will *import* but crash with a `numpy.dtype size changed` ABI error
the moment `picamera2` pulls in `simplejpeg` — numpy changed its C struct
layout in 2.0, and the apt-compiled extensions were built against 1.24's.
Pinning both to versions compatible with the system numpy (6.1.x is the
newest astropy still numpy-1.x-compatible) resolves it; `--no-deps` when
installing caelum itself avoids pip immediately undoing the pin by pulling
newer defaults back in.

`requires-python = ">=3.11"` in `pyproject.toml` reflects this too — 3.13
would be preferable in isolation, but Bookworm's picamera2 forces 3.11, and
that's this project's actual deployment target.

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

## Exposure control

The exposure loop runs on the capture thread, once per frame, entirely in EV
— config, diagnostics and the dashboard alike:

- exposure*gain: `log2(seconds) + log2(gain)` (+1 EV = twice the light);
- image brightness: `log2(median / 255)`, i.e. EV below full scale
  (0 EV = 255 ADU, −1 EV ≈ 128 ADU, −0.77 EV ≈ 150 ADU).

**Measurement** — the median of a circle centred on the frame,
`exposure_policy.brightness_roi_diameter_frac` (default 0.8) of the shorter
side across. The preset's `target_ev` is the setpoint on the same scale.

**Each frame says what it needed.** Every frame carries the exposure/gain it
was really taken with, so `required = applied + (target − brightness) /
response_gamma` (`response_gamma` ≈ how many EV the image moves per EV of
exposure, default 0.7). A saturated median corrects by at least
`saturated_step_ev` down.

**Regulator** — PI, velocity form: `P = kp·Δrequired` (reacts to the scene
changing), `I = ki·(required − last output)` (closes the remaining
distance), `kd` exists but is 0. Within `deadband_ev` nothing moves; pinned
at a preset limit with the error pushing further out, nothing integrates.

**Split** — applied to the current exposure/gain by direction: more light =
exposure up first, then gain; less light = gain down first, exposure only
once gain is at its minimum. Preset bounds are soft across sky-period
switches: a value outside the new preset's range only moves toward it, in
that order (so at dawn the night's long exposure stays until gain is down).

**Captures on demand** — the camera is stopped between captures; each one
starts it with that capture's exposure/gain, takes the first frame and stops
it (~0.2 s overhead). libcamera sets the start controls before the first
frame, so every frame has exactly the requested settings — a continuously
running camera applies changes only 6–7 frames later, i.e. minutes with long
frames.

**Timing** — captures sit on a wall-clock grid `capture_interval_s` apart
(e.g. every minute on the minute), with the *middle of the exposure* on the
slot: the start is brought forward by half the exposure plus the measured
start latency, and `captured_at` is the mid-exposure time. A capture that
can't make a slot (exposure longer than the interval) skips it; the grid
never moves.

Older config files (`target_mean_adu`, `deadband_pct`,
`saturation_threshold`, `max_step_*`) are converted on load.
`GET /api/status` → `exposure_diagnostics` shows the last cycle; every
frame's sidecar has it under `exposure_control`, and
`scripts/plot_exposure.py` charts it over a night.

## Capture pipeline and output

The capture thread only captures, measures brightness, sets the next
exposure and hands the frame off. Calibration, statistics, encoding and all
disk writes run in a separate **processing process** (fed through shared
memory, `/dev/shm/caelum-*`), in parallel with the next exposure; if it falls
behind, frames are dropped from processing rather than delaying capture.
`processing.mode: "inline"` runs it on the capture thread instead (debugging).
`GET /api/status` → `processing` has its counters.

Per capture:

- `thumbnails/YYYY/MM/DD/<YYYYMMDD-HHMMSS>.webp` + `.json` sidecar, always;
- `raw/YYYY/MM/DD/<YYYYMMDD-HHMMSS>.dng` + `.json` sidecar, during
  `storage_policy.raw_periods` — the sensor's real 12-bit Bayer data (not
  the ISP output), with exposure/ISO/time/camera tags and an XMP packet
  (`caelum:` namespace) carrying sky state, site location, gains and the
  exposure loop's measurement. Needs PiDNG (`python3-pidng`, seen through the
  venv's system site-packages).

### White balance on a RAW frame

The DNG's white balance is its `AsShotNeutral` tag — the camera-space RGB
of a neutral grey, `[1/red_gain, 1, 1/blue_gain]` — the form every raw
converter reads (the alternative, `AsShotWhiteXY`, is far less supported).
The camera's `ColourGains` never change the Bayer data, so white balance
on a DNG is metadata only, and editing it is non-destructive.

The White balance page's **RAW frame** mode loads the newest DNG
(`GET /api/raw/white-balance`, then `/pixels`: linear camera RGB, one pixel
per 2×2 CFA cell, downscaled) and renders it in the browser — gains, the
file's colour matrix, a display-only brightness, sRGB curve. From there:

- **Save to this DNG** (`PUT /api/raw/white-balance`) rewrites those 24
  bytes in place, atomically; nothing else in the file changes. The gains
  the frame was captured with stay in the XMP (`caelum:colour_gains`), so
  "as captured" can always be restored. rsync re-sends the file on the
  next upload pass.
- **Use as camera default** is the existing `POST /api/camera/white-balance`:
  manual gains, AWB off, applied to every frame from then on.

The live stream (`/api/frame/latest.jpg`, `/ws/stream`) stays JPEG. Older
captures in `.jpg`/`.fits` keep working everywhere alongside the new formats.

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
  browser; a DNG previews as its capture's stored thumbnail.
- `/api/frames` — the same files seen as a time series instead of a tree. One
  capture is up to three files in three directories (thumbnail, `.json`
  sidecar, raw DNG — or FITS for older captures); this collapses them into one row per capture, and
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
