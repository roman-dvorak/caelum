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

## Configuration

Runtime config is a single JSON document (see `config/default.json` for the
shape), kept in sync between disk (`config/config.json`, the durable source of
truth) and Redis (fast runtime reads + pub/sub change notifications) — see
`src/caelum/config/manager.py`. Copy `.env.example` to `.env` to override
bootstrap paths/ports.
