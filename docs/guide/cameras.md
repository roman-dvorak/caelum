# Camera backends

A camera backend is a small class with five methods — `open`, `close`,
`configure`, `set_controls`, `capture_frame` — and a `capabilities` attribute.
Exactly one instance is created at startup and owned by exactly one
`CaptureWorker` for the process lifetime; `capture_frame()` is blocking and is
called only from that worker's thread.

Every backend hands back a `RawFrame`:

```python
@dataclass(frozen=True)
class RawFrame:
    image: np.ndarray          # already RGB
    exposure_us: int
    analogue_gain: float
    sensor_timestamp_ns: int
    captured_at: datetime
```

`image` is RGB, already debayered. For this generation of the stack, backends
are expected to hand back ISP-processed frames (picamera2's `main` stream, or
OpenCV's converted BGR). A raw-Bayer capture path with its own debayer step is
a future extension, not something the pipeline currently carries.

## Selecting a backend

`camera.backend` in the config takes one of three values — `mock`, `picamera2`,
`opencv` — and selection is explicit, never a silent fallback:

```python
def create_camera_backend(cfg: CameraConfig) -> CameraBackend:
    if cfg.backend == "mock": ...
    if cfg.backend == "opencv": ...
    if cfg.backend == "picamera2": ...   # imported lazily, here
    raise ValueError(f"Unknown camera backend: {cfg.backend!r}")
```

`picamera2` is imported inside the branch, so a development machine without it
installed can import the package freely as long as it never selects that
backend.

## `mock`

A synthetic-frame backend for development and CI. It builds a fixed 320×240
scene — a horizon brightness gradient plus fifteen stars placed from a fixed
seed — and scales it by `(exposure_us / 10000) * analogue_gain` with a little
Gaussian noise on top, so the exposure feedback loop has something real to
converge against.

Its resolution is deliberately fixed and independent of `camera.resolution`;
`configure()` is a no-op. This backend exists to exercise the control loop, the
event bus, the derivative pool and the API quickly and deterministically, not
to simulate a sensor's pixel count.

## `picamera2`

The Raspberry Pi camera module backend, via picamera2/libcamera. It is only
importable where the `picamera2` extra is installed (ARM-only — the dependency
carries an `aarch64`/`armv7l` marker), and if you select it without that
package present you get a clear `RuntimeError` rather than a mysterious import
failure.

`open()` builds a still configuration with `main={"size": resolution}` and
starts the camera. `set_controls()` sets three controls together:

```python
self._picam2.set_controls({
    "AeEnable": False,          # the app owns exposure, never the camera
    "ExposureTime": exposure_us,
    "AnalogueGain": analogue_gain,
})
```

`capture_frame()` takes a request, pulls the `main` array and the request
metadata, then releases the request. If the platform's default format includes
an alpha channel it is dropped, keeping RGB order. Exposure, gain and the
sensor timestamp are read back from libcamera's metadata, so the values stored
with the frame are what the sensor actually applied, not what was requested.

::: warning
This backend has no automated test coverage — there is no Pi camera in CI.
Validate it against real hardware, particularly the channel order and the
alpha-channel handling in `capture_frame()`.
:::

## `opencv`

A generic UVC/V4L2 webcam backend. Its purpose is to let the *entire* pipeline
— capture loop, sky-state driven policy, derivatives, API, web UI — be
exercised on an ordinary PC with a webcam plugged in, with no astro hardware
required.

### Device selection

`camera.sensor_id` doubles as the V4L2 device selector. The backend tries to
parse it as an integer; if that succeeds it is used as a device index,
otherwise it is passed through as an explicit device path.

```json
{
  "camera": {
    "backend": "opencv",
    "sensor_id": "0",
    "resolution": [1280, 720]
  }
}
```

- `"0"` → device index 0, i.e. `/dev/video0`
- `"/dev/video2"` → that exact device node
- `"cam0"` (the schema default) → passed through as a path, which will not
  open; change it when switching to this backend

The capture object is opened with `cv2.VideoCapture(device, cv2.CAP_V4L2)`, and
a device that will not open raises
`RuntimeError: Could not open V4L2 camera at ...`.

### Resolution negotiation

`camera.resolution` (default `[4056, 3040]`, sized for an HQ camera sensor) is
requested via `CAP_PROP_FRAME_WIDTH` / `CAP_PROP_FRAME_HEIGHT`, then read back.
Webcams routinely ignore the request and pick the nearest mode they support. If
the read-back differs from the request, the backend logs

```
Camera '0' negotiated (640, 480) instead of requested (4056, 3040)
```

and adopts the negotiated size as both its own resolution and its reported
`CameraCapabilities.max_resolution`. Nothing downstream breaks — statistics,
thumbnails and derivatives all work from the actual array shape — but check the
log if frames are smaller than you expected.

### Exposure and gain

`open()` sets `CAP_PROP_AUTO_EXPOSURE` to `1`, V4L2's `V4L2_EXPOSURE_MANUAL`
enum value, which OpenCV's Linux V4L2 backend passes through directly. If the
driver refuses, you get:

```
Camera '0' did not accept manual-exposure mode — AE may still be active
```

`set_controls()` then writes `CAP_PROP_EXPOSURE` in units of 100 µs (the common
UVC convention once manual mode is engaged) and `CAP_PROP_GAIN` as the raw gain
value. The values reported back in the `RawFrame` are the last values *set*,
not values read back from the device, and `sensor_timestamp_ns` is `0` — UVC
devices do not expose a hardware timestamp worth trusting.

::: warning
Manual exposure and gain support varies enormously across consumer webcam
drivers — units, ranges, and whether manual mode is honoured at all are all
device- and driver-specific. Treat this backend as a pipeline-testing tool, not
as a source of accurate photometry.
:::

## The `CAELUM_CAMERA_BACKEND` override

`config.json`'s `camera.backend` is authoritative. Setting the environment
variable `CAELUM_CAMERA_BACKEND` overrides it for one run:

```python
backend_name = settings.camera_backend_override or cfg.camera.backend
camera = create_camera_backend(cfg.camera.model_copy(update={"backend": backend_name}))
```

Only `backend` is overridden — `sensor_id` and `resolution` still come from the
config. The variable is unset by default and there is deliberately no
auto-detection, so a misconfigured Pi fails loudly instead of quietly capturing
synthetic frames for a week.

```bash
CAELUM_CAMERA_BACKEND=opencv uv run caelum
```

## Testing with a plain USB webcam

This is the fastest way to exercise the real capture path without astro
hardware:

```bash
CAELUM_CAMERA_BACKEND=opencv uv run caelum
```

with `camera.sensor_id` set to `"0"` in your config.

::: warning The daylight preset will look broken indoors
The default `day` exposure preset is 100 µs to 10 ms at 1–2× gain. That is
tuned for a genuinely bright daytime sky through an allsky lens, and pointed at
an ordinary lit room it produces a black frame — the control loop is working
exactly as configured, there simply is not enough light.

Two ways out. Widen the preset in a local test config:

```json
{
  "exposure_policy": {
    "presets": {
      "day": { "exposure_us_min": 1000, "exposure_us_max": 200000, "gain_min": 1.0, "gain_max": 8.0 }
    }
  }
}
```

Or bypass the loop entirely with a manual override:

```bash
curl -X POST localhost:8000/api/camera/exposure-override \
     -H 'content-type: application/json' \
     -d '{"exposure_us": 100000}'
```

Clear it again with `{"clear": true}`. While an override is active the closed
loop is not consulted at all, and `GET /api/status` reports
`manual_exposure_override: true`.
:::
