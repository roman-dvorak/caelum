---
description: 'From a camera to the first night of allsky images: install caelum, log in, set the observing site, check the picture and publish it.'
sidebar: false
---

# Getting started

From a camera on a pole to the first night of images, in six steps. Each step
links to the details when you need them; the [User manual](/manual) explains
how everything fits together.

## 1. Get a camera

caelum runs on a Raspberry Pi with a camera module, under a dome, outdoors.
The simplest way is an [AMASC01](/cameras/amasc01) — a finished, weatherproof
camera with a heated dome and a single PoE+ cable. You can also
[build your own](/cameras/diy).

## 2. Install caelum

Installation is one command on the camera's Raspberry Pi. It sets everything
up and starts caelum, which from then on runs on its own and comes back after
every power cut.

**→ [Installation](/guide/installation)**

Choose the https option there; the web interface is then at
`https://<camera>/`.

## 3. Log in

Open the camera's address in a browser. The first time, log in as `admin`
with the password the installer created — [Installation](/guide/installation#first-login)
says where to find it — and set your own password under **Accounts**.

You will land on the **Dashboard**: the newest frame, the current sky period
and the exposure caelum has chosen.

![The caelum dashboard](/images/screenshots/dashboard.webp)

## 4. Tell it where it is

caelum sets the exposure from where the sun and the moon really are, so it
has to know where the camera stands. Under **Settings**, fill in the
**location**: latitude, longitude, elevation and time zone.

Until this is right, the camera exposes for somebody else's sky.

![Settings, with the location section](/images/screenshots/settings.webp)

## 5. Check the picture

- **Focus.** Point the camera at the sky and turn the lens until the
  **focus score** on the Dashboard is as high as it gets.
- **Exposure.** Leave it alone — caelum adjusts exposure and gain by itself,
  within limits for each part of the day. On the first evening, watch the sky
  period change from *day* through the twilights to *night* and the exposure
  grow with it.
- **Live view.** **Live stream** shows frames as they come; *stream mode*
  captures faster while you watch.

The camera now captures around the clock: a frame every minute by day and
every 30 seconds at night, with the full raw data kept for the dark hours.

## 6. Share the sky (optional)

To keep the images for good and show them to others, let the camera upload to
a storage server. The [User manual](/manual#where-your-data-goes) explains how
that works, [Upload & archive](/guide/upload) how to set it up.

Uploaded nights can be browsed, played as a time-lapse and downloaded in
**[Caelum Viewer](/viewer)** — which can also read a camera directly on your
local network.

## What next

- [User manual](/manual) — how caelum works and how to operate it day to day.
- [Web interface](/guide/web-ui) — every page of the camera's interface.
- [Updates](/guide/updates) — new releases install from the web interface.
