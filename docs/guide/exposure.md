# Exposure control

caelum drives exposure time and analogue gain itself, in a closed loop, once
per capture cycle. The algorithm is short enough to read in full — it lives in
`control/exposure.py` and is about forty lines — but every constant in it is
there for a reason.

## The camera's auto-exposure is always off

This is not a tuning choice, it is the premise. The picamera2 backend sets
`AeEnable: False` on every `set_controls()` call; the OpenCV backend puts the
V4L2 device into `V4L2_EXPOSURE_MANUAL` on open and warns loudly if the driver
refuses.

A sensor's built-in AE optimises for a pleasant-looking photograph of whatever
is in frame right now. An allsky camera wants the opposite: a known, stable,
reproducible exposure that is a function of where the sun is, not of how many
bright clouds happen to be in view. Leaving AE on would mean two controllers
fighting over the same knobs, with the app's measurements reflecting the
camera's corrections rather than the sky.

## One cycle, step by step

### 1. Look up the preset for the current period

```python
preset = policy.preset_for(sky_state.period)
```

`sky_state.period` is one of the five values described in
[Concepts](/guide/concepts); `exposure_policy.presets` maps each to an
`ExposurePreset` with `exposure_us_min`, `exposure_us_max`, `gain_min`,
`gain_max`, `target_mean_adu` and `saturation_threshold`. Everything that
follows happens strictly inside this envelope.

### 2. Cold start

If there are no statistics from a previous frame — the first cycle after
startup, or right after the backend switched preset ranges — the controller
does not guess at a correction. It starts at the *geometric* middle of the
preset:

```python
exposure_us = math.sqrt(preset.exposure_us_min * preset.exposure_us_max)
gain        = math.sqrt(preset.gain_min * preset.gain_max)
```

Geometric rather than arithmetic, because these ranges span orders of magnitude
— the night preset runs 100 ms to 15 s, where the arithmetic midpoint would be
7.5 s and the geometric midpoint is about 1.2 s. The geometric midpoint is the
midpoint in stops, which is the scale the correction loop works in.

### 3. The correction factor, clamped

```python
measured_mean = max(prev_stats.mean, 1e-3)
correction_factor = clamp(preset.target_mean_adu / measured_mean, 0.5, 2.0)
```

`prev_stats.mean` is the mean of a downscaled grayscale copy of the previous
frame (statistics are computed at a maximum dimension of 640 px, so their cost
does not scale with sensor resolution). The ratio of the target to the measured
mean is how far off the last frame was; the `max(..., 1e-3)` guards against a
division by zero on a completely black frame.

The **0.5×–2.0× clamp is the anti-flicker guard**. Without it, one frame ruined
by a passing car's headlights would produce a wild correction, the next frame
would over-correct in the opposite direction, and the sequence would oscillate
visibly. With it, the loop can move at most one stop per cycle in either
direction. A period transition — civil to nautical twilight, say, where the
preset envelope jumps by more than an order of magnitude — therefore eases in
over several cycles instead of jump-cutting. That is deliberate: a keogram or a
timelapse built from these frames should not have a hard seam in it.

### 4. The highlight guard

```python
if prev_stats.p99 > preset.saturation_threshold:
    correction_factor = min(correction_factor, 0.8)
```

The mean alone cannot see clipping. A frame that is 97% dark sky and 3% blown
moon has a perfectly reasonable mean and a completely destroyed highlight.
`FrameStats.p99` — the 99th percentile of the downscaled grayscale frame —
catches exactly that case.

When p99 exceeds the preset's `saturation_threshold` (250 by default, i.e.
essentially clipped in 8-bit terms), the correction is forced to be at most
0.8×, regardless of what the mean-brightness maths suggested. Note it is
`min`, not an assignment: if the mean says to cut harder than 0.8×, that
stronger cut wins. The guard only ever pulls exposure *down*, and it can
override an increase the mean was asking for.

### 5. Split the product, exposure first

The correction is applied to the exposure×gain product, and then split back
into the two knobs:

```python
new_product = current.exposure_us * current.analogue_gain * correction_factor

exposure_us = clamp(new_product / preset.gain_min, preset.exposure_us_min, preset.exposure_us_max)
gain        = clamp(new_product / exposure_us,     preset.gain_min,        preset.gain_max)
```

Read that carefully, because the whole day/night behaviour of the system falls
out of these two lines.

The first line assumes gain sits at its floor and asks exposure to absorb the
entire correction, clamped to the preset's range. The second line then computes
whatever gain is still needed to reach the requested product, clamped to the
preset's gain range.

So as long as the required product is achievable within
`[exposure_us_min × gain_min, exposure_us_max × gain_min]`, the second line
resolves to `gain_min` and gain never rises at all. Only once exposure has
saturated at `exposure_us_max` does gain start climbing to make up the
shortfall. Symmetrically, once exposure bottoms out at `exposure_us_min` the
product cannot be reduced further by exposure and gain is already at its floor,
so the frame stays bright — which is the signal that your preset's lower bound
is too high for the conditions.

This single rule is what keeps noise down at night (there is plenty of exposure
headroom, so gain is rarely needed) *and* keeps gain near its minimum during
the day (the preset's exposure range alone is normally enough). It is one
mechanism, not two code paths for day and night.

Both values are rounded to an integer exposure and a float gain, and returned
as an `ExposureTarget` which the capture worker applies to the camera before
the next grab.

## Default presets

Taken from `_default_exposure_policy()` in `config/schema.py`:

| Period | Exposure min | Exposure max | Gain min | Gain max | Target mean ADU | Saturation threshold |
| --- | --- | --- | --- | --- | --- | --- |
| `day` | 100 µs | 10 ms | 1.0× | 2.0× | 128 | 250 |
| `civil_twilight` | 200 µs | 100 ms | 1.0× | 4.0× | 120 | 250 |
| `nautical_twilight` | 1 ms | 2 s | 1.0× | 8.0× | 110 | 250 |
| `astronomical_twilight` | 10 ms | 8 s | 1.0× | 12.0× | 100 | 250 |
| `night` | 100 ms | 15 s | 1.0× | 16.0× | 100 | 250 |

Two things to notice. The exposure envelopes overlap generously between
adjacent periods — the loop is never asked to make a discontinuous jump at a
boundary, only to walk into a wider room. And `target_mean_adu` falls as the
sky darkens, from 128 in daylight to 100 at night: a darker target frame is
what you want once stars are the subject, and it buys headroom against the
moon.

The bare `ExposurePreset` defaults, used if you add a preset without filling in
every field, are 100 µs–10 ms, gain 1.0–4.0, target 128, saturation 250.

## Editing presets

Presets are ordinary config, patched through `PUT /api/config` or edited in the
web UI's settings tree. Patches are deep-merged dictionary-wise, so you can
touch a single period without restating the rest:

```json
{
  "patch": {
    "exposure_policy": {
      "presets": {
        "night": { "exposure_us_max": 30000000, "gain_max": 8.0 }
      }
    }
  }
}
```

Changes take effect on the next capture cycle — the worker reads
`config_manager.current` at the top of every cycle. There is nothing to
restart.

::: tip
If you are chasing a specific look, watch `GET /api/status`: it reports the
current `exposure_us` and `analogue_gain` alongside `last_stats`, which
contains the `mean`, `p95`, `p99`, `saturated_fraction` and `focus_score` the
loop is actually reacting to.
:::

## Bypassing the loop

`POST /api/camera/exposure-override` installs a manual `ExposureTarget` that
the capture worker uses directly instead of calling the controller. Either
field may be omitted, in which case the current value is kept:

```bash
curl -X POST localhost:8000/api/camera/exposure-override \
     -H 'content-type: application/json' \
     -d '{"exposure_us": 2000000, "analogue_gain": 4.0}'

# release control back to the closed loop
curl -X POST localhost:8000/api/camera/exposure-override \
     -H 'content-type: application/json' \
     -d '{"clear": true}'
```

The override is process state, not config — it does not survive a restart, and
it is not written to disk. `GET /api/status` reports it as
`manual_exposure_override`.
