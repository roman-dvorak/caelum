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
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

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
    #: The stored WebP thumbnail (None without a data dir) — where
    #: `DerivativePool` puts the rendered overlay next to, or into.
    thumbnail_path: Path | None = None
    #: The rendered overlay layer (transparent PNG) for the live view, once
    #: every plugin has contributed — see `FrameStore.set_overlay`.
    overlay_png: bytes | None = None
    #: Toggleable overlay layers by name (see `FrameMetadata.overlay_layers`).
    overlay_layer_pngs: dict[str, bytes] = field(default_factory=dict)


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

    def set_overlay(
        self,
        captured_at: datetime,
        elements: list[OverlayElement],
        overlay: str | None,
        overlay_png: bytes | None,
        layer_pngs: dict[str, bytes] | None = None,
    ) -> ProcessedFrame | None:
        """Attach a frame's final overlay — the complete element list, after
        every plugin contributed, and its rendered layer — and re-broadcast
        it. Done once per frame by `DerivativePool`. A frame that is no
        longer the latest (a newer capture arrived meanwhile) is left alone:
        the live view has moved on and the newer frame gets its own."""
        with self._lock:
            if self._latest is None or self._latest.metadata.captured_at != captured_at:
                return None
            updated_metadata = self._latest.metadata.model_copy(
                update={"overlay_elements": elements, "overlay": overlay, "overlay_layers": list(layer_pngs or {})}
            )
            self._latest = replace(
                self._latest, metadata=updated_metadata, overlay_png=overlay_png, overlay_layer_pngs=layer_pngs or {}
            )
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
