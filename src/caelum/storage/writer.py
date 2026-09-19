"""Local persistence, off the capture thread: always writes a thumbnail +
its metadata sidecar, and conditionally a raw FITS file (per
`ProcessedFrame.save_raw`, set by StoragePolicy). Subscribes to
FRAME_CAPTURED directly, same off-thread pattern as DerivativePool.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from caelum.capture.frame_store import ProcessedFrame
from caelum.events import FRAME_CAPTURED, EventBus

from . import paths, raw_writer

logger = logging.getLogger(__name__)


class StorageWriter:
    def __init__(self, event_bus: EventBus, data_dir: Path, max_workers: int = 2) -> None:
        self._data_dir = data_dir
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="storage-writer")
        event_bus.subscribe(FRAME_CAPTURED, self._on_frame_captured)

    def _on_frame_captured(self, frame: ProcessedFrame) -> None:
        self._pool.submit(self._write, frame)

    def _write(self, frame: ProcessedFrame) -> None:
        try:
            when = frame.metadata.captured_at
            sidecar_json = frame.metadata.model_dump_json(indent=2)

            thumb_path = paths.thumbnail_path(self._data_dir, when)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_path.write_bytes(frame.thumbnail_jpeg)
            paths.sidecar_path(thumb_path).write_text(sidecar_json)

            if frame.save_raw:
                raw_path = paths.raw_path(self._data_dir, when)
                raw_writer.write(raw_path, frame)
                paths.sidecar_path(raw_path).write_text(sidecar_json)
        except Exception:
            logger.exception("Failed persisting frame captured at %s", frame.metadata.captured_at)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)
