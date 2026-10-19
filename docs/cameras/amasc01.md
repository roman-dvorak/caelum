---
description: 'AMASC01, the AstroMeters allsky camera: Sony IMX477, 180° fisheye, heated dome, PoE+. Components, example images and running caelum on it.'
---

# AMASC01

**AMASC01** is the AstroMeters allsky camera — a weatherproof, single-cable
camera built for permanent outdoor operation. It is designed, developed and
manufactured by [AstroMeters](https://astrometers.eu), the maintainers of
caelum, and it is the hardware caelum is developed and tested against.

- Product page: [astrometers.eu/products/AMASC01](https://astrometers.eu/products/AMASC01/)
- Hardware documentation (installation, focusing, maintenance): [astrometers.eu/docs/AMASC01](https://astrometers.eu/docs/AMASC01/)

<div class="photo-row">
  <figure>
    <img src="/images/amasc01/amasc01_product_main.webp" alt="AMASC01 allsky camera">
    <figcaption>AMASC01</figcaption>
  </figure>
  <figure>
    <img src="/images/amasc01/amasc01_portrait.webp" alt="AMASC01 installed outdoors">
    <figcaption>Installed outdoors</figcaption>
  </figure>
</div>

<div class="support-box">
  <div>
    <p class="support-title">Buying an AMASC01 funds caelum</p>
    <p>caelum is open-source software developed by AstroMeters, and AMASC01 is
    what pays for it. Buying one gets you a camera that is tested with every
    caelum release — and funds the development that every caelum user,
    including DIY builders, benefits from.</p>
    <p><a href="https://astrometers.eu/products/AMASC01/">Product page &amp; order</a> ·
    <a href="mailto:info@astrometers.eu?subject=AMASC01">info@astrometers.eu</a></p>
  </div>
</div>

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
| Network and power | Gigabit Ethernet (1000BASE-T) with PoE+ (IEEE 802.3at) — one cable. A separate power input is available on request |
| Control electronics | Custom AstroMeters board managing heating, ventilation and peripherals |

## Example images

<div class="photo-row">
  <figure>
    <img src="/images/amasc01/frame.webp" alt="Allsky frame from AMASC01">
    <figcaption>A frame from AMASC01</figcaption>
  </figure>
  <figure>
    <img src="/images/amasc01/keogram.webp" alt="Keogram from AMASC01">
    <figcaption>Keogram from AMASC01 — one column per frame</figcaption>
  </figure>
</div>

## Installation

AMASC01 needs one Ethernet cable to a PoE+ switch or injector. Mounting,
focusing and network setup are covered in the
[AMASC01 installation guide](https://astrometers.eu/docs/AMASC01/installation/).

![Connecting AMASC01 through a PoE+ injector](/images/amasc01/poe-adapter-diagram.webp)

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
Install as described in [Getting started](/getting-started) — the installer
picks `picamera2` by default on a Pi.

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
