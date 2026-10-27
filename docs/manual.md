---
sidebar: false
description: 'caelum user manual: how the system works, what happens through the day and night, where the data goes, and how to operate and look after the camera.'
---

# User manual

This manual describes how a caelum camera works and how to look after it. It
assumes caelum is installed and running — if not, start with
[Getting started](/getting-started). For the exact behaviour of each part,
follow the links into the [documentation](/guide/).

## What caelum does

caelum is the software of an allsky camera. It runs on the camera's Raspberry
Pi, unattended, day and night:

- it **takes a picture of the whole sky** every 30–60 seconds,
- **sets the exposure itself** from where the sun and the moon actually are,
- **keeps the full raw data** of the dark hours and a preview of every frame,
- **builds a keogram** of each day and **looks for meteors**,
- **uploads** everything to a permanent archive, and
- lets you **watch and control** the camera from a browser.

## How the system fits together

<!--@include: ./_diagrams/system-overview.md-->

*The parts of a caelum installation and how data moves between them.*

**The camera** does all the work. Its *capture engine* takes the pictures and
processes them; its *web interface* is how you see and control it. Nothing
outside the camera is needed for it to run — it keeps capturing with no
network at all.

**The storage server** is optional but recommended. The camera uploads its
frames there, and the server keeps them permanently, while the camera's own
disk only holds the last few days. It can be an S3 bucket or an ordinary web
server.

**[Caelum Viewer](/viewer)** is the website for looking at the results: it
reads the storage server and shows any camera, any day, as a timeline, a
time-lapse and a gallery, with downloads of the raw files. On your local
network it can also read a camera directly.

## What happens to every frame

<!--@include: ./_diagrams/frame-pipeline.md-->

*What happens to every frame inside the camera.*

1. **Sky state.** From the camera's location and the clock, caelum computes
   where the sun and the moon are and which part of the day it is. This needs
   no internet connection.
2. **Exposure.** Every part of the day has its own allowed range of exposure
   time and gain. Within it, caelum steers towards the right brightness using
   what it measured in the previous frame. The camera's own automatic
   exposure is never used.
3. **Capture** on a fixed time grid, so frames from different nights and
   cameras line up.
4. **Processing.** A dark frame is subtracted when one is available,
   brightness and sharpness are measured, a preview (WebP) is made and the
   frame gets its metadata: time, exposure, gain, sun and moon positions and
   more.
5. **Everything else at once.** The frame is handed to storage, the plugins
   (keogram, meteor detection, overlay), the uploader and the live view, all
   in parallel. A slow disk or network never delays the next picture.

What the camera captures in each slot is decided by a
[capture program](/capture-programs) — the built-in one takes a single frame;
others can take several, for example for HDR.

## A day and a night

caelum divides the day into five **sky periods** by how far the sun is below
the horizon. Each has its own exposure limits, capture interval and storage
rule:

| | Day | Civil twilight | Nautical | Astronomical | Night |
|---|---|---|---|---|---|
| **Sun altitude** | above −0.8° | −0.8° to −6° | −6° to −12° | −12° to −18° | below −18° |
| **Exposure** | 0.1–10 ms | 0.2–100 ms | 1 ms–2 s | 10 ms–8 s | 0.1–15 s |
| **Gain** | 1–2× | 1–4× | 1–8× | 1–12× | 1–16× |
| **Frame every** | 60 s | 60 s | 60 s | 30 s | 30 s |
| **Raw DNG** | — | — | — | **saved** | **saved** |

*One evening, left to right; the morning runs the same way back. These are the
defaults — every value is a setting.*

- **Daytime** frames are short and frequent enough to follow clouds; only the
  preview is kept.
- **Through the twilights** the exposure grows step by step.
- **In astronomical twilight and at night** frames come every 30 seconds and
  the full raw data (DNG) is kept as well.

All limits can be changed under **Settings** — see
[Exposure control](/guide/exposure) and [Concepts](/guide/concepts).

**Observation day.** Images are grouped into observation days that start at
sunrise (configurable), so one night is never split at midnight. Each
observation day gets one **keogram**: a single picture made of one column from
every frame, which shows the whole night — clouds, aurora, dawn — at a glance.

**Overlay.** Every frame gets an overlay: time, exposure and gain, camera
name and logo by default. You edit it under **Overlay**; the camera draws it
once, and the live view and Recordings show exactly that, with a switch to
hide it.

## Where your data goes

<!--@include: ./_diagrams/data-lifecycle.md-->

*Where frames go, and when the camera forgets them. Intervals are the defaults; the age and space limits are settings.*

The camera's disk is a **rotating cache**, not an archive. With upload turned
on:

- **today's** new files go to the storage server about once a minute,
- **everything** is compared and completed every 30 minutes, so files missed
  during a network outage are sent once it is back.

**Retention** keeps the disk from filling up, and adapts to the space there
is. Two settings under **Settings → retention** drive it:

- **maximum age** (2 days by default) — older files are deleted, but only
  once the server is confirmed to have them;
- **minimum free space** (1 GB by default) — when free space drops below it,
  the oldest files are deleted sooner, uploaded ones first. Only if that is
  not enough do files the server does not have yet go too, so the camera
  never stops capturing because of a full disk.

A larger card or SSD simply holds more, and a long network outage eats into
the free space before anything unarchived is lost. Without upload, the same
two limits apply to all files.

Details: [Upload & archive](/guide/upload), [Storage & retention](/guide/storage).

## The web interface

Open the camera's address in a browser and log in. There are two kinds of
account: **viewers** see the pictures, **administrators** can also change
everything. Pages under *Observe* are for everyone, pages under *Manage* for
administrators only.

| Page | What it is for |
|---|---|
| **Dashboard** | The newest frame, the sky period, exposure, gain, focus score and the exposure controller's numbers. The first place to look. |
| **Live stream** | Frames as they arrive. *Stream mode* captures faster while you watch; *manual exposure* fixes exposure and gain for testing. |
| **Recordings** | Captured frames by day, with their raw files, metadata and derivatives such as the keogram. |
| **Files** | Everything on the camera's disk, to preview and download. |
| **Settings** | The whole configuration: location, exposure limits, storage, upload, access rules. Changes apply as you make them. |
| **Capture programs** | Choose, check and test what the camera captures in each slot. |
| **Plugins** | Turn plugins on and off and set their options. |
| **Overlay** | Edit the overlay: text, masks, images. |
| **White balance** | Set colour balance on the newest frame's raw data, previewed live. |
| **Terminal** | A shell on the camera, in the browser. |
| **Logs** | Everything caelum has logged since it started, live. |
| **System** | Temperatures, disk, network — and **Software update**. |
| **Accounts** | Add viewers and administrators, change passwords. |

A walk through every page: [Web interface](/guide/web-ui).

## Everyday tasks

**Check the camera is fine.** On the **Dashboard**, the last capture time
should be at most a minute or two old, and the sky period should match the
sky outside. **System** shows the free disk space and the temperatures.

**Focus.** Turn the lens and watch the **focus score** on the Dashboard; the
highest value is the sharpest image. A bright star field at night is the best
target.

**Download raw data.** In **Recordings**, open a day and a frame and download
its DNG — or browse the archive in [Caelum Viewer](/viewer).

**Give someone access.** Under **Accounts**, add a *viewer* account: they see
the pictures but can change nothing. To let anyone see the preview without an
account, see [Access & security](/guide/security#preview-access).

**Change the overlay.** **Overlay** shows the real rendering while you edit;
changes apply once saved.

**Change several settings at once.** Write the values you want into a small
JSON file — only those, nothing else — and load it with **Settings →
Import…**. caelum lists every value the file would change, and applies them
only when you press **Apply**. The same file works on any number of cameras;
**Settings → Export** saves the whole configuration as a backup. See
[Configuration files](/guide/config-files).

```json
{ "location": { "lat": 49.1951, "lon": 16.6068 },
  "retention": { "max_age_days": 7 } }
```

**Update the software.** First **Settings → Export** to keep a copy of the
configuration. Then **System → Software update → Check for updates** shows
the new release and what changed; **Update to …** installs it. Capturing
pauses for a few seconds; your settings and data stay. If the new release
does not start properly, the camera returns to the previous one by itself.
Step by step, with every message explained: [Updates](/guide/updates).

## Looking after the camera

- **Keep the dome clean.** Dust, pollen, bird droppings and water spots show
  up in every frame. For AMASC01, follow the cleaning instructions in its
  [maintenance guide](https://astrometers.eu/docs/AMASC01/).
- **Watch for dew and frost.** A heated dome (as on AMASC01) keeps it clear;
  fogged frames on clear nights mean the heating is not keeping up.
- **Check the disk now and then** under **System**, especially if upload is
  off or the network is unreliable.
- **Keep the clock right.** The exposure follows the sun, so the time must be
  correct. With a network the Pi sets its clock itself; offline, it needs a
  real-time clock (AMASC01 has one).
- **Update** when a new release is out — **System → Software update**.

## When something is wrong

| What you see | What to check |
|---|---|
| The Dashboard says *Waiting for first frame* | At night the first exposure can take up to 15 s — wait a minute. If it stays, look at **Logs** for camera errors. |
| Frames are black by day or white at night | **Location** and **time zone** in Settings, and the camera clock — the sky period on the Dashboard must match the real sky. |
| Frames are blurred | Focus — see above — and dew on the dome. |
| Nothing new in Caelum Viewer | Upload settings, and **Logs**: every upload pass is logged, failures with the reason. |
| The disk is filling up | Upload is failing, so files wait for the server and are only removed at the free-space limit. Fix upload, or adjust the retention settings. |
| An update failed | Nothing to do: the camera keeps, or goes back to, the release that worked. The reason is in **System → Software update** and in **Logs**. |
| Forgotten admin password | [Resetting a forgotten admin password](/guide/security#resetting-a-forgotten-admin-password). |
