---
layout: home

hero:
  name: caelum
  text: A capture stack for allsky cameras
  tagline: Headless capture engine, closed-loop exposure control driven by real sun and moon geometry, RAM-first image pipeline, and a self-healing upload path to a permanent remote archive.
  actions:
    - theme: brand
      text: Get started
      link: /getting-started
    - theme: alt
      text: Documentation
      link: /guide/
    - theme: alt
      text: Cameras
      link: /cameras/

features:
  - title: Exposure follows the sky, not a clock
    details: Sun altitude from an offline astropy ephemeris classifies the sky into five periods. Each period has its own exposure and gain envelope, and a closed feedback loop drives the camera inside it. The camera's own auto-exposure is always disabled.
  - title: Three camera backends, one pipeline
    details: picamera2 for Raspberry Pi camera modules, OpenCV/V4L2 for any UVC webcam, and a synthetic mock backend so the whole stack runs on a laptop with no hardware attached. Switching backends changes nothing downstream.
  - title: RAM-first capture path
    details: The capture thread owns the camera and does nothing but capture, calibrate, measure, thumbnail, publish. Disk writes, derivative processing and uploads all subscribe to an event bus and run off-thread, so capture cadence never depends on how busy the rest of the system is.
  - title: Keograms and meteor detection
    details: Two built-in derivative workers ship with the engine — a daily keogram assembled column by column with a live partial flush during the night, and a frame-difference streak detector that annotates frames and emits crops.
  - title: Self-healing upload
    details: rsync pushes today's directories often and reconciles the whole tree periodically. rsync does its own diffing, so there is no retry ledger to corrupt — a reboot mid-transfer or a dead uplink resolves itself on the next reconciliation pass.
  - title: Plugins without forking
    details: A plugin is a class with four optional hooks and a config block carrying enabled, order and an opaque settings dict. Built-in derivative workers use exactly the same interface, so the extension point is proven by the code that ships with it.
---

<div class="maintainer">
  <a href="https://astrometers.eu"><img src="/astrometers.svg" alt="AstroMeters" width="72" height="72"></a>
  <div>
    <p class="maintainer-label">Maintained by</p>
    <p class="maintainer-name"><a href="https://astrometers.eu">AstroMeters</a></p>
    <p>caelum is developed by AstroMeters, who also build the
    <a href="/cameras/amasc01.html">AMASC01</a> allsky camera it is tested on.
    For hardware, custom development or support, see
    <a href="https://astrometers.eu">astrometers.eu</a> or write to
    <a href="mailto:info@astrometers.eu">info@astrometers.eu</a>.</p>
  </div>
</div>
