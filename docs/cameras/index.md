# Supported cameras

caelum runs on a Linux computer with a camera attached. What it needs from the
camera is a [backend](/guide/cameras) that can set exposure and gain manually
and hand back a frame; everything downstream — exposure control, storage,
derivatives, upload — is the same whichever camera produced it.

| Camera | Type | Sensor & optics | Backend | Enclosure, heating, power | Support |
|---|---|---|---|---|---|
| [**AMASC01**](/cameras/amasc01) | Finished outdoor allsky camera by AstroMeters | Sony IMX477, 180° fisheye | `picamera2` | Included: heated dome, ventilation, PoE+ | Maintained and tested by AstroMeters |
| [**DIY camera**](/cameras/diy) | Your own build from off-the-shelf parts | Raspberry Pi camera module or UVC webcam | `picamera2`, `opencv` | Up to you | Community, best effort |

<div class="support-box">
  <img src="/images/amasc01/amasc01_product_main.webp" alt="AMASC01 allsky camera">
  <div>
    <p class="support-title">Buying an AMASC01 funds caelum</p>
    <p>caelum is open source and developed by AstroMeters. Every AMASC01 sold
    pays for that development — new features, hardware support and fixes that
    every caelum installation gets, DIY builds included.</p>
    <p><a href="/cameras/amasc01.html">About AMASC01</a> ·
    <a href="https://astrometers.eu/products/AMASC01/">Product page &amp; order</a></p>
  </div>
</div>

## Backends at a glance

| Backend | Hardware | Status |
|---|---|---|
| `picamera2` | Raspberry Pi camera modules via libcamera (HQ camera / IMX477 and others) | Primary target; used on AMASC01 |
| `opencv` | Any UVC/V4L2 webcam | For testing the pipeline; manual exposure support varies by driver |
| `mock` | None — synthetic frames | Development and CI |

Details, configuration and caveats for each: [Camera backends](/guide/cameras).
