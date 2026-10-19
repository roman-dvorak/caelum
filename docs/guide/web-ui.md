---
description: 'The caelum web interface: dashboard, live stream, settings, plugins, recordings, files and terminal.'
---

# The web UI

caelum ships two frontends, built from one pnpm workspace and sharing one
component library and one typed API client.

- **`local-web`** — the interactive control UI. It talks to a live backend on
  the same device over the REST API and the `/ws/stream` WebSocket. FastAPI
  serves its built `dist/` directly at `/` if it is present, so a Raspberry Pi
  runs one service and no nginx.
- **`remote-web`** — a read-only, multi-camera viewer. It talks to nothing but
  static JSON and JPEG files on a web host. No backend, no API, no credentials.

Neither draws overlays itself: both stack the overlay image the camera
rendered (see [Overlays](/guide/storage#overlays)) over the frame, so the
live view and the remote archive show exactly the same thing.

::: tip
`local-web` uses a hash router (`/#/live`, `/#/settings`). That is not a
stylistic choice: the backend mounts the build as plain `StaticFiles` with no
SPA fallback rewrite, so client-side routes must not depend on the server
rewriting arbitrary paths to `index.html`.
:::

## Layout

A left sidebar carries navigation between the pages below, and a light/dark
theme toggle sits with it. The toggle is a UI preference stored in the browser;
it has nothing to do with the backend config.

## Dashboard

The landing page. It shows the live frame with its overlay, a sky-state badge,
and a grid of status tiles fed by `GET /api/status` and `GET /api/skystate`:

- camera backend class name and whether the capture thread is alive
- current exposure, formatted in µs, ms or s, and analogue gain
- whether stream mode is on and whether a manual exposure override is active
- time of the last capture
- focus score from the most recent frame's statistics

![Dashboard](/images/screenshots/dashboard.webp)

*Screenshots on this page use the `mock` backend's synthetic frames.*

If no frame has been captured yet the viewer shows "Waiting for first frame…"
rather than an error — on a night preset the first capture can legitimately
take a while.

## Live stream

The full-size live view. It subscribes to `/ws/stream`, which pushes two
messages per update: the frame's metadata as JSON first, then the JPEG
thumbnail as binary — metadata first so the client can size and prepare before
the image lands. On connect, the currently latest frame is sent immediately so
a fresh page is never blank.

Each frame arrives twice: once as soon as it is captured, and again a moment
later when every plugin has contributed its overlay elements and the overlay
has been rendered — `metadata.overlay` is then set and the view stacks
`/api/frame/overlay.png` over the image, meteor boxes included.

![Live stream](/images/screenshots/live.webp)

This is also where the two capture-cadence controls live:

- **Stream mode** (`POST /api/camera/mode`) speeds capture up for live viewing,
  taking `min(storage_policy_interval, 1 / realtime_stream_fps)`. It can only
  ever speed capture up relative to what the storage policy would otherwise
  pick, never slow it down.
- **Manual exposure override** (`POST /api/camera/exposure-override`) takes the
  closed loop out of circuit and applies fixed values until cleared. See
  [Exposure control](/guide/exposure).

Both are process state, not config — they do not survive a restart.

## Settings

The whole runtime `AppConfig` as an editable JSON tree, loaded from
`GET /api/config`. Changes save automatically: each edit issues a
`PUT /api/config`, and if the backend rejects it the tree reverts to its
previous value and the error is shown. Type selection is restricted, so you
cannot accidentally turn a number into a string.

![Settings](/images/screenshots/settings.webp)

Three sections are locked against editing:

| Section | Why |
| --- | --- |
| `config_version` | Server-managed. The config manager bumps it on every write and uses it to resolve disk-versus-Redis conflicts at startup. |
| `camera` | Only takes effect on the next process restart, since the backend instance is created once at startup. Editing it here would silently do nothing until then, which is more confusing than locking it. |
| `redis` | A connection setting, not a tunable parameter. |

Adding and deleting nodes is restricted to `storage_policy.raw_periods`, the
one list where adding or removing an entry is a meaningful edit. Everywhere
else the schema is fixed and `extra="forbid"` would reject an invented key
anyway.

To change the camera backend, edit `config.json` directly (or use
`CAELUM_CAMERA_BACKEND` for a one-off) and restart.

## Plugins

Lists every entry in the `plugins` config block, sorted by `order` ascending —
the same order `PluginLoader` and `DerivativePool` apply. Each row exposes the
plugin's `enabled` flag, its `order`, and its `settings` blob, written back via
`PUT /api/plugins/{id}`. See [Plugins](/guide/plugins) for what those fields
mean.

## Files

A browser over the data directory — `raw/`, `thumbnails/`, `derivatives/`,
`darks/` and whatever else lives under `CAELUM_DATA_DIR`. It is the page for
answering "did that FITS file actually get written", for pulling a single frame
off the camera, and for checking that the date directories look the way
[Storage](/guide/storage) says they should.

## Recordings

A frame manager rather than a file browser: it lists captured frames grouped by
date and can delete them. Use it to clear out a night of test captures, or to
drop a date you know is worthless before the retention sweeper gets to it.

::: warning
Deletions here are immediate and local. If the frames have already been
uploaded, the archive keeps its copy — the uploader never issues `--delete`. If
they have not been uploaded yet, deleting them here destroys the only copy.
:::

## Terminal

A real PTY shell in the browser, at `/terminal`. It is admin-only and it is a
genuine shell with the full privileges of the user caelum runs as.

Set `auth.terminal_enabled` to `false` to remove it. Please read
[Security](/guide/security) before leaving it enabled on anything reachable
from a network you do not control.

## The remote view-only site

`remote-web` is a separate build with a separate deployment. It reads
`cameras.json` at its configured base URL, then each camera's `manifest.json`,
then each date's `index.json`, and renders galleries from the thumbnails and
their metadata sidecars. `VITE_REMOTE_BASE_URL` defaults to `/` — same origin —
which is right for the normal deployment where the build is dropped at the
Apache document root next to the data tree the uploader rsyncs there.

It has no write path, no API client and no session. Everything it can show is
everything the archive already serves publicly. See
[Web viewer](/viewer) for what it shows and how cameras get
into it, and [Deployment](/guide/deployment) for putting it on a host.
