---
sidebar: false
description: 'Caelum Viewer: a static web app for browsing allsky camera data — timeline by sky period, time-lapse playback, frame metadata, charts, filters and RAW download.'
---

# Web viewer

**Caelum Viewer** is a web app for browsing what caelum cameras have captured:
pick a camera and a day, scrub through the night on a timeline, play it as a
time-lapse, inspect any frame's metadata and download its RAW file. It has no
backend of its own — it runs as static files and reads the data straight from
where the cameras put it.

::: tip Open it
**[viewer.caelum.astrometers.eu](https://viewer.caelum.astrometers.eu/)** —
source code: [roman-dvorak/caelum-viewer](https://github.com/roman-dvorak/caelum-viewer)
:::

![Caelum Viewer showing a night frame, the day's timeline and the frame's metadata](/images/screenshots/caelum-viewer.webp)

## What it does

- **Camera, day and time** — chosen from a camera catalogue; the whole view
  state is in the URL, so any frame can be bookmarked or shared.
- **Timeline** — 24 hours UTC, coloured by sky period (day, civil, nautical
  and astronomical twilight, night). Click or drag to move through the day.
- **Frame detail** — zoom (wheel, `+`/`−`), pan by dragging, fullscreen, and
  the overlay with time, exposure, gain, sky period, sun and moon on or off.
- **Metadata** — the frame's full metadata as a table: exposure and gain, sun
  and moon position, moon illumination, focus score and the exposure-control
  values behind the frame.
- **Downloads** — the original RAW (DNG), the preview and the JSON metadata.
  RAW files are only ever fetched when you ask for one.
- **Time-lapse** — playback at 2–30 frames per second, preloading ahead.
- **Live** — reloads every 30 s and shows the newest frame.
- **Charts** — any numeric metadata over the day, with a cursor synchronised
  to the frame shown; click a chart to jump to that frame.
- **Filters** — by sky period, by value ranges of any metadata field and by
  whether a RAW exists. They apply to playback, the gallery and the charts.
- **Gallery** — the day's WebP thumbnails.

Keyboard: `←`/`→` (with Shift, by 10), `Home`/`End`, `Space` plays,
`F` fullscreen, `+`/`−`/`0` zoom, `L` live, `O` overlay.

## Where it reads data from

The viewer works with anything that can list a directory and serve files, and
it expects caelum's on-disk layout (`thumbnails/YYYY/MM/DD/…webp` + `.json`,
`raw/YYYY/MM/DD/…dng`):

| Source | `type=` | Notes |
|---|---|---|
| S3 bucket | `s3` | publicly readable bucket; caelum's [S3 upload](/guide/upload) writes exactly this |
| Web server directory listing | `http-index` | nginx (`autoindex_format json`), Caddy, or Apache's HTML listing |
| Archive without listings | `caelum-manifest` | reads the `manifest.json` / `index.json` caelum's uploader writes; no RAW |
| A camera on your LAN | `caelum` | straight from the camera's API — see below |

A single source goes in the URL:

```
https://viewer.caelum.astrometers.eu/?type=s3&endpoint=https://s3.example.org&bucket=allsky&prefix=camera01/
https://viewer.caelum.astrometers.eu/?type=http-index&source=https://data.example.org/camera01/
```

Several cameras go in a catalogue — a JSON file listing each camera's `id`,
`name` and `source` (the `cameras.json` caelum's uploader writes is accepted
too):

```
https://viewer.caelum.astrometers.eu/?catalog=https://example.org/cameras.json
```

Further parameters: `camera=`, `date=YYYY-MM-DD`, `time=HH:MM[:SS]` (UTC),
`live=1`. The full reference, including custom file layouts, is in the
viewer's [README](https://github.com/roman-dvorak/caelum-viewer#readme).

::: warning CORS and public data
The data is on a different domain than the viewer, so the server has to send
CORS headers allowing the viewer's origin, and the data has to be publicly
readable — no keys ever go into the URL or the catalogue. Examples for S3,
nginx and Apache are in the README.
:::

### Straight from a camera

`?type=caelum&source=192.168.1.50` reads frames from a camera's own API on your
LAN, with no archive at all. The camera has to allow the viewer's origin
(`CAELUM_CORS_ORIGINS` in its environment) and have
`auth.preview_access: "public"`, because a page from another domain never gets
the camera's login cookie. Chrome and Edge allow an https page to reach a LAN
address after a one-time prompt; Firefox and Safari block it as mixed content.

## Publishing a camera

Turn on the camera's [upload](/guide/upload) to an S3 bucket or a web server
the viewer can read, then point the viewer at it. Want your camera on
viewer.caelum.astrometers.eu? Contact AstroMeters at
[info@astrometers.eu](mailto:info@astrometers.eu).

::: warning Location is public
Each camera's `location` ends up in its public metadata. If the site is
somebody's garden, set `location` to a rounded coordinate — the sky-state
calculation does not need metre precision.
:::

## The bundled gallery: `remote-web`

caelum itself also ships a much simpler read-only gallery, `web/apps/remote-web`:
a camera list, observation dates, the day's keogram and thumbnails. It needs no
CORS and no directory listings — it is dropped into the same directory the
uploader rsyncs to and reads the uploader's `cameras.json` and manifests.

```bash
cd web
pnpm --filter remote-web build
rsync -az apps/remote-web/dist/ archive.example.org:/var/www/allsky-data/
```

No `--delete`: the cameras' data lives in the same tree. The Apache vhost and
the upload user are in [Deployment](/guide/deployment#the-archive-and-remote-viewer).
