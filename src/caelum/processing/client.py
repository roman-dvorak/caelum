"""`FrameSink` that processes frames in a separate OS process.

Main-process side of the split described in `processing/__init__.py`:

- **Slots.** A small ring of shared-memory segments, each big enough for
  one frame's RGB plus raw Bayer buffer — `processing.slots` of them plus
  one for the latest frame. The capture thread `reserve()`s a slot before
  each capture and the camera writes straight into it; `submit()` then only
  enqueues a small `ProcessingJob` (a frame that didn't get a slot is
  copied into one here). With no free slot the frame is dropped and
  counted — capture never waits for processing. Free slots are taken
  oldest-freed first. Segments are allocated on the first frame and
  reallocated (new generation) if a later frame doesn't fit, e.g. after a
  resolution change.
- **Latest frame.** When a published frame's job is done its slot (now
  calibrated RGB plus the raw data) becomes the latest frame, read in place
  through `latest()`; the previous one is freed once nobody reads it.
- **Result pump.** A thread reading the worker's queue: on `FrameResult`
  it copies the calibrated frame out of the slot, builds the
  `ProcessedFrame` and publishes it (FrameStore + `FRAME_CAPTURED`); on
  `JobDone` it frees the slot (or keeps it as the latest frame); log records are re-emitted locally.
- **Supervision.** If the worker dies it is restarted (with backoff) on
  fresh queues and every in-flight slot is reclaimed; a job stuck longer
  than `job_timeout_s` gets the worker killed and restarted the same way.
"""

from __future__ import annotations

import dataclasses
import itertools
import logging
import multiprocessing
import os
import queue
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any

import numpy as np

from caelum.cameras.base import RawFrame
from caelum.capture.frame_store import FrameStore, ProcessedFrame
from caelum.capture.metadata import FrameMetadata
from caelum.events import FRAME_CAPTURED, EventBus

from .child import child_main
from .jobs import (
    FrameInfo,
    FrameResult,
    FrameSlot,
    FrameSubmission,
    JobDone,
    ProcessingJob,
    ProcessingSetJob,
    slot_layout,
)

logger = logging.getLogger(__name__)

_SHM_PREFIX = "caelum-"
_SHM_DIR = Path("/dev/shm")
_NO_PIXELS = np.zeros((0, 0, 3), dtype=np.uint8)
_DROP_WARN_INTERVAL_S = 60.0
_RESTART_BACKOFF_MAX_S = 30.0
_RESTART_BACKOFF_RESET_S = 300.0
_STOP_JOIN_S = 10.0


@dataclass
class _InFlight:
    slot: int
    generation: int
    submitted_at: float
    rgb_shape: tuple[int, ...]
    raw_shape: tuple[int, ...] | None
    raw_offset: int
    save_raw: bool
    #: Published (not a set's hidden member): becomes the latest frame.
    primary: bool
    #: The capture without its pixels — what `latest()` describes it with.
    frame: RawFrame
    frame_delivered: bool = False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def remove_stale_segments(shm_dir: Path = _SHM_DIR) -> int:
    """Unlink segments left behind by a caelum process that no longer
    exists (the resource tracker normally does this, but not if it died
    too). Names are `caelum-<pid>-<generation>-<slot>`."""
    removed = 0
    if not shm_dir.is_dir():
        return 0
    for path in shm_dir.glob(f"{_SHM_PREFIX}*"):
        parts = path.name[len(_SHM_PREFIX):].split("-")
        try:
            pid = int(parts[0])
        except (ValueError, IndexError):
            continue
        if pid != os.getpid() and not _pid_alive(pid):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


class ProcessingClient:
    def __init__(
        self,
        frame_store: FrameStore,
        event_bus: EventBus,
        data_dir: Path,
        darks_dir: Path | None = None,
        slots: int = 3,
        job_timeout_s: float = 120.0,
    ) -> None:
        self._frame_store = frame_store
        self._event_bus = event_bus
        self._data_dir = data_dir
        self._darks_dir = darks_dir if darks_dir is not None else data_dir / "darks"
        self._slot_count = slots
        self._job_timeout_s = job_timeout_s

        self._ctx = multiprocessing.get_context("spawn")
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._job_ids = itertools.count(1)

        self._segments: list[shared_memory.SharedMemory] = []
        self._segment_size = 0
        self._generation = 0
        self._free: deque[int] = deque()
        self._in_flight: dict[int, _InFlight] = {}
        #: Slots handed to the capture thread by `reserve()`.
        self._leased: set[int] = set()
        self._latest: _InFlight | None = None
        #: Readers inside `latest()`, per slot.
        self._readers: dict[int, int] = {}

        self._proc: Any = None
        self._job_q: Any = None
        self._result_q: Any = None
        self._ready = False
        self._pump: threading.Thread | None = None

        self._submitted = 0
        self._processed = 0
        self._dropped = 0
        self._failed = 0
        self._restarts = 0
        self._last_latency_ms: float | None = None
        self._last_timings: dict[str, float] = {}
        self._last_drop_warning = 0.0
        self._recent_restarts: list[float] = []

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        removed = remove_stale_segments()
        if removed:
            logger.info("Removed %d stale shared-memory segment(s)", removed)
        self._spawn()
        self._pump = threading.Thread(target=self._pump_loop, name="processing-pump", daemon=True)
        self._pump.start()

    def stop(self) -> None:
        self._stop_event.set()
        # The pump may be mid-restart; let it finish first so the worker
        # stopped below is the one that is actually running.
        if self._pump is not None:
            self._pump.join(5.0)
        with self._lock:
            self._ready = False
            proc, job_q = self._proc, self._job_q
        if proc is not None:
            try:
                job_q.put(None)
            except Exception:  # noqa: BLE001
                pass
            # Keep reading while waiting: the worker can't exit until its
            # queue feeder has flushed everything into the pipe, and a pipe
            # nobody reads fills up after one live JPEG.
            deadline = time.monotonic() + _STOP_JOIN_S
            while proc.is_alive() and time.monotonic() < deadline:
                self._drain(timeout=0.2)
                proc.join(0.05)
            if proc.is_alive():
                logger.warning("Processing worker did not stop in %.0fs — killing it", _STOP_JOIN_S)
                proc.kill()
                proc.join(2.0)
        # Anything the worker reported before exiting (last frames, logs).
        self._drain()
        with self._lock:
            self._release_segments()
            self._in_flight.clear()
        if proc is not None:
            self._close_queues(self._job_q, self._result_q)

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            proc = self._proc
            return {
                "mode": "process",
                "worker_pid": proc.pid if proc is not None else None,
                "worker_alive": bool(proc is not None and proc.is_alive()),
                "slots": self._slot_count,
                "slot_mb": round(self._segment_size / 1e6, 1),
                "in_flight": len(self._in_flight),
                "reserved": len(self._leased),
                "latest_frame": self._latest is not None,
                "submitted": self._submitted,
                "processed": self._processed,
                "dropped": self._dropped,
                "failed": self._failed,
                "restarts": self._restarts,
                "last_latency_ms": self._last_latency_ms,
                "last_timings_ms": dict(self._last_timings),
            }

    # ---- capture-thread side --------------------------------------------

    def reserve(self, rgb_shape: tuple[int, ...], raw_shape: tuple[int, ...] | None) -> FrameSlot | None:
        raw_offset, needed = slot_layout(rgb_shape, raw_shape)
        with self._lock:
            if not self._ready:
                return None
            if needed > self._segment_size:
                if self._in_flight or self._leased or self._readers:
                    return None  # reallocated once everything is back
                self._allocate_segments(needed)
            if not self._free:
                return None
            index = self._free.popleft()
            self._leased.add(index)
            segment, generation = self._segments[index], self._generation
        rgb = np.ndarray(rgb_shape, dtype=np.uint8, buffer=segment.buf)
        raw = np.ndarray(raw_shape, dtype=np.uint8, buffer=segment.buf, offset=raw_offset) if raw_shape else None
        return FrameSlot(index=index, generation=generation, rgb=rgb, raw=raw)

    def release(self, slot: FrameSlot) -> None:
        with self._lock:
            if self._owns_locked(slot):
                self._leased.discard(slot.index)
                self._free.append(slot.index)

    def _owns_locked(self, slot: FrameSlot | None) -> bool:
        return slot is not None and slot.generation == self._generation and slot.index in self._leased

    def submit(self, submission: FrameSubmission) -> bool:
        return self.submit_set([submission])

    def submit_set(self, submissions: list[FrameSubmission]) -> bool:
        """All frames get a slot, or none does: a capture set is processed
        whole or dropped whole (with more members than slots, always).
        Reserved slots come with their frames; the rest are copied in."""
        prepared = []
        for submission in submissions:
            rgb = np.ascontiguousarray(submission.raw.image, dtype=np.uint8)
            raw = submission.raw.raw_bayer
            if raw is not None:
                raw = np.ascontiguousarray(raw, dtype=np.uint8)
            raw_offset, size = slot_layout(rgb.shape, raw.shape if raw is not None else None)
            prepared.append((submission, rgb, raw, raw_offset, size))
        what = "frame" if len(prepared) == 1 else f"capture set of {len(prepared)}"

        with self._lock:
            # From here on reserved slots are this call's: in flight, or
            # freed with a drop. One from before a reallocation is gone —
            # its frame is copied like any other.
            own = [p[0].slot if self._owns_locked(p[0].slot) else None for p in prepared]
            for slot in own:
                if slot is not None:
                    self._leased.discard(slot.index)

            def drop(reason: str) -> bool:
                self._free.extend(slot.index for slot in own if slot is not None)
                return self._drop_locked(reason, what)

            to_copy = [p for p, slot in zip(prepared, own, strict=True) if slot is None]
            if not self._ready:
                return drop("processing worker is not running")
            if len(prepared) > self._slot_count:
                return drop(f"more frames than the {self._slot_count} slots")
            needed = max((p[4] for p in to_copy), default=0)
            if needed > self._segment_size:
                if self._in_flight or self._leased or self._readers or len(to_copy) < len(prepared):
                    return drop("reallocating frame slots for a larger frame")
                self._allocate_segments(needed)
            if len(self._free) < len(to_copy):
                return drop("all frame slots busy")
            generation = self._generation
            job_q = self._job_q
            reserved = []
            for (submission, rgb, raw, raw_offset, _), slot in zip(prepared, own, strict=True):
                index = slot.index if slot is not None else self._free.popleft()
                job_id = next(self._job_ids)
                info = FrameInfo.from_submission(submission)
                self._in_flight[job_id] = _InFlight(
                    slot=index,
                    generation=generation,
                    submitted_at=time.monotonic(),
                    rgb_shape=tuple(rgb.shape),
                    raw_shape=tuple(raw.shape) if raw is not None else None,
                    raw_offset=raw_offset,
                    save_raw=submission.save_raw,
                    primary=not info.is_hidden_member,
                    frame=dataclasses.replace(submission.raw, image=_NO_PIXELS, raw_bayer=None),
                )
                reserved.append((job_id, self._segments[index], info))
            self._submitted += len(prepared)

        # The capture thread is the only submitter, and the slots are ours
        # until JobDone (or a restart reclaims them) — no lock needed to fill them.
        jobs = []
        for (submission, rgb, raw, raw_offset, _), (job_id, segment, info) in zip(prepared, reserved, strict=True):
            slot = submission.slot
            if slot is None or submission.raw.image is not slot.rgb:
                np.ndarray(rgb.shape, dtype=np.uint8, buffer=segment.buf)[...] = rgb
            if raw is not None and (slot is None or submission.raw.raw_bayer is not slot.raw):
                np.ndarray(raw.shape, dtype=np.uint8, buffer=segment.buf, offset=raw_offset)[...] = raw
            jobs.append(
                ProcessingJob(
                    job_id=job_id,
                    generation=generation,
                    slot_name=segment.name,
                    rgb_shape=tuple(rgb.shape),
                    raw_shape=tuple(raw.shape) if raw is not None else None,
                    raw_offset=raw_offset,
                    info=info,
                )
            )
        job_q.put(jobs[0] if len(jobs) == 1 else ProcessingSetJob(jobs=tuple(jobs)))
        return True

    # ---- latest frame ----------------------------------------------------

    @contextmanager
    def latest(self) -> Iterator[RawFrame | None]:
        with self._lock:
            entry = self._latest
            if entry is not None:
                self._readers[entry.slot] = self._readers.get(entry.slot, 0) + 1
                segment, generation = self._segments[entry.slot], self._generation
        if entry is None:
            yield None
            return
        try:
            rgb = np.ndarray(entry.rgb_shape, dtype=np.uint8, buffer=segment.buf)
            raw = None
            if entry.raw_shape is not None:
                raw = np.ndarray(entry.raw_shape, dtype=np.uint8, buffer=segment.buf, offset=entry.raw_offset)
            yield dataclasses.replace(entry.frame, image=rgb, raw_bayer=raw)
        finally:
            with self._lock:
                left = self._readers.pop(entry.slot, 1) - 1
                if left:
                    self._readers[entry.slot] = left
                elif self._latest is not entry and generation == self._generation:
                    self._free.append(entry.slot)  # replaced while being read

    def _set_latest_locked(self, entry: _InFlight | None) -> None:
        previous, self._latest = self._latest, entry
        if previous is not None and not self._readers.get(previous.slot):
            self._free.append(previous.slot)

    def _drop_locked(self, reason: str, what: str = "frame") -> bool:
        self._dropped += 1
        now = time.monotonic()
        if now - self._last_drop_warning >= _DROP_WARN_INTERVAL_S:
            self._last_drop_warning = now
            logger.warning("Dropping %s from processing: %s (%d dropped so far)", what, reason, self._dropped)
        return False

    # ---- shared memory ---------------------------------------------------

    def _allocate_segments(self, size: int) -> None:
        self._release_segments()
        self._generation += 1
        self._segment_size = size
        # One more than the processing slots: the latest frame keeps one.
        for index in range(self._slot_count + 1):
            name = f"{_SHM_PREFIX}{os.getpid()}-{self._generation}-{index}"
            self._segments.append(shared_memory.SharedMemory(name=name, create=True, size=size))
        self._free = deque(range(len(self._segments)))
        logger.info(
            "Allocated %d frame slot(s) of %.1f MB in shared memory", len(self._segments), size / 1e6
        )

    def _release_segments(self) -> None:
        for segment in self._segments:
            try:
                segment.close()
            except BufferError:
                logger.warning("Frame slot %s still has views — not unmapping", segment.name)
            try:
                segment.unlink()
            except FileNotFoundError:
                pass
        self._segments = []
        self._segment_size = 0
        self._free = deque()
        self._leased = set()
        self._latest = None

    # ---- worker process --------------------------------------------------

    def _spawn(self) -> None:
        job_q = self._ctx.Queue()
        result_q = self._ctx.Queue()
        proc = self._ctx.Process(
            target=child_main,
            args=(job_q, result_q, str(self._data_dir), str(self._darks_dir), logging.getLogger().getEffectiveLevel()),
            name="caelum-processing",
            daemon=True,
        )
        proc.start()
        with self._lock:
            self._proc, self._job_q, self._result_q = proc, job_q, result_q
            self._ready = True
        logger.info("Processing worker spawned (pid %d)", proc.pid)

    @staticmethod
    def _close_queues(*queues: Any) -> None:
        for q in queues:
            if q is None:
                continue
            try:
                q.close()
                q.cancel_join_thread()
            except Exception:  # noqa: BLE001
                pass

    def _restart(self, reason: str) -> None:
        with self._lock:
            self._ready = False
            proc, job_q, result_q = self._proc, self._job_q, self._result_q
            reclaimed = len(self._in_flight)
            for entry in self._in_flight.values():
                if entry.generation == self._generation:
                    self._free.append(entry.slot)
                if not entry.frame_delivered:
                    self._failed += 1
            self._in_flight.clear()
            # Its slot is intact, but nothing vouches for it any more.
            self._set_latest_locked(None)
            self._restarts += 1
        logger.error("Processing worker %s — restarting (%d in-flight frame(s) abandoned)", reason, reclaimed)
        if proc is not None and proc.is_alive():
            proc.kill()
            proc.join(2.0)
        # Fresh queues: a worker killed mid-put may have left the old ones'
        # internal locks held forever.
        self._close_queues(job_q, result_q)

        now = time.monotonic()
        self._recent_restarts = [t for t in self._recent_restarts if now - t < _RESTART_BACKOFF_RESET_S]
        delay = min(2.0 ** len(self._recent_restarts), _RESTART_BACKOFF_MAX_S) if self._recent_restarts else 0.0
        self._recent_restarts.append(now)
        if delay and self._stop_event.wait(delay):
            return
        if not self._stop_event.is_set():
            self._spawn()

    def _supervise(self) -> None:
        with self._lock:
            proc = self._proc
            oldest = min((e.submitted_at for e in self._in_flight.values()), default=None)
        if proc is None or self._stop_event.is_set():
            return
        if not proc.is_alive():
            self._restart(f"exited unexpectedly (exit code {proc.exitcode})")
        elif oldest is not None and time.monotonic() - oldest > self._job_timeout_s:
            self._restart(f"has been stuck on a frame for over {self._job_timeout_s:.0f}s")

    # ---- result pump -----------------------------------------------------

    def _pump_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                result_q = self._result_q
            try:
                message = result_q.get(timeout=0.5)
            except queue.Empty:
                message = None
            except (EOFError, OSError, ValueError):
                message = None  # queue closed under us by a restart
            if message is not None:
                self._handle(message)
            try:
                self._supervise()
            except Exception:  # noqa: BLE001 - the pump must keep running
                logger.exception("Processing supervisor failed")

    def _drain(self, timeout: float = 0.2) -> None:
        with self._lock:
            result_q = self._result_q
        if result_q is None:
            return
        while True:
            try:
                message = result_q.get(timeout=timeout)
            except (queue.Empty, EOFError, OSError, ValueError):
                return
            self._handle(message)

    def _handle(self, message: tuple[str, Any]) -> None:
        kind, payload = message
        try:
            if kind == "log":
                record: logging.LogRecord = payload
                logging.getLogger(record.name).handle(record)
            elif kind == "frame":
                self._on_frame(payload)
            elif kind == "done":
                self._on_done(payload)
        except Exception:  # noqa: BLE001
            logger.exception("Handling a %r message from the processing worker failed", kind)

    def _on_frame(self, result: FrameResult) -> None:
        with self._lock:
            entry = self._in_flight.get(result.job_id)
            if entry is None or entry.generation != self._generation:
                return  # from before a restart/reallocation — its slot is gone
            segment = self._segments[entry.slot]
            image = np.ndarray(entry.rgb_shape, dtype=np.uint8, buffer=segment.buf).copy()
            entry.frame_delivered = True
            save_raw = entry.save_raw
            self._last_latency_ms = round((time.monotonic() - entry.submitted_at) * 1000.0, 1)

        processed = ProcessedFrame(
            image=image,
            thumbnail_jpeg=result.live_jpeg,
            stats=result.stats,
            metadata=FrameMetadata.model_validate_json(result.metadata_json),
            save_raw=save_raw,
            thumbnail_path=Path(result.thumbnail_path) if result.thumbnail_path else None,
        )
        self._frame_store.update(processed)
        self._event_bus.publish(FRAME_CAPTURED, processed)

    def _on_done(self, done: JobDone) -> None:
        with self._lock:
            entry = self._in_flight.pop(done.job_id, None)
            if entry is None:
                return
            if entry.generation == self._generation:
                if done.error is None and entry.primary and entry.frame_delivered:
                    self._set_latest_locked(entry)
                else:
                    self._free.append(entry.slot)
            if done.error is None:
                self._processed += 1
            elif not entry.frame_delivered:
                self._failed += 1
            self._last_timings = dict(done.timings_ms)
