"""Fans FRAME_CAPTURED out to registered derivative workers/plugins off the
capture thread.

Worker instances (and their accumulated state — an in-progress keogram
buffer, a meteor detector's previous frame) live in *this* process and run
on this pool's `ThreadPoolExecutor` threads: dispatching a stateful `on_frame`
call to a `ProcessPoolExecutor` isn't practical (it would mean pickling the
whole worker's state on every call), so threads are what take work off the
capture thread here. A worker with a genuinely heavy, stateless
sub-computation (see meteor_detection.py's `detect_streak`) can still submit
that specific piece to `process_pool` to use a second/third CPU core —
`DerivativePool` hands every worker a reference to the same process pool.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import date
from pathlib import Path

import cv2

from caelum.capture.frame_store import FrameStore, ProcessedFrame
from caelum.events import FRAME_CAPTURED, EventBus

from .base import Derivative, DerivativeWorker

logger = logging.getLogger(__name__)


def _derivative_path(data_dir: Path, derivative: Derivative, worker_id: str) -> Path:
    when = derivative.created_at
    day: date = when.date()
    ext = "png" if derivative.kind.startswith("keogram") else "jpg"
    return data_dir / "derivatives" / str(day) / f"{when.strftime('%H%M%S')}_{worker_id}_{derivative.kind}.{ext}"


def write_derivative(data_dir: Path, derivative: Derivative, worker_id: str) -> Path | None:
    if derivative.image is None:
        return derivative.path
    path = _derivative_path(data_dir, derivative, worker_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(derivative.image, cv2.COLOR_RGB2BGR) if derivative.image.ndim == 3 else derivative.image
    cv2.imwrite(str(path), bgr)
    return path


class DerivativePool:
    def __init__(
        self,
        event_bus: EventBus,
        frame_store: FrameStore,
        data_dir: Path,
        max_thread_workers: int = 4,
        max_process_workers: int = 2,
    ) -> None:
        self._event_bus = event_bus
        self._frame_store = frame_store
        self._data_dir = data_dir
        self._thread_pool = ThreadPoolExecutor(max_workers=max_thread_workers, thread_name_prefix="derivative")
        self.process_pool = ProcessPoolExecutor(max_workers=max_process_workers)
        self._workers: list[DerivativeWorker] = []
        event_bus.subscribe(FRAME_CAPTURED, self._on_frame_captured)

    def register(self, worker: DerivativeWorker) -> None:
        self._workers.append(worker)

    def register_all(self, workers: Iterable[DerivativeWorker]) -> None:
        for worker in workers:
            self.register(worker)

    def _on_frame_captured(self, frame: ProcessedFrame) -> None:
        for worker in self._workers:
            self._thread_pool.submit(self._run_worker, worker, frame)

    def _run_worker(self, worker: DerivativeWorker, frame: ProcessedFrame) -> None:
        try:
            worker.on_frame(frame)

            elements = worker.provide_overlay_elements(frame)
            if elements:
                self._frame_store.update_metadata(elements)

            derivative = worker.create_derivative({"frame": frame})
            if derivative is not None:
                path = write_derivative(self._data_dir, derivative, worker.id)
                logger.info("Derivative %s (%s) written to %s", worker.id, derivative.kind, path)
        except Exception:
            logger.exception("Derivative worker %r failed processing a frame", worker.id)

    def shutdown(self) -> None:
        self._thread_pool.shutdown(wait=True, cancel_futures=True)
        self.process_pool.shutdown(wait=True, cancel_futures=True)
