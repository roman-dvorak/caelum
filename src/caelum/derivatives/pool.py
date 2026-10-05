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
import multiprocessing
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import cv2

from caelum.capture import thumbnail as thumbnail_module
from caelum.capture.frame_store import FrameStore, ProcessedFrame
from caelum.config.manager import ConfigManager
from caelum.events import FRAME_CAPTURED, EventBus
from caelum.storage import paths

from .base import Derivative, DerivativeWorker

logger = logging.getLogger(__name__)

#: Small enough that a busy night's gallery (a meteor detector can produce
#: hundreds of crops) stays fast to browse on Raspberry Pi-class hardware.
_THUMBNAIL_MAX_DIM = 320


def _derivative_dir(data_dir: Path, derivative: Derivative) -> Path:
    # One subdirectory per kind — before this, every worker's output for a
    # given day landed flat in the same directory (keograms, keogram_live
    # partials and meteor crops all interleaved by timestamp), which made
    # "show me just the keograms" a manual filtering exercise instead of a
    # directory listing.
    return paths.date_dir(data_dir, "derivatives", derivative.created_at) / derivative.kind


def _derivative_path(data_dir: Path, derivative: Derivative, worker_id: str) -> Path:
    ext = "png" if derivative.kind.startswith("keogram") else "jpg"
    stem = paths.timestamp_stem(derivative.created_at)
    return _derivative_dir(data_dir, derivative) / f"{stem}_{worker_id}_{derivative.kind}.{ext}"


def thumbnail_path_for(full_path: Path) -> Path:
    """The companion thumbnail path for a derivative's full-resolution file —
    a fixed `_thumb` suffix before the extension, deterministic in both
    directions (same convention as `storage/paths.sidecar_path`), so a
    consumer never needs to look the pairing up anywhere."""
    return full_path.with_name(f"{full_path.stem}_thumb.jpg")


def write_derivative(data_dir: Path, derivative: Derivative, worker_id: str) -> Path | None:
    if derivative.image is None:
        return derivative.path
    path = _derivative_path(data_dir, derivative, worker_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(derivative.image, cv2.COLOR_RGB2BGR) if derivative.image.ndim == 3 else derivative.image
    cv2.imwrite(str(path), bgr)

    thumb_bytes = thumbnail_module.encode(derivative.image, max_dim=_THUMBNAIL_MAX_DIM)
    thumbnail_path_for(path).write_bytes(thumb_bytes)

    return path


class DerivativePool:
    def __init__(
        self,
        event_bus: EventBus,
        frame_store: FrameStore,
        data_dir: Path,
        max_thread_workers: int = 4,
        max_process_workers: int = 2,
        config_manager: ConfigManager | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._frame_store = frame_store
        self._data_dir = data_dir
        self._config_manager = config_manager
        self._thread_pool = ThreadPoolExecutor(max_workers=max_thread_workers, thread_name_prefix="derivative")
        # "spawn", not the default fork: forked workers would inherit the
        # main process's threads (libcamera, asyncio, redis) mid-state and,
        # forked while uvicorn is serving, its SIGTERM handler — which only
        # sets a flag, so they ignored `systemctl stop` until the 90 s
        # SIGKILL. Submitted callables must be importable functions either way.
        self.process_pool = ProcessPoolExecutor(
            max_workers=max_process_workers, mp_context=multiprocessing.get_context("spawn")
        )
        self._workers: list[DerivativeWorker] = []
        event_bus.subscribe(FRAME_CAPTURED, self._on_frame_captured)

    def register(self, worker: DerivativeWorker) -> None:
        # Injected rather than passed at construction, so a worker can be
        # built from nothing but its config block — which is what lets
        # PluginLoader instantiate built-ins and third-party plugins the
        # same way. See DerivativeWorker.process_pool/config_manager.
        worker.process_pool = self.process_pool
        worker.config_manager = self._config_manager
        worker.data_dir = self._data_dir
        self._workers.append(worker)

    def register_all(self, workers: Iterable[DerivativeWorker]) -> None:
        for worker in workers:
            self.register(worker)

    def replace_all(self, workers: Iterable[DerivativeWorker]) -> None:
        """Swap the whole worker set — how a config change takes effect.

        Replacing wholesale rather than diffing means a worker whose settings
        changed is rebuilt from scratch, which is the only way to be sure its
        accumulated state (a keogram buffer sized by `strip_height`, a
        detector's previous frame at the old `max_dim`) matches its new
        configuration. The cost is that an in-progress keogram restarts.
        """
        self._workers = []
        self.register_all(workers)

    def _on_frame_captured(self, frame: ProcessedFrame) -> None:
        self._thread_pool.submit(self._dispatch, frame)

    def _dispatch(self, frame: ProcessedFrame) -> None:
        """Runs the `modify_image` chain first — sequential, because each
        worker's output feeds the next worker's input, unlike everything
        else here — then fans the (possibly modified) frame out to every
        worker's `on_frame`/`provide_overlay_elements`/`create_derivative`
        in parallel, since those don't depend on each other's output.

        Both stages run on this pool's threads, off the capture thread that
        published the event; the chain itself runs synchronously within
        this one task rather than one task per worker; because a chain is
        exactly the thing that can't be parallelized, and threads are cheap
        enough that giving it a whole one is not a cost worth avoiding.
        """
        frame = self._run_modify_chain(frame)
        for worker in self._workers:
            self._thread_pool.submit(self._run_worker, worker, frame)

    def _run_modify_chain(self, frame: ProcessedFrame) -> ProcessedFrame:
        """Chains `modify_image` across every registered worker in ascending
        `order` — `self._workers` is already in that order, since
        `PluginLoader.load()` sorts it and `replace_all()`/`register_all()`
        preserve whatever order they're handed.

        Offloading the actual heavy computation to `process_pool` is each
        worker's own responsibility, not this method's — see
        `DerivativeWorker.process_pool` and `meteor_detection.py`'s
        `_detect()` for the pattern. Pickling a stateful worker instance
        wholesale into a *different* process on every frame (which is what
        `process_pool.submit(worker.modify_image, ...)` would do here)
        defeats the purpose for exactly the reason a stateful `on_frame`
        can't be dispatched that way either — see the module docstring.

        Only `ProcessedFrame.image` — the full-resolution calibrated frame —
        passes through the chain. The thumbnail JPEG and any raw FITS write
        are already fixed by the time this runs (both happen on the capture
        thread, or off it in `StorageWriter`, independently and before any
        plugin sees the frame at all) — keeping capture cadence independent
        of plugin cost requires exactly this boundary, not working around
        it. What *does* see the result is everything downstream in this
        same dispatch: every worker's own `on_frame`/`create_derivative`,
        called next with the frame this method returns.
        """
        image = frame.image
        for worker in self._workers:
            try:
                image = worker.modify_image(image, frame)
            except Exception:
                logger.exception("modify_image failed for %r — passing the image through unchanged", worker.id)
        # The overwhelmingly common case: no worker overrides modify_image,
        # so `image` is still the exact object `frame.image` already was —
        # skip allocating a copy of the frame for nothing.
        if image is frame.image:
            return frame
        return replace(frame, image=image)

    def _run_worker(self, worker: DerivativeWorker, frame: ProcessedFrame) -> None:
        try:
            worker.on_frame(frame)

            elements = worker.provide_overlay_elements(frame)
            if elements:
                self._frame_store.update_metadata(elements)

            derivative = worker.create_derivative({"frame": frame, "data_dir": self._data_dir})
            if derivative is not None:
                path = write_derivative(self._data_dir, derivative, worker.id)
                logger.info("Derivative %s (%s) written to %s", worker.id, derivative.kind, path)
        except Exception:
            logger.exception("Derivative worker %r failed processing a frame", worker.id)

    def shutdown(self) -> None:
        self._thread_pool.shutdown(wait=True, cancel_futures=True)
        self.process_pool.shutdown(wait=True, cancel_futures=True)
