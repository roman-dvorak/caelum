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

    from .jobs import ProcessingJob, ProcessingSetJob

    parent_pid = os.getppid()
    data_path = Path(data_dir)
    dark_library = DarkLibrary(darks_dir=Path(darks_dir))
    slots = _SlotCache()
    ctx = _ChildContext(result_q, data_path, dark_library, slots)
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

            if isinstance(job, ProcessingSetJob):
                _process_set(job, ctx)
            else:
                _process_set(ProcessingSetJob(jobs=(job,)), ctx)
    finally:
        slots.close()
        logger.info("Processing worker stopped")


class _ChildContext:
    def __init__(self, result_q: Any, data_dir: Path, dark_library: Any, slots: _SlotCache) -> None:
        self.result_q = result_q
        self.data_dir = data_dir
        self.dark_library = dark_library
        self.slots = slots


def _process_set(set_job: Any, ctx: _ChildContext) -> None:
    """Process one frame, or all members of a capture set: per member the
    thumbnail and sidecar (and the live frame for the one that is
    published), then the raw — one DNG per frame, or one multi-frame DNG
    for a set. Every job's slot is released with its own JobDone."""
    from . import pipeline
    from .jobs import FrameResult, JobDone

    jobs = set_job.jobs
    timers = {job.job_id: pipeline.Timer() for job in jobs}
    views: dict[int, tuple[Any, Any]] = {}
    done: dict[int, JobDone] = {}
    members = []
    try:
        for job in jobs:
            info, timer = job.info, timers[job.job_id]
            try:
                segment = ctx.slots.get(job.slot_name, job.generation)
                rgb = np.ndarray(job.rgb_shape, dtype=np.uint8, buffer=segment.buf)
                raw = None
                if job.raw_shape is not None:
                    raw = np.ndarray(job.raw_shape, dtype=np.uint8, buffer=segment.buf, offset=job.raw_offset)
                views[job.job_id] = (rgb, raw)

                calibrated, stats, live_jpeg, webp = pipeline.analyze(rgb, info, ctx.dark_library, timer)
                if calibrated is not rgb:
                    rgb[...] = calibrated  # the main process copies the calibrated frame out of the slot
                del calibrated
                metadata = pipeline.build_metadata(info, stats)
                thumb_path = pipeline.persist_thumbnail(ctx.data_dir, metadata, webp, info)
                timer.lap("write_thumbnail")
                if not info.is_hidden_member:  # only a set's representative is published
                    ctx.result_q.put(("frame", FrameResult(
                        job_id=job.job_id, stats=stats, live_jpeg=live_jpeg,
                        metadata_json=metadata.model_dump_json(), thumbnail_path=str(thumb_path),
                    )))
                members.append((job, info, metadata, stats, raw))
            except Exception as exc:  # noqa: BLE001 - one bad frame must not kill the worker
                logger.error("Processing frame captured at %s failed:\n%s", info.captured_at, traceback.format_exc())
                done[job.job_id] = JobDone(job_id=job.job_id, error=repr(exc), timings_ms=timer.timings_ms)

        raw_paths: dict[int, str] = {}
        with_raw = [m for m in members if m[1].save_raw and m[4] is not None and m[1].raw_config is not None]
        try:
            if len(jobs) == 1 and with_raw:
                job, info, metadata, stats, raw = with_raw[0]
                raw_paths[job.job_id] = str(pipeline.persist_raw(ctx.data_dir, info, metadata, stats, raw))
                timers[job.job_id].lap("write_raw")
            elif len(jobs) > 1:
                # Whatever members made it, as long as the primary did.
                primary = next((m for m in with_raw if not m[1].is_hidden_member), None)
                if primary is not None:
                    path = pipeline.persist_raw_set(ctx.data_dir, [(i, md, st, r) for _, i, md, st, r in with_raw])
                    raw_paths[primary[0].job_id] = str(path)
                    timers[primary[0].job_id].lap("write_raw_set")
        except Exception:  # noqa: BLE001
            logger.error("Writing the raw DNG failed:\n%s", traceback.format_exc())

        for job in jobs:
            if job.job_id not in done:
                done[job.job_id] = JobDone(job_id=job.job_id, raw_path=raw_paths.get(job.job_id),
                                           timings_ms=timers[job.job_id].timings_ms)
    finally:
        # Views into the segments must be gone before they can ever be closed.
        members.clear()
        views.clear()
        for job in jobs:
            ctx.result_q.put(("done", done.get(job.job_id) or JobDone(job_id=job.job_id, error="not processed")))
