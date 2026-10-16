# AMASC01

**AMASC01** is the AstroMeters allsky camera — a weatherproof, single-cable
camera built for permanent outdoor operation. It is designed, developed and
manufactured by [AstroMeters](https://astrometers.eu), the maintainers of
caelum, and it is the hardware caelum is developed and tested against.

- Product page: [astrometers.eu/products/AMASC01](https://astrometers.eu/products/AMASC01/)
- Hardware documentation (installation, focusing, maintenance): [astrometers.eu/docs/AMASC01](https://astrometers.eu/docs/AMASC01/)

## Components

| Part | What it is |
|---|---|
| Image sensor | Sony IMX477, 12.3 MP, 1.55 µm pixels (Raspberry Pi HQ camera class) |
| Lens | 180° fisheye covering the whole sky, with a focusing mechanism accessible without disassembly |
| Computer | Raspberry Pi single-board computer inside the enclosure |
| Dome | Optical dome with a heater ring ([AMASCHR01](https://astrometers.eu/accessories/AMASCHR01/), SHT4x temperature/humidity sensor) against dew and frost |
| Ventilation | Active ventilation of the enclosure plus dedicated CPU cooling |
| Environmental sensors | Dome temperature; body temperature, humidity and pressure; optional external sensor |
| Timekeeping | Battery-backed RTC, so frames are timestamped correctly with no network |
| Network and power | Gigabit Ethernet (1000BASE-T) with PoE+ (IEEE 802.3at) — one cable. Plain 802.3af PoE is not enough. A separate power input is available on request |
| Control electronics | Custom AstroMeters board managing heating, ventilation and peripherals |

## Running caelum on AMASC01

The camera is driven by the [`picamera2` backend](/guide/cameras#picamera2):

```json
{
  "camera": {
    "backend": "picamera2",
    "resolution": [4056, 3040]
  }
}
```

`[4056, 3040]` is the IMX477's full resolution and already the schema default.
Install as described in [Deployment](/guide/deployment) — the installer picks
`picamera2` by default on a Pi.

::: info Thermal control is separate
Dome heating, ventilation and the environmental sensors are run by the
camera's own control electronics and tooling, independently of caelum. caelum
does not yet read those sensors or drive the heater.
:::

## Getting one

AMASC01 is available from AstroMeters — see the
[product page](https://astrometers.eu/products/AMASC01/) or write to
[info@astrometers.eu](mailto:info@astrometers.eu). Modified versions (lens and
field of view, sensor, power, mounting) can be made on request.
