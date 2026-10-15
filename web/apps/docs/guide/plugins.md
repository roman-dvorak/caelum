# Plugins and derivative workers

caelum's extension point is one small class with four optional hooks. The
built-in derivative workers — the keogram builder and the meteor detector —
implement exactly the same interface and are dispatched by exactly the same
code, which is what keeps the extension point honest: it is not a speculative
API, it is the API the shipped features are written against.

## The worker interface

```python
class DerivativeWorker:
    id: str

    def on_frame(self, frame: ProcessedFrame) -> None: ...
    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]: ...
    def modify_image(self, image: np.ndarray, frame: ProcessedFrame) -> np.ndarray: ...
    def create_derivative(self, context: dict[str, Any]) -> Derivative | None: ...
```

It is deliberately **not** an ABC. Every hook has a working no-op default, so
there is nothing a subclass is required to implement — override only what you
actually need.

- **`on_frame(frame)`** — called for every captured frame, off the capture
  thread. This is where you accumulate state: append a keogram column, stash
  the previous frame for differencing, update a running histogram.
- **`provide_overlay_elements(frame)`** — return a list of `OverlayElement` to
  attach to the frame's metadata. They are appended to whichever frame is
  currently latest and re-broadcast to live WebSocket viewers. Set
  `source` to your plugin id so the renderer and the reader can tell where an
  element came from.
- **`modify_image(image, frame)`** — return a transformed image. Declared on
  the interface and intended to chain in `order` sequence.
- **`create_derivative(context)`** — called every frame, right after
  `on_frame`. Return `None` on most calls; return a `Derivative` only when your
  own internal state says it is genuinely time to produce one — a finished
  keogram at day rollover, a detection that just fired.
  `context["frame"]` is always the frame that was just processed.

`modify_image` is chained across every enabled worker in ascending `order`
before `on_frame`/`provide_overlay_elements`/`create_derivative` run — see
`DerivativePool._run_modify_chain`. Only `ProcessedFrame.image` passes through
the chain; the thumbnail JPEG and any raw FITS write are already fixed by the
time it runs, so a `modify_image` change is visible to derivative workers
(keograms, meteor detection) but never to the stored thumbnail/raw file or the
live view — an overlay element (see `provide_overlay_elements` above) is the
right tool for anything that should show up on the Dashboard or remote-web.

A `Derivative` is:

```python
@dataclass(frozen=True)
class Derivative:
    kind: str
    created_at: datetime
    image: np.ndarray | None = None
    path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Return one with an `image` and the pool writes it to
`<data_dir>/derivatives/<YYYY>/<MM>/<DD>/<YYYYMMDD-HHMMSS>_<worker_id>_<kind>.<ext>`, PNG for
kinds starting with `keogram` and JPEG otherwise, and logs the path.

## `Plugin`

A `Plugin` is a `DerivativeWorker` with two additions:

```python
class Plugin(DerivativeWorker):
    id: ClassVar[str]
    config_schema: ClassVar[type[BaseModel] | None] = None

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
```

`id` is the key the config store namespaces this plugin's settings under.
`config_schema`, if set, is a Pydantic model the loader validates the settings
dict against *before* constructing the plugin — a plugin with invalid config is
logged with a traceback and skipped, not constructed with garbage.

```python
from pydantic import BaseModel
from caelum.plugins.base import Plugin
from caelum.capture.metadata import OverlayElement


class CloudCoverSettings(BaseModel):
    threshold: float = 0.35
    label: str = "cloudy"


class CloudCoverPlugin(Plugin):
    id = "cloud_cover"
    config_schema = CloudCoverSettings

    def on_frame(self, frame):
        # frame.stats is already computed; focus_score drops on overcast skies
        self._cloudy = frame.stats.focus_score < self.settings["threshold"] * 100

    def provide_overlay_elements(self, frame):
        if not self._cloudy:
            return []
        return [OverlayElement(type="badge", source=self.id,
                               payload={"text": self.settings["label"]})]
```

## The config block

Every plugin id gets one entry under `plugins`:

```json
{
  "plugins": {
    "cloud_cover": {
      "enabled": true,
      "order": 50,
      "settings": { "threshold": 0.4, "label": "overcast" }
    },
    "star_count": {
      "enabled": false,
      "order": 100,
      "settings": {}
    }
  }
}
```

- **`enabled`** (default `true`) — a disabled plugin is skipped entirely at load
  time; it is never constructed.
- **`order`** (default `100`) — sort key, ascending, lower runs first.
- **`settings`** (default `{}`) — an intentionally open dict. The app-level
  config store treats it as an opaque blob and validates nothing; each plugin
  validates its own shape against its declared `config_schema`. That is why
  adding a plugin never requires a change to `config/schema.py`.

Read and write them through the API:

```bash
curl -s localhost:8000/api/plugins                 # sorted by order, ascending
curl -X PUT localhost:8000/api/plugins/cloud_cover \
     -H 'content-type: application/json' \
     -d '{"enabled": true, "order": 20, "settings": {"threshold": 0.5}}'
```

`PUT /api/plugins/{id}` only sends the fields you provide, and the config
manager deep-merges the patch, so you can flip `enabled` without restating
`settings`.

## What `order` governs

`PluginLoader.load()` builds the loaded-plugin list from `config.plugins` and
sorts it by `order` ascending. That single ordering is what governs:

- the sequence in which `modify_image` would chain, each worker receiving the
  previous worker's output;
- the order overlay elements are appended in, and therefore the order the
  renderer draws them — a lower `order` draws first, so a higher `order` draws
  on top;
- the order `on_frame` and `create_derivative` are dispatched in.

Pick numbers with gaps (10, 20, 30) so you can slot something in later without
renumbering. Anything that must draw underneath other annotations gets a low
number; a watermark or a frame border that should sit over everything gets a
high one.

::: warning
Workers are dispatched to a thread pool, one submission per worker per frame,
so `order` fixes dispatch order but does not serialise execution. Do not build
a plugin that depends on another plugin having *finished* first.
:::

## Loading

For now, "discovery" means matching `AppConfig.plugins` keys against a list of
`Plugin` classes the caller has already registered — either passed to
`PluginLoader(available_classes=...)` or added later with
`register_class()`. There is no directory scan and no entry-point scan, because
there are no third-party plugins yet to discover and that machinery would be
speculative. A `plugins/installed/` scan is a natural extension of
`register_class` once a real plugin exists.

An id in the config with no registered class is skipped with a warning:

```
No plugin class registered for id 'cloud_cover' — skipping
```

::: warning
`main.py` currently constructs `PluginLoader()` with no available classes, so
in the shipped binary every configured plugin id produces that warning. To run
your own plugin today you need to register its class in `main.py` before
`plugin_loader.load()` is called.
:::

## Worked example: the keogram worker

A keogram is a single image of a whole night: take the centre column of every
frame, stand them side by side, and you get time on the x-axis and sky altitude
on the y-axis.

`KeogramWorker` (id `keogram`) does exactly that.

- **`on_frame`** extracts the single centre column of the frame and resizes it
  to a 2 px wide, 240 px tall strip, then appends it to an in-memory buffer. It
  also compares the frame's date against the buffer's date; when they differ it
  sets a rollover flag and returns *without* appending, so the new day's column
  is not mixed into yesterday's image.
- **`create_derivative`** handles two cases. On rollover it concatenates the
  whole buffer along the x-axis and returns a `Derivative` of kind `keogram`
  with `{"date": ..., "frame_count": ...}`, then reseeds the buffer with the
  current frame's column and resets the date. Otherwise, if at least five
  minutes have passed since the last flush, it emits a `keogram_live` — the
  same concatenation of whatever has accumulated so far.

The live flush is what makes the keogram useful *during* the night rather than
at dawn: every five minutes there is a fresh partial image on disk, and the web
UI has something to show. Both kinds are written as PNG.

State — the column buffer, the current date, the last flush time — lives in the
worker instance in this process, which is exactly why derivative workers are
dispatched to threads rather than processes.

## Worked example: the meteor detector

`MeteorDetectionWorker` (id `meteor_detection`) is a frame-difference streak
detector. It is intentionally simple for this generation of the stack — a real
detection pipeline, but not an astrometric one.

- **`on_frame`** converts the frame to grayscale and downscales it so the
  longest side is at most 480 px, then, if a previous frame of matching shape
  exists, submits the actual detection to the shared `ProcessPoolExecutor` and
  waits for the result. The bounding box that comes back is normalised to
  fractions of the frame's width and height and stashed.
- **`provide_overlay_elements`** turns a stashed detection into a
  `detection_box` overlay element with `source: "meteor_detection"` and a
  payload of `{x, y, w, h, label: "possible meteor"}` in normalised
  coordinates.
- **`create_derivative`** returns a `meteor_crop` derivative carrying the
  full-resolution frame and the bounding box in its metadata, then clears the
  stash so a single detection is emitted exactly once.

The detection itself is a module-level function:

```python
def detect_streak(prev_gray, curr_gray, threshold) -> BoundingBox | None:
```

It absolute-differences the two frames, thresholds at `diff_threshold`
(default 40), finds external contours, and keeps the most elongated one with
an aspect ratio of at least 3:1 and an area of at least 4 px. Being
module-level and taking only numpy arrays and a float makes it picklable, which
is what lets it run on a second core.

That split is the pattern to copy: **stateful accumulation stays in the worker
on a thread; a heavy stateless computation goes to the process pool.**
`DerivativePool` hands every worker a reference to the same process pool for
exactly this purpose.

## Worked example: the overlay plugin

`OverlayWorker` (id `overlay`) is what backs the web UI's visual overlay
editor — masks, text labels and inserted images an admin configures by
dragging boxes over the live preview rather than writing Python. Its whole
job is `provide_overlay_elements`: it turns each `OverlayElementDef` in
`settings.elements` into a `mask`, `custom_label` or `custom_image` overlay
element. Label `template` strings are resolved with plain `str.format()`
against the frame's metadata (`{exposure_us}`, `{sky_state.period}`, etc.) —
an unknown placeholder falls back to showing the raw template rather than
dropping the element or crashing the pipeline.

Masking here means an opaque box drawn on top wherever the image is
displayed — it is `provide_overlay_elements`, not `modify_image`, precisely
because (per the note above) only an overlay element reaches the live view,
the Dashboard and remote-web; it does not redact the stored thumbnail/raw
file.

## Worked example: the telescope-position widget

`TelescopePositionWorker` (id `telescope_position`) is a small demo proving
the same interface can back a "widget", not just static annotations: it
contributes a `telescope_marker` overlay element showing where a telescope is
pointed, projected onto the allsky image with the standard equidistant-fisheye
formula (`r = radius * (90 - altitude) / 90`). `source: "simulated"` — the only
mode implemented today — sweeps a fake alt/az over a few minutes rather than
querying real hardware; swapping in a query against an INDI/ASCOM server is a
drop-in replacement for that one function, everything else about the plugin
stays the same.

Both `overlay` and `telescope_position` ship disabled by default (an empty
mask list or a fake telescope marker showing up unasked would be a bad
default) — enable them from the Overlay editor page or `PUT /api/plugins/{id}`.

::: warning
`overlay`'s `custom_image` elements reference an asset by filename, resolved
against `data_dir/overlay_assets/` locally (`GET /api/overlay/assets/{name}`,
admin-only to upload/delete) and against `<camera_slug>/overlay_assets/` on
the remote archive — the uploader's whole-tree reconciliation pass mirrors
that directory the same way it mirrors `darks/`, so no separate sync step is
needed.
:::
