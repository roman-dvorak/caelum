# Capture programs

What the camera captures each slot is decided by a **capture program**: a
small Python module with one coroutine. Caelum's own automatic exposure is
the built-in `default.py`; others plug in the same way.

```python
PROGRAM = {"description": "Two exposures per slot", "kind": "hdr"}


async def capture(ctx):
    short = await ctx.capture(exposure_us=1_000)
    long = await ctx.capture(exposure_us=ctx.commanded.exposure_us, analogue_gain=ctx.commanded.analogue_gain)
    return ctx.capture_set([short, long], kind="hdr", representative=long)
```

## How it runs

- `capture(ctx)` is called **once per capture slot** of the wall-clock grid.
  The **first** `ctx.capture()` of a run is timed so the middle of its
  exposure lands on the slot; later captures in the same run follow straight
  away.
- Return what should be kept: a frame, a list of frames, `ctx.capture_set(...)`,
  or `None`. Frames not returned are discarded.
- A set of several frames is stored with one representative (shown live,
  listed, used by derivatives and uploads); the others go next to it, and the
  raw frames into one multi-frame DNG — see [dng-capture-sets.md](dng-capture-sets.md).
  Keep sets within `processing.slots` frames, or they are dropped whole.

## `ctx`

| | |
|---|---|
| `await ctx.capture(exposure_us, analogue_gain=1.0, *, colour_gains=None, raw=True, **extra)` | take one frame |
| `ctx.capture_set(frames, kind="series", representative=None, **annotations)` | group frames into a set |
| `await ctx.sleep(seconds)` | wait (stops cleanly on shutdown) |
| `ctx.state` | dict kept between runs of the same program version |
| `ctx.params` | `capture.params.<program name without .py>` from the config |
| `ctx.config`, `ctx.sky` | app config and the sky state (period, sun/moon) |
| `ctx.capabilities` | the camera's `model`, `exposure_us` and `analogue_gain` ranges, `raw`, `colour_gains` |
| `ctx.commanded` | exposure/gain to use next — read it, and set it (the status shows it) |
| `ctx.exposure_controller` | the PI regulator `default.py` uses |
| `ctx.camera_fresh`, `ctx.slot`, `ctx.interval_s`, `ctx.stream_mode`, `ctx.overrides` | run context |
| `ctx.log` | logger — messages go to the journal and to Check/Test reports |

A frame (`CapturedFrame`) has `raw` (the camera frame: `image`,
`exposure_us`, `analogue_gain`, `camera_metadata`, `capture_settings`),
`brightness` (`median`, `p99` of the central circle, 0–255), `sky`,
`requested`, `index`, and `annotations` (a dict stored with the frame).

**Nothing is refused for exceeding the camera:** values outside its ranges
are clamped to the nearest possible, options it doesn't have (incl. any
`extra` keyword) are ignored, and the frame's metadata records what was
requested, what was applied, and what was clamped or ignored.

## Built-in programs

| | |
|---|---|
| `default.py` | automatic exposure (PI regulator in EV) |
| `fixed.py` | fixed `exposure_us` / `analogue_gain` / `colour_gains` from params |
| `hdr.py` | bracket (`ev_steps`, default −2/0/+2 EV) around the automatic exposure, adaptive |
| `darks.py` | `count` dark frames at one exposure, for calibration |

Importing a built-in from your own program works too, e.g.
`from caelum.capture_programs import default` and `await default.capture(ctx)`.

## Managing programs

Web UI: **Manage → Capture programs** (admins). API under `/api/capture-programs`:
list, get, `PUT` save, upload, delete, `check`, `{name}/test`,
`test-runs/{id}`, `{name}/activate`, `status`.

- **Save ≠ deploy.** Production runs the archived version recorded at
  activation (`capture.active_program` + `capture.active_sha256`); editing the
  file changes nothing until it is activated again. Every activated or tested
  version is kept in `<programs dir>/.archive/<sha256>.py`.
- **Check** parses the program (nothing executed), then imports it and runs
  it twice against a simulated camera with the real camera's limits — in a
  separate process, never in the server.
- **Test once** runs the saved program on the real camera right after the next
  slot, with its own state and a copy of the regulator. What it returns is
  stored **exactly as production stores it** — same processing, same
  `thumbnails/…` / `raw/…` layout (a set: representative, `<stem>_set/`
  members, one multi-frame DNG) — under `<data_dir>/program-tests/<run id>/`,
  next to a `report.json`. Raw frames are kept regardless of the time of day;
  nothing is published or uploaded.
- **Activate** checks again, archives, and switches production from the next
  slot.
- A program that fails `capture.max_consecutive_failures` times in a row (or
  can't be loaded) is replaced by `default.py` until another version is
  activated; one that hangs gets the process restarted, and it starts in that
  fallback. The status (`/api/status` → `capture_program`) shows it.
- Every frame records its provenance: program name and sha256, caelum version,
  camera model and capabilities, config hash.

User programs live in `CAELUM_CAPTURE_PROGRAMS_DIR` (default
`<data_dir>/capture-programs`). They are arbitrary Python running with the
service's rights — admin only, and `capture.editing_enabled: false` turns
editing off entirely.
