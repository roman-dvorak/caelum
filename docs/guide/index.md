---
description: 'Introduction to caelum, an open-source capture stack for allsky cameras: what problem it solves and how its architecture fits together.'
---

# Introduction

caelum is a from-scratch software stack for allsky and astronomical cameras. It
is built for a machine you own and administer yourself — typically a Raspberry
Pi with a camera module bolted under an acrylic dome, left outside and expected
to keep working without anyone logging in.

The stack is one repository with two halves:

- **the Python backend** (`src/caelum`). A headless capture engine plus a FastAPI
  HTTP/WebSocket interface. This is where all of the behaviour described in
  this guide lives.
- **`web/`** — a pnpm workspace with two React apps and two shared
  packages. `local-web` is the interactive control UI served by the backend
  itself; `remote-web` is a read-only, multi-camera viewer that talks to
  nothing but static files on a web host.

## What problem it solves

An allsky camera has to expose correctly across roughly fourteen stops of sky
brightness over the course of a single evening, and it has to do so unattended.
Consumer auto-exposure is the wrong tool: it hunts, it flickers, it has no idea
that the sun is six degrees below the horizon and that the next frame should be
a hundred times longer than the last. It also has no opinion about which frames
are worth keeping at full resolution and which are not.

caelum replaces that with an explicit control loop. It computes where the sun
and the moon actually are for the configured observing site, classifies the sky
into one of five periods, looks up the exposure envelope configured for that
period, and drives exposure and gain inside it using measurements from the
previous frame. The same period classification decides whether a frame is
persisted as a full raw FITS file or as a thumbnail only, and how long to wait
before the next capture. Exposure policy and storage policy read the same
source of truth, so "is this a night frame" and "how long should we expose"
can never disagree.

## Architecture

<!--@include: ../_diagrams/frame-pipeline.md-->

**The capture thread is the sole owner of the camera.** One `CameraBackend`
instance is created at startup and handed to one `CaptureWorker`, which runs on
its own thread for the entire process lifetime. Nothing else in the system ever
touches the camera. Each cycle the worker refreshes the sky state (recomputed
at most every 30 seconds, since it moves slowly), asks the exposure controller
for a target, applies it, grabs a frame, subtracts a matching dark frame if the
library has one, computes statistics, encodes a JPEG thumbnail in memory,
builds the frame's metadata, and publishes. That is the whole hot path, and it
is deliberately narrow.

**Everything slow hangs off an event bus.** The capture worker publishes a
`frame_captured` event carrying the processed frame. The local storage writer,
the derivative pool and the upload worker are all subscribers. The bus itself
is a trivial in-process pub/sub that calls subscribers on the publisher's
stack, which means subscribers are required to hand work off to a pool
immediately rather than doing it inline — the storage writer submits to a small
thread pool, the derivative pool fans each worker out onto its own thread pool,
and the upload worker just sets a flag its own thread is waiting on. Slow disk,
a stalled network mount or an expensive plugin therefore cannot stretch the
capture interval.

**Derivative workers and plugins run off the hot path, with state in this
process.** Keogram accumulation and meteor detection are stateful — an
in-progress column buffer, the previous downscaled frame — so they are
dispatched to threads rather than processes; pickling a worker's whole state on
every frame would be absurd. A worker with a genuinely heavy but *stateless*
sub-computation can submit that one piece to a shared `ProcessPoolExecutor` to
use a second core, which is exactly what the meteor detector does with its
frame-difference and contour step.

**Configuration lives on disk and in Redis at the same time.** Disk is the
durable source of truth; Redis is a fast read path and a pub/sub channel so
that a config change made through the API is visible to anything else watching.
Every write validates against the Pydantic schema, writes the disk file
atomically, then updates Redis and publishes the new version number. The disk
write comes first so that a crash between the two steps never leaves Redis
holding a config that nothing durably committed to. High-frequency edits apply
to the in-memory config immediately and the disk and Redis flush is debounced,
which matters when the durable store is an SD card. At startup, disk wins
unless Redis holds a strictly newer, schema-valid `config_version` — in which
case Redis wins and the disk file is rewritten to match. Either way both stores
agree by the time startup finishes. If Redis is unreachable the process logs a
warning and runs off disk alone; it is a convenience, never a hard dependency.

**Local disk is a rotating cache, not the archive.** The remote storage server
holds the permanent copy. The retention sweeper on the camera deletes by age
and by free-space pressure, but when upload is enabled it will only ever
consider files that a full reconciliation pass has confirmed are present
remotely. A local disk that is genuinely full while upload lags far behind will
not free space until upload catches up. That is a deliberate trade — data
safety over guaranteed headroom — not an oversight.

Where to go next: [Getting started](/getting-started) to run it, the
[User manual](/manual) for the whole system from an operator's point of view,
[Concepts](/guide/concepts) for the domain model, or straight to
[Exposure](/guide/exposure) for the control loop in detail.
