---
sidebar: false
description: 'The caelum web viewer: a static, read-only website showing every camera in an archive, with keograms and frame galleries.'
---

# Web viewer

The web viewer (`remote-web`) is the public face of a caelum camera network: a read-only
website that shows every camera publishing to one archive — the latest image
from each, and for every camera a browsable history of nights with keograms
and frame galleries.

::: tip Live
AstroMeters runs one at **[viewer.caelum.astrometers.eu](https://viewer.caelum.astrometers.eu/)**.
:::

![The web viewer's camera list](/images/screenshots/viewer-cameras.webp)

## What it shows

- **All cameras** — one card per camera with its name, latest thumbnail and
  when it last published. Each camera also gets its own entry in the sidebar,
  so comparing cameras is one click.
- **A camera** — its site coordinates, a strip of observation dates (newest
  selected by default), that night's keogram and a gallery of the day's
  thumbnails.
- **Overlays** — the overlay each camera rendered is stacked over its frames,
  exactly as in the camera's own web UI, and can be toggled off.

![A camera in the web viewer: dates, keogram and gallery](/images/screenshots/viewer-camera.webp)

*Screenshots show the `mock` backend's synthetic frames, captured in daylight — hence no keogram yet.*

## How it works

There is no server behind it. The viewer (`web/apps/remote-web`) is a static
single-page app that reads three kinds of JSON file and the images they point
to, all produced by the cameras' [uploader](/guide/upload):

| File | Written by | Contents |
|---|---|---|
| `cameras.json` | every camera, merged | the list of cameras, each with its latest thumbnail |
| `<slug>/manifest.json` | that camera | site, and the dates it has data for |
| `<slug>/<date>/index.json` | that camera | the frames of one observation day |

So the viewer can show nothing that is not already public in the archive, and
it holds no credentials. It has no write path at all. A camera appears in the
viewer as soon as its first upload lands — there is nothing to register.

## Publishing a camera

Point the camera's upload at the archive the viewer is served from and give it
a slug and a name:

```json
{
  "upload": {
    "enabled": true,
    "remote_host": "archive.example.org",
    "remote_user": "caelum",
    "remote_base_path": "/var/www/allsky-data",
    "camera_slug": "brno-north",
    "camera_name": "Brno North Allsky"
  }
}
```

`camera_slug` is the camera's directory in the archive and its address in the
viewer (`/#/camera/brno-north`); `camera_name` is the label people see. SSH
keys, transports and the full layout are in [Upload & archive](/guide/upload).

Want your camera on viewer.caelum.astrometers.eu? Contact AstroMeters at
[info@astrometers.eu](mailto:info@astrometers.eu).

::: warning Location is public
Each camera's `location` ends up in its public `manifest.json`. If the site is
somebody's garden, set `location` to a rounded coordinate — the sky-state
calculation does not need metre precision.
:::

## Running your own

The viewer is one build that works wherever its folder is dropped — at a
document root or in a subdirectory, with no rebuild and no web server
configuration, because it derives the data root from its own URL and keeps its
routes in the URL fragment.

```bash
cd web
pnpm --filter remote-web build
rsync -az apps/remote-web/dist/ archive.example.org:/var/www/allsky-data/
```

No `--delete`: the cameras' data lives in the same tree. The Apache vhost and
the upload user are in [Deployment](/guide/deployment#the-archive-and-remote-viewer).
