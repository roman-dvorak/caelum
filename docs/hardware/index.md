# Supported hardware

caelum runs on a Linux computer with a camera attached. What it needs from the
camera is a [backend](/guide/cameras) that can set exposure and gain manually
and hand back a frame; everything downstream — exposure control, storage,
derivatives, upload — is the same whichever camera produced it.

There are two ways to get a camera running caelum:

| | [AMASC01](/hardware/amasc01) | [DIY camera](/hardware/diy) |
|---|---|---|
| What it is | Finished outdoor allsky camera from AstroMeters | Your own build from off-the-shelf parts |
| Sensor | Sony IMX477, 180° fisheye | Anything with a supported backend |
| Backend | `picamera2` | `picamera2` or `opencv` |
| Enclosure, heating, power | Included (heated dome, ventilation, PoE+) | Up to you |
| Support | Maintained and tested by AstroMeters | Community, best effort |

## Backends at a glance

| Backend | Hardware | Status |
|---|---|---|
| `picamera2` | Raspberry Pi camera modules via libcamera (HQ camera / IMX477 and others) | Primary target; used on AMASC01 |
| `opencv` | Any UVC/V4L2 webcam | For testing the pipeline; manual exposure support varies by driver |
| `mock` | None — synthetic frames | Development and CI |

Details, configuration and caveats for each: [Camera backends](/guide/cameras).
