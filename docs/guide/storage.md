---
description: 'caelum local storage and retention: what is kept at full resolution, thumbnails, overlays, and how old files are rotated out.'
---

# Local storage and retention

Local disk is a rotating cache. The remote archive (see [Upload](/guide/upload))
is the permanent copy. Everything on this page follows from that.

## On-disk layout

All managed files live under `CAELUM_DATA_DIR` in a single date-based
convention shared by the storage writer, the retention sweeper and the
uploader:

```
<data_dir>/<kind>/<YYYY>/<MM>/<DD>/<YYYYMMDD-HHMMSS>[...].<ext>
```

A populated data directory looks like this:

```
data/
  raw/
    2026/09/19/
      20260919-210431.dng
      20260919-210431.json
      20260919-210501.dng
      20260919-210501.json
  thumbnails/
    2026/09/19/
      20260919-210431.webp
      20260919-210431.json
      20260919-210501.webp
      20260919-210501.json
      index.json
  overlays/
    2026/09/19/
      20260919-210431.png
      20260919-210501.png
  derivatives/
    2026/09/19/
      20260919-235959_keogram_keogram.png
      20260919-210433_meteor_detection_meteor_crop.jpg
  darks/
    dark_1000000us_4.0g_4056x3040.npy
  overlay_assets/
    logo.png
  manifest.json
```

Both the nested `YYYY/MM/DD` directories and the `YYYYMMDD-HHMMSS` filename
carry the same timestamp, deliberately redundantly — the nesting makes a
`thumbnails/2026/09/` listing a plain "browse by month" without opening
anything, and the full timestamp in the name means any single file, on its
own, is enough to know exactly when it was captured. Every date and time
here is **UTC**, always, taken from the frame's `captured_at` — the local
site time only ever shows up already converted, in the [web UI](/guide/web-ui),
with the zone made explicit. The four managed subdirectories — `raw`, `thumbnails`, `overlays`, `derivatives` — are
the ones retention sweeps and the uploader publishes. `darks` is a hand-curated calibration library and
is never touched, and neither is `overlay_assets` — the images an admin
uploads for `custom_image` overlay elements in the [overlay editor](/guide/plugins),
which are config, not capture output. Neither is uploaded: an asset only
ever reaches the remote archive as pixels of a rendered overlay.

## Overlays

The overlay of every frame — the overlay editor's template (by default the
capture time, exposure and gain, the camera name, the AstroMeters logo, the
capture software and the camera model), and whatever other plugins
contribute (meteor boxes, the telescope marker) — is rendered **once, on the
camera**, after all plugins have finished with the frame
(`derivatives/overlay_render.py`). The viewers never draw overlay elements
themselves; they show that image, so the live view, the local history and
the remote archive look exactly the same.

`storage_policy.overlay_mode` decides what happens to it:

| Mode | Stored thumbnail | Overlay |
|---|---|---|
| `file` (default) | clean | transparent PNG with the same stem in `overlays/`, stacked over the thumbnail by the viewers (which can also hide it) |
| `burn` | overlay drawn into the WebP | no separate file |
| `off` | clean | none |

The live view always gets the rendered layer (`/api/frame/overlay.png`)
unless the mode is `off`. Overlay text sizes are given in pixels of a
1024 px wide image and scale with the actual size. Changing the mode only
affects frames captured from then on.

Derivative filenames carry more than a timestamp, because several workers may
emit on the same second:

```
<YYYYMMDD-HHMMSS>_<worker_id>_<kind>.<ext>
```

The extension is `png` for anything whose kind starts with `keogram`, and `jpg`
otherwise. Retention reconstructs a file's capture time straight from its own
name — splitting the stem on the first `_` and parsing what's left as
`YYYYMMDD-HHMMSS` — which is why the timestamp must come first and needs no
help from the parent directory.

## Metadata sidecars

Every stored image gets a JSON sidecar with the same stem and a `.json`
extension — `210431.dng` and `210431.json`, `210431.webp` and `210431.json`. It
is the frame's `FrameMetadata` serialised with `indent=2`: capture time,
exposure, gain, the full sky state, the focus score and the overlay elements.
The same document is written next to the raw file and next to the
thumbnail; the thumbnail's copy is rewritten once the overlay is rendered,
with every plugin's elements and `overlay` saying where the rendered image
is (`"file"` or `"burned"`).

That redundancy is on purpose: a raw DNG pulled off the archive months later
carries its own provenance next to it.

The raw DNG file additionally carries the key values inside itself — standard
EXIF tags (`ExposureTime`, `DateTimeOriginal` in UTC, `Make`/`Model`) and an XMP
packet in the `caelum:` namespace with the sky period, Sun and Moon position,
moon illumination, site location, exposure and gains and the exposure loop's
brightness measurement — so a DNG separated from its sidecar still says when
and how it was taken. The pixels are the sensor's untouched Bayer data,
losslessly compressed unless `dng_compress` is off. Several raw frames of one
capture set go into one multi-frame DNG, see
[Capture sets in DNG](/dng-capture-sets).

Older captures may still be `.fits` raws and `.jpg` thumbnails; caelum reads
both next to the new formats.

## When raw files are written

Every captured frame produces a thumbnail plus a sidecar. Raw DNG files are
conditional.

`StoragePolicy.decide()` sets `save_raw` to true when the frame's sky period is
listed in `storage_policy.raw_periods`, which defaults to:

```json
{
  "storage_policy": {
    "raw_periods": ["astronomical_twilight", "night"],
    "thumbnail_max_dim": 1024,
    "thumbnail_downscale": "peak",
    "thumbnail_prefilter_sigma": 0.8,
    "thumbnail_chroma_blur": 0.0,
    "thumbnail_gamma": 1.0,
    "webp_quality": 90,
    "night_capture_interval_s": 30.0,
    "day_capture_interval_s": 60.0,
    "realtime_stream_fps": 2.0
  }
}
```

So out of the box, daylight and the two brighter twilights produce thumbnails
only, and astronomical twilight and night produce a full DNG file as well. The
same flag also selects the capture cadence — `night_capture_interval_s` when
raw is being saved, `day_capture_interval_s` otherwise.

Thumbnails are encoded in memory at `thumbnail_max_dim` on the longest side
(1024 px by default) at `webp_quality`. No temporary files are involved at any
point in the pipeline.

Five settings decide how well faint stars survive that step:

| Setting | Default | Effect |
|---|---|---|
| `thumbnail_downscale` | `peak` | `area` averages each block of source pixels, so a 1–2 px star loses most of its brightness in a 4× reduction. `peak` also pulls each block half-way towards its brightest pixel (hue is kept). Affects the stored thumbnail and the live stream. |
| `thumbnail_prefilter_sigma` | `0.8` | Gaussian blur (sigma in source pixels, 0–4, 0 = off) of the full-size frame before the reduction. Single noisy pixels stop counting as peaks while a star's 2 px profile survives; on a night frame it roughly halves the noise and nearly halves the WebP. Affects the stored thumbnail and the live stream. |
| `thumbnail_chroma_blur` | `0.0` | Gaussian blur (sigma in thumbnail pixels, 0–8, 0 = off) of the colour channels only; removes coloured speckle without softening stars. Stored WebP only. |
| `thumbnail_gamma` | `1.0` | Tone curve `out = in ** (1 / gamma)` on the stored WebP only. Above 1 lifts the shadows; 1 is off. |
| `webp_quality` | `90` | Lossy WebP quality, 1–100. At 1024 px a night frame is roughly 100 kB at 80, 150 kB at 85 and 240 kB at 90. |

The actual writing happens in `StorageWriter`, which subscribes to
`frame_captured` and immediately submits to a two-thread pool — the capture
thread never blocks on disk. A write failure is logged with a traceback and
dropped; it never propagates back into the capture loop.

::: tip Sizing the disk
A 4056×3040 RGB frame is roughly 35 MB uncompressed. At the default 30 s night
cadence that is about 4 GB per hour of raw data. Either keep
`retention.max_age_days` short, keep the uplink fast, or narrow `raw_periods`
to `["night"]`.
:::

## The retention sweeper

`RetentionSweeper` is a daemon thread that runs a sweep, waits
`retention.sweep_interval_s`, and repeats. It re-reads the config at the top of
every iteration, so changes apply without a restart.

```json
{
  "retention": {
    "max_age_days": 2,
    "min_free_space_mb": 1024,
    "sweep_interval_s": 3600.0
  }
}
```

Each sweep:

1. **Collect candidates.** Walk `raw/`, `thumbnails/` and `derivatives/`
   recursively. Skip `.json` files — sidecars are never candidates in their own
   right, they are deleted alongside their image. Skip anything whose capture
   time cannot be reconstructed from its path. Record time, path and size.
2. **Apply the upload filter.** See below.
3. **Sort oldest first.**
4. **Delete by age.** Anything older than `now - max_age_days` is deleted,
   along with its sidecar.
5. **Delete by space pressure.** While free space on the data directory's
   filesystem is below `min_free_space_mb`, pop the oldest remaining candidate
   and delete it. Free space is re-checked after each deletion, so the sweep
   stops as soon as it has made enough room. If the uploaded candidates run out
   first, the oldest not-yet-uploaded files follow (see below).

The sweep logs a summary when it deletes anything:

```
Retention sweep deleted 412 file(s), freed 1834.6 MB
```

## Files not yet uploaded are exempt

This is the rule that makes the "local disk is a cache" claim true rather than
aspirational.

When `upload.enabled` is true, the candidate list is filtered down to files
older than the uploader's confirmed-upload watermark:

```python
if upload_cfg.enabled:
    candidates = [c for c in candidates if uploaded_before is not None and c[0] < uploaded_before]
```

`uploaded_before` is the timestamp of the last *successful full reconciliation
pass* — not the last incremental push, which only ever proves that today's
directories are covered. Until a reconciliation has completed successfully at
least once since startup, `uploaded_before` is `None` and the filter removes
**every** candidate: nothing is deleted at all.

That exemption applies to the age limit only. The free-space floor wins over
it: if deleting every uploaded file still leaves less than
`min_free_space_mb` free — upload lagging far behind, or a remote that is
unreachable or refuses writes — the sweep goes on to delete the oldest
not-yet-uploaded files until the floor is met, and logs

```
Free space below 4096 MB with upload not caught up: deleted 38 file(s) that were never confirmed uploaded
```

Losing the oldest frames that never reached the archive is a loss you can
live with; a full root filesystem that stops capture, logging and SSH on a
remote camera is not.

::: warning
Running with `upload.enabled: true` against a remote that is permanently
unreachable means nothing gets archived, and the camera keeps only as much
history as fits above the free-space floor. Check the log for repeated
`rsync failed` warnings and for the warning above.
:::
