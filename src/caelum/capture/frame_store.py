"""Holds only the single latest full-resolution frame — never a history of
full frames (that would blow RAM fast: ~35MB for a 4056x3040x3 array) — plus
a small ring buffer of stats (no images) for the exposure feedback loop.

Bridges the capture thread to asyncio consumers (the `/ws/stream` route) via
`loop.call_soon_threadsafe`, since `update()` is called from CaptureWorker's
thread, not the event loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass, replace

import numpy as np

from caelum.events import FRAME_METADATA_UPDATED, EventBus

from .metadata import FrameMetadata, OverlayElement
from .stats import FrameStats


@dataclass(frozen=True)
class ProcessedFrame:
    image: np.ndarray  # calibrated, full-resolution RGB
    thumbnail_jpeg: bytes
    stats: FrameStats
    metadata: FrameMetadata
    save_raw: bool  # from StoragePolicy.decide() — whether this frame should get a persisted raw copy


class FrameStore:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        event_bus: EventBus | None = None,
        stats_history: int = 30,
    ) -> None:
        self._lock = threading.Lock()
        self._latest: ProcessedFrame | None = None
        self._recent_stats: deque[FrameStats] = deque(maxlen=stats_history)
        self._loop = loop
        self._event_bus = event_bus
        self._queues: list[asyncio.Queue[ProcessedFrame]] = []

    def update(self, frame: ProcessedFrame) -> None:
        with self._lock:
            self._latest = frame
            self._recent_stats.append(frame.stats)
            queues = list(self._queues)
        if self._loop is not None:
            for queue in queues:
                self._loop.call_soon_threadsafe(self._offer, queue, frame)

    @staticmethod
    def _offer(queue: asyncio.Queue[ProcessedFrame], frame: ProcessedFrame) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(frame)

    def get_latest(self) -> ProcessedFrame | None:
        with self._lock:
            return self._latest

    def get_latest_stats(self) -> FrameStats | None:
        with self._lock:
            return self._recent_stats[-1] if self._recent_stats else None

    def update_metadata(self, new_elements: list[OverlayElement]) -> ProcessedFrame | None:
        """Append overlay elements contributed asynchronously by a
        derivative/plugin (e.g. a meteor detection) to whichever frame is
        *currently* latest, and re-broadcast it.

        There's no per-frame id to address a specific past frame by, so this
        assumes derivative processing finishes well within one capture
        interval — true in practice (a frame-diff is milliseconds; capture
        intervals are seconds to minutes) but not strictly guaranteed."""
        if not new_elements:
            return None
        with self._lock:
            if self._latest is None:
                return None
            updated_metadata = self._latest.metadata.model_copy(
                update={"overlay_elements": [*self._latest.metadata.overlay_elements, *new_elements]}
            )
            self._latest = replace(self._latest, metadata=updated_metadata)
            updated = self._latest
            queues = list(self._queues)
        if self._loop is not None:
            for queue in queues:
                self._loop.call_soon_threadsafe(self._offer, queue, updated)
        if self._event_bus is not None:
            self._event_bus.publish(FRAME_METADATA_UPDATED, updated)
        return updated

    def subscribe(self) -> asyncio.Queue[ProcessedFrame]:
        """Must be called from the event loop thread — creates a queue bound
        to the calling loop, used by e.g. the /ws/stream route."""
        queue: asyncio.Queue[ProcessedFrame] = asyncio.Queue(maxsize=2)
        with self._lock:
            self._queues.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[ProcessedFrame]) -> None:
        with self._lock:
            if queue in self._queues:
                self._queues.remove(queue)
