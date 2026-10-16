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
      20260919-210431.fits
      20260919-210431.json
      20260919-210501.fits
      20260919-210501.json
  thumbnails/
    2026/09/19/
      20260919-210431.jpg
      20260919-210431.json
      20260919-210501.jpg
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
extension — `210431.fits` and `210431.json`, `210431.jpg` and `210431.json`. It
is the frame's `FrameMetadata` serialised with `indent=2`: capture time,
exposure, gain, the full sky state, the focus score and the overlay elements.
The same document is written next to the raw file and next to the
thumbnail; the thumbnail's copy is rewritten once the overlay is rendered,
with every plugin's elements and `overlay` saying where the rendered image
is (`"file"` or `"burned"`).

That redundancy is on purpose: a raw FITS pulled off the archive months later
carries its own provenance next to it.

The raw FITS file additionally carries the key values in its header, so
standard astronomy tools see them without reading the sidecar:

```ini
EXPOSURE = 4.0          / seconds
GAIN     = 2.5          / analogue gain
DATE-OBS = 2026-09-19T21:04:31.482913+00:00
SUNALT   = -21.4        / degrees
MOONALT  = 14.8         / degrees
MOONILLU = 0.62         / fraction 0-1
SKYPERD  = 'night'
```

The image data is stored in the FITS convention for a colour cube — axes
reordered to `(channels, height, width)`.

## When raw files are written

Every captured frame produces a thumbnail plus a sidecar. Raw FITS files are
conditional.

`StoragePolicy.decide()` sets `save_raw` to true when the frame's sky period is
listed in `storage_policy.raw_periods`, which defaults to:

```json
{
  "storage_policy": {
    "raw_periods": ["astronomical_twilight", "night"],
    "thumbnail_max_dim": 1024,
    "jpeg_quality": 85,
    "night_capture_interval_s": 30.0,
    "day_capture_interval_s": 60.0,
    "realtime_stream_fps": 2.0
  }
}
```

So out of the box, daylight and the two brighter twilights produce thumbnails
only, and astronomical twilight and night produce a full FITS file as well. The
same flag also selects the capture cadence — `night_capture_interval_s` when
raw is being saved, `day_capture_interval_s` otherwise.

Thumbnails are encoded in memory at `thumbnail_max_dim` on the longest side
(1024 px by default) at `jpeg_quality`. No temporary files are involved at any
point in the pipeline.

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
    "max_age_days": 14,
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
   stops as soon as it has made enough room.

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

The consequence is deliberate and worth stating plainly: a disk that is
genuinely full while upload is lagging far behind will not free space until
upload catches up. caelum will let the disk fill rather than delete the only
copy of a frame. If that is not the trade you want, set `upload.enabled` to
false — retention then runs on age and space alone, because the local copy is
by definition the only copy that will ever exist, and that is your own
configuration choice.

::: warning
Running with `upload.enabled: true` against a remote that is permanently
unreachable is the worst of both worlds — nothing gets archived and nothing
gets rotated. Check the log for repeated `rsync failed` warnings, and watch
whether `Running full upload reconciliation pass` is ever followed by a
successful sweep.
:::
