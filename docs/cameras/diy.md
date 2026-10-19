---
description: 'Build your own allsky camera for caelum: recommended Raspberry Pi, camera module, lens, dome and dew heater, and the pitfalls to avoid.'
---

# DIY cameras

caelum does not need AMASC01. Any Linux machine with a camera that one of the
[backends](/guide/cameras) can drive will run the whole stack. This page is a
starting point for building your own; it is community-supported and not tested
by the maintainers the way [AMASC01](/cameras/amasc01) is.

## A typical build

| Part | Recommendation |
|---|---|
| Computer | Raspberry Pi 4 or 5. Anything that runs Linux works for `opencv`; `picamera2` needs a Pi |
| Camera | Raspberry Pi HQ camera (IMX477) or another libcamera-supported module, for the `picamera2` backend |
| Lens | A fisheye that covers 180° on the sensor you chose (for the HQ camera: C/CS-mount, ~1.5–2 mm) |
| Dome | Acrylic or glass dome over the lens |
| Dew heater | A heater around the lens under the dome. [AMASCHR02](https://astrometers.eu/accessories/AMASCHR02/) (below) is self-regulating (PID, 8–14 V) and needs no software |
| Storage | A good SD card or, better, USB/NVMe SSD — caelum writes continuously |
| Power | PoE HAT or a supply rated for the Pi plus heater |
| Network | Ethernet if possible; [upload](/guide/upload) can tolerate a poor link but the web UI is nicer with a good one |

<figure class="photo">
  <img src="/images/amaschr02.webp" alt="AMASCHR02 heating ring">
  <figcaption>AMASCHR02 — an autonomous dew heater ring for camera modules under a dome</figcaption>
</figure>

## Things that bite

- **Manual exposure is mandatory.** caelum disables the camera's
  auto-exposure and runs its own loop. A camera whose driver will not accept
  manual exposure and gain cannot be controlled properly — this is common with
  cheap UVC webcams. See the [`opencv` caveats](/guide/cameras#opencv).
- **Dew.** An unheated dome fogs up on most clear nights, exactly when you
  want images.
- **Heat in sunlight.** A sealed box in the sun gets hot; plan for ventilation
  or shading of the electronics.
- **Time.** Exposure control is driven by the sun's altitude, so the clock
  must be right. Without a network, add an RTC.

## Getting started

1. Install caelum as in [Getting started](/getting-started), choosing
   `--camera picamera2` or `--camera opencv`.
2. Set your observing site (`location.lat`, `location.lon`) in the config —
   sun and moon geometry depend on it. See [Concepts](/guide/concepts).
3. Check the first frames in the [web interface](/guide/web-ui) and widen the
   exposure presets if your optics are slower or faster than the defaults.

Built something that works? Share it in the
[repository](https://github.com/roman-dvorak/caelum) so it can be listed on
[Supported cameras](/cameras/).

::: tip Prefer not to build one?
[AMASC01](/cameras/amasc01) is a finished, tested caelum camera — and buying
one funds caelum's development.
:::
