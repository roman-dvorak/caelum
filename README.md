# caelum

Headless capture engine for (not only) allsky cameras. Owns the camera, computes
sky state (sun/moon altitude, twilight period), drives exposure/gain, processes
frames in RAM, and persists/uploads only what's decided to be kept.

See `../caelum-web` for the local and remote React frontends, and
`/home/roman/.claude/plans/pot-eboval-bych-zde-zalo-it-cuddly-squid.md` for the
full architecture writeup.

## Development

```bash
uv sync --group dev
uv run pytest
```

No real camera is required for development — the mock backend
(`CAELUM_CAMERA_BACKEND=mock`, the default outside a Raspberry Pi) generates
synthetic frames with simulated exposure/gain-dependent brightness.

```bash
uv run caelum
```

### Testing with a real webcam

Set `camera.backend` to `"opencv"` (or `CAELUM_CAMERA_BACKEND=opencv` to
override for one run) to capture from any UVC/V4L2 webcam via OpenCV —
useful for exercising the real capture pipeline on a PC with no astro
hardware attached. `camera.sensor_id` doubles as the device selector: `"0"`
opens `/dev/video0`, or give an explicit path.

Manual exposure/gain support varies a lot across consumer webcam drivers —
treat this backend as a pipeline-testing tool, not a source of accurate
photometry. In particular, the default `exposure_policy.day` preset
(0.1–10ms) is tuned for a bright daytime sky and will read as a black frame
indoors; either widen that preset for a local test config, or use
`POST /api/camera/exposure-override` with something like
`{"exposure_us": 100000}` to see a normally-lit room.

### Local systemd service (optional)

There's no systemd unit active anywhere by default — local dev just runs
`scripts/dev_run.sh` / `uv run caelum` directly, and `systemd/caelum.service.template`
is a template for a real Raspberry Pi deployment (`WorkingDirectory`,
`.venv` path, and `caelum` user need adjusting for wherever it's installed).
To run it as a persistent local service instead (e.g. to leave a webcam
test running in the background), copy the template, fill in the paths, and
`systemctl --user enable --now` it — ask first if you'd like this set up,
since it changes what starts automatically on this machine.

## Configuration

Runtime config is a single JSON document (see `config/default.json` for the
shape), kept in sync between disk (`config/config.json`, the durable source of
truth) and Redis (fast runtime reads + pub/sub change notifications) — see
`src/caelum/config/manager.py`. Copy `.env.example` to `.env` to override
bootstrap paths/ports.
