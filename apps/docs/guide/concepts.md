# Concepts

Almost every decision caelum makes is keyed off one small object: the sky
state. Understanding it explains the rest of the system.

## Sky state

`SkyStateCalculator` is constructed once from `location.lat`, `location.lon`
and `location.elevation_m`, and computes a `SkyState` on demand. The capture
worker recomputes it at most every 30 seconds — the sky does not move fast
enough to justify more, and the computation is not free on a Pi.

A `SkyState` carries:

| Field | Meaning |
| --- | --- |
| `timestamp` | When this state was computed (UTC). |
| `sun_altitude_deg` | Sun altitude above the horizon, degrees. |
| `sun_azimuth_deg` | Sun azimuth, degrees. |
| `moon_altitude_deg` | Moon altitude, degrees. |
| `moon_azimuth_deg` | Moon azimuth, degrees. |
| `moon_illumination` | Illuminated fraction, 0.0 at new moon to 1.0 at full. |
| `period` | One of the five sky periods below. |

Positions come from astropy's `get_body`, transformed into the observer's
`AltAz` frame. The builtin analytic solar-system ephemeris is used and
`iers.conf.auto_download` is set to `False`, so this needs no external file and
no network access, ever — nothing to pre-seed on a field-deployed Pi, nothing
that can go stale or fail to download. Accuracy was cross-checked against
skyfield's JPL DE421 ephemeris during development: sun and moon altitudes
agreed to within about 0.05°, which is far inside what altitude-based twilight
classification needs.

Moon illumination is derived from the sun–moon elongation as seen from the
observer, `k = (1 - cos(elongation)) / 2`. This is the standard low-error
approximation; it ignores the small Earth–Moon versus Sun–Moon distance
correction.

::: tip
`astral` was evaluated and rejected: it exposes moon phase but not moon
altitude and azimuth, which the overlay and the observer both want.
:::

## The five sky periods

Classification is purely a function of sun altitude, using the standard
NOAA/USNO thresholds:

| Period | Sun altitude |
| --- | --- |
| `day` | above −0.8333° |
| `civil_twilight` | −0.8333° down to −6° |
| `nautical_twilight` | −6° down to −12° |
| `astronomical_twilight` | −12° down to −18° |
| `night` | below −18° |

The −0.8333° figure is not arbitrary: it accounts for the apparent radius of
the solar disk plus atmospheric refraction, so `day` ends at visible sunset
rather than at geometric sunset. Each boundary is a strict "greater than" test
on the upper bound, so a sun altitude of exactly −6.0° classifies as
`nautical_twilight`.

These five strings are the `SkyPeriod` literal type used throughout the config
schema, so they are also the exact keys you will type into
`exposure_policy.presets` and the exact values you will list in
`storage_policy.raw_periods`.

## Period drives exposure

`exposure_policy.presets` is a map from period to an `ExposurePreset`: an
exposure range in microseconds, a gain range, a target mean ADU and a
saturation threshold. The controller looks up the preset for the current period
and drives the camera inside that envelope. Widening night exposure, or
refusing to let gain rise above 4× during civil twilight, is a matter of
editing one preset. The full defaults and the control algorithm are in
[Exposure control](/guide/exposure).

## Period drives storage

`StoragePolicy.decide()` reads the same `sky_state.period` and returns two
things:

```python
StorageDecision(save_raw=..., capture_interval_s=...)
```

- `save_raw` is true when the current period appears in
  `storage_policy.raw_periods`, which defaults to
  `("astronomical_twilight", "night")`.
- `capture_interval_s` is `storage_policy.night_capture_interval_s`
  (default 30 s) when `save_raw` is true, and
  `storage_policy.day_capture_interval_s` (default 60 s) otherwise.

Note the exact coupling: the "night" interval is selected by the raw-save
decision, not by the period being literally `night`. Add `civil_twilight` to
`raw_periods` and civil twilight also switches to the faster cadence. That is
intentional — the two settings describe one regime, "we are taking this
seriously now", and keeping them on one switch means they cannot drift apart.

Because both the exposure controller and the storage policy read the same
`SkyState` object produced in the same capture cycle, there is no window in
which one believes it is night and the other does not.

The capture interval can be shortened, never lengthened, by stream mode: when
the local UI requests live viewing (`POST /api/camera/mode`), the worker takes
`min(capture_interval_s, 1 / storage_policy.realtime_stream_fps)`, with
`realtime_stream_fps` defaulting to 2.

## Frame metadata

Every frame carries a `FrameMetadata` document. The same JSON shape is pushed
live over the WebSocket, written as a `<HHMMSS>.json` sidecar next to every
stored image, and mirrored to the remote server by the uploader — so the
overlay renderer in `@caelum/ui` draws from an identical structure regardless
of where it came from.

```json
{
  "captured_at": "2026-09-19T21:04:31.482913+00:00",
  "exposure_us": 4000000,
  "analogue_gain": 2.5,
  "sky_state": {
    "sun_altitude_deg": -21.4,
    "sun_azimuth_deg": 332.1,
    "moon_altitude_deg": 14.8,
    "moon_azimuth_deg": 191.7,
    "moon_illumination": 0.62,
    "period": "night"
  },
  "focus_score": 118.3,
  "overlay_elements": []
}
```

`focus_score` is the variance of the Laplacian of a downscaled grayscale copy
of the frame — a standard cheap sharpness proxy. High variance means crisp
edges (stars in focus); low variance means a blurred, fogged or overcast frame.
It is a useful trend to watch, not a calibrated measurement.

## Overlay elements

`overlay_elements` is a list of `OverlayElement`, each with a `type`, a
`source` and an open `payload` dict:

```json
{
  "type": "detection_box",
  "source": "meteor_detection",
  "payload": { "x": 0.41, "y": 0.22, "w": 0.09, "h": 0.03, "label": "possible meteor" }
}
```

`type` is deliberately *not* an enum, so a plugin can introduce its own kind
without a schema change on the backend. `source` is `"system"` for the
built-ins, or the plugin id for anything a plugin contributed.

Three system elements are attached to every frame in the capture thread:

- `timestamp` — payload `{ "text": <ISO 8601 capture time> }`
- `exposure_readout` — payload `{ "exposure_us": …, "analogue_gain": … }`
- `sky_state_badge` — payload `{ "period": …, "sun_altitude_deg": …, "moon_illumination": … }`,
  rounded for display

Derivative workers and plugins append further elements asynchronously through
`FrameStore.update_metadata()`, which attaches them to whichever frame is
currently latest and re-broadcasts it to WebSocket subscribers. There is no
per-frame identifier to address a specific past frame with, so this assumes
derivative processing completes well within one capture interval. In practice
that holds comfortably — a frame difference takes milliseconds, capture
intervals are tens of seconds — but it is an assumption, not a guarantee.
