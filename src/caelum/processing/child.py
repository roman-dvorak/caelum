"""Entry point of the processing process (started with the "spawn"
context — a clean interpreter, nothing inherited from the main process's
threads, camera or event loop).

Loop: take a `ProcessingJob`, map its shared-memory slot, run the pipeline
on the pixels in place, report `FrameResult` as soon as the frame is
viewable, write the raw DNG, report `JobDone`. Log records travel back on
the same result queue and are re-emitted by the main process's loggers, so
they show up in the journal and the logs API like any other.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import queue
import signal
import traceback
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("caelum.processing.child")

# How often an idle worker checks whether its parent is still alive — if
# the main process was SIGKILLed, nobody would ever send the stop sentinel.
_PARENT_CHECK_S = 2.0


class _TaggedQueueHandler(logging.handlers.QueueHandler):
    def enqueue(self, record: logging.LogRecord) -> None:
        self.queue.put_nowait(("log", record))


def _setup_logging(result_q: Any, level: int) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(_TaggedQueueHandler(result_q))
    root.setLevel(level)


class _SlotCache:
    """Shared-memory segments this process has attached to, by name. Only
    the current generation is kept: once a job from a newer generation
    arrives (the main process reallocated after a resolution change), the
    older mappings are closed so the unlinked memory can actually be freed."""

    def __init__(self) -> None:
        self._generation = -1
        self._segments: dict[str, shared_memory.SharedMemory] = {}

    def get(self, name: str, generation: int) -> shared_memory.SharedMemory:
        if generation != self._generation:
            self.close()
            self._generation = generation
        segment = self._segments.get(name)
        if segment is None:
            # Not unregistered from the resource tracker on purpose: a
            # spawned child shares the parent's tracker, whose registry is a
            # set — unregistering here would drop the parent's own entry and
            # with it the cleanup-on-crash guarantee.
            segment = shared_memory.SharedMemory(name=name)
            self._segments[name] = segment
        return segment

    def close(self) -> None:
        for segment in self._segments.values():
            try:
                segment.close()
            except BufferError:
                logger.warning("Shared-memory segment %s still has views — leaving it mapped", segment.name)
        self._segments.clear()


def child_main(job_q: Any, result_q: Any, data_dir: str, darks_dir: str, log_level: int) -> None:
    # Ctrl+C in a terminal, or systemd stopping the service, signals the
    # whole process group / cgroup at once. The main process decides when
    # this worker stops (stop sentinel) — so a frame half-written to disk
    # isn't abandoned mid-way, and the supervisor doesn't see an "unexpected"
    # exit and respawn it during shutdown. systemd's final SIGKILL still
    # applies if the main process never gets that far.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    _setup_logging(result_q, log_level)

    from caelum.capture.calibration import DarkLibrary

    from . import pipeline
    from .jobs import FrameResult, JobDone, ProcessingJob

    parent_pid = os.getppid()
    data_path = Path(data_dir)
    dark_library = DarkLibrary(darks_dir=Path(darks_dir))
    slots = _SlotCache()
    logger.info("Processing worker started (pid %d)", os.getpid())

    try:
        while True:
            try:
                job: ProcessingJob | None = job_q.get(timeout=_PARENT_CHECK_S)
            except queue.Empty:
                if os.getppid() != parent_pid:
                    # Nobody will ever read what's still buffered for the
                    # result queue — don't let exit block on flushing it.
                    result_q.cancel_join_thread()
                    return
                continue
            if job is None:
                return

            info = job.info
            timer = pipeline.Timer()
            rgb = raw = calibrated = None
            try:
                segment = slots.get(job.slot_name, job.generation)
                rgb = np.ndarray(job.rgb_shape, dtype=np.uint8, buffer=segment.buf)
                if job.raw_shape is not None:
                    raw = np.ndarray(job.raw_shape, dtype=np.uint8, buffer=segment.buf, offset=job.raw_offset)

                calibrated, stats, live_jpeg, webp = pipeline.analyze(rgb, info, dark_library, timer)
                if calibrated is not rgb:
                    rgb[...] = calibrated  # the main process copies the calibrated frame out of the slot
                metadata = pipeline.build_metadata(info, stats)
                thumb_path = pipeline.persist_thumbnail(data_path, metadata, webp)
                timer.lap("write_thumbnail")
                result_q.put(
                    (
                        "frame",
                        FrameResult(
                            job_id=job.job_id,
                            stats=stats,
                            live_jpeg=live_jpeg,
                            metadata_json=metadata.model_dump_json(),
                            thumbnail_path=str(thumb_path),
                        ),
                    )
                )

                raw_path = None
                if info.save_raw and raw is not None and info.raw_config is not None:
                    raw_path = pipeline.persist_raw(data_path, info, metadata, stats, raw)
                    timer.lap("write_raw")
                result_q.put(
                    ("done", JobDone(job_id=job.job_id, raw_path=str(raw_path) if raw_path else None,
                                     timings_ms=timer.timings_ms))
                )
            except Exception as exc:  # noqa: BLE001 - one bad frame must not kill the worker
                logger.error("Processing frame captured at %s failed:\n%s", info.captured_at, traceback.format_exc())
                result_q.put(("done", JobDone(job_id=job.job_id, error=repr(exc), timings_ms=timer.timings_ms)))
            finally:
                # Views into the segment must be gone before it can ever be closed.
                del rgb, raw, calibrated
    finally:
        slots.close()
        logger.info("Processing worker stopped")
