---
description: 'From a camera to the first night of allsky images: install caelum, log in, set the observing site, check the picture and publish it.'
sidebar: false
pageClass: getting-started
---

# Getting started

Six steps from a camera on a pole to the first night of images. Each one links
to the full guide; the [User manual](/manual) explains how everything fits
together.

<div class="steps">

<div class="step">

## Get a camera

caelum runs on a Raspberry Pi with a camera module, under a dome, outdoors. The
simplest way is an AMASC01 — a finished, weatherproof camera with a heated dome
and a single PoE+ cable. You can also build your own.

- [AMASC01](/cameras/amasc01)
- [Build your own](/cameras/diy)
- [Supported cameras](/cameras/)

</div>

<div class="step">

## Install caelum

One command on the camera's Raspberry Pi sets everything up and starts caelum,
which from then on runs on its own and comes back after every power cut.
Choose the https option; the web interface is then at `https://<camera>/`.

- [Installation](/guide/installation)
- [Deployment](/guide/deployment)
- [Running from source](/guide/development)

</div>

<div class="step">

## Log in

Open the camera's address in a browser. The first time, log in as `admin` with
the password the installer created and set your own under **Accounts**. You
land on the **Dashboard**: the newest frame, the current sky period and the
exposure caelum has chosen.

![The caelum dashboard](/images/screenshots/dashboard.webp)

- [First login](/guide/installation#first-login)
- [Access & security](/guide/security)
- [Web interface](/guide/web-ui)

</div>

<div class="step">

## Tell it where it is

caelum sets the exposure from where the sun and the moon really are. Under
**Settings**, fill in the **location**: latitude, longitude, elevation and time
zone. Until this is right, the camera exposes for somebody else's sky.

![Settings, with the location section](/images/screenshots/settings.webp)

- [Web interface](/guide/web-ui)
- [Configuration files](/guide/config-files)
- [Concepts](/guide/concepts)

</div>

<div class="step">

## Check the picture

Point the camera at the sky and turn the lens until the **focus score** on the
Dashboard is as high as it gets. Leave the exposure alone — caelum adjusts it
and the gain by itself, within limits for each part of the day. **Live stream**
shows frames as they come. The camera then captures around the clock: a frame
every minute by day and every 30 seconds at night.

- [Exposure control](/guide/exposure)
- [Lens & sky overlay](/guide/lens-calibration)
- [Storage & retention](/guide/storage)
- [Capture programs](/capture-programs)

</div>

<div class="step">

## Share the sky <span class="optional">optional</span>

To keep the images for good and show them to others, let the camera upload to a
storage server. Uploaded nights can be browsed, played as a time-lapse and
downloaded in Caelum Viewer, which can also read a camera directly on your
local network.

- [Upload & archive](/guide/upload)
- [Caelum Viewer](/viewer)
- [Where your data goes](/manual#where-your-data-goes)

</div>

</div>

## Reference

<div class="chips">

- [User manual](/manual)
- [Updates](/guide/updates)
- [Plugins](/guide/plugins)
- [Capture sets in DNG](/dng-capture-sets)

</div>

Stuck? Read the [User manual](/manual), or open an issue in the
[repository](https://github.com/roman-dvorak/caelum).
