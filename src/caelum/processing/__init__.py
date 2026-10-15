"""Per-frame processing, decoupled from capture.

The capture thread only grabs a frame, measures its brightness for the
exposure loop and hands it off (`FrameSink.submit`). Everything heavier —
dark calibration, full statistics, thumbnail/live-stream encoding, writing
the WebP thumbnail and the raw DNG — happens behind the sink:

- `ProcessingClient` (production): a separate OS process fed through
  shared memory, so processing runs in parallel with the next exposure and
  never competes with the API/event loop for the GIL;
- `InlineFrameSink`: the same pipeline synchronously on the caller's thread
  (tests, debugging).

Both end the same way: a `ProcessedFrame` lands in the `FrameStore` and is
published as `FRAME_CAPTURED` in the main process, so derivatives, plugins,
the live stream and the uploader don't care which one is in use.
"""
