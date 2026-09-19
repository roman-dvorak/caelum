"""Daily keogram (one resized center-column strip per frame, stacked
side-by-side) plus a progressively-updated "live" keogram during the night
so it's viewable before the night ends.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, Field

from caelum.capture.frame_store import ProcessedFrame
from caelum.plugins.base import Plugin

from .base import Derivative

_LIVE_FLUSH_INTERVAL_S = 300.0  # write a partial "live" keogram at most this often


class KeogramSettings(BaseModel):
    """Validated against `AppConfig.plugins["keogram"].settings`."""

    #: Pixels each frame contributes to the finished strip. Wider makes a
    #: short night readable; narrower fits a long one on screen.
    column_width: int = Field(default=2, ge=1, le=32)
    #: Height the extracted centre column is resized to — the keogram's
    #: vertical resolution, independent of the sensor's.
    strip_height: int = Field(default=240, ge=8, le=2048)
    #: How often a partial keogram is written during the night, so it is
    #: viewable before the night ends.
    live_flush_interval_s: float = Field(default=_LIVE_FLUSH_INTERVAL_S, ge=0.0)


class KeogramWorker(Plugin):
    """Shipped built-in, but loaded through `PluginLoader` like any
    third-party plugin — so `enabled`, `order` and `settings` apply to it."""

    id = "keogram"
    config_schema = KeogramSettings

    def __init__(self, settings: dict | None = None) -> None:
        super().__init__(settings or {})
        parsed = KeogramSettings.model_validate(self.settings)
        self._column_width = parsed.column_width
        self._strip_height = parsed.strip_height
        self._live_flush_interval_s = parsed.live_flush_interval_s
        self._buffer: list[np.ndarray] = []
        self._current_date: date | None = None
        self._rollover_pending = False
        self._last_live_flush_monotonic: float = time.monotonic()

    def _extract_column(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        cx = w // 2
        column = image[:, cx : cx + 1, :]
        return cv2.resize(column, (self._column_width, self._strip_height), interpolation=cv2.INTER_AREA)

    def on_frame(self, frame: ProcessedFrame) -> None:
        today = frame.metadata.captured_at.date()
        if self._current_date is not None and today != self._current_date:
            self._rollover_pending = True
            return  # this frame's column belongs to the new day; create_derivative() will pick it up
        self._current_date = self._current_date or today
        self._buffer.append(self._extract_column(frame.image))

    def create_derivative(self, context: dict[str, Any]) -> Derivative | None:
        frame: ProcessedFrame | None = context.get("frame")
        if frame is None:
            return None

        if self._rollover_pending:
            finished = None
            if self._buffer:
                image = np.concatenate(self._buffer, axis=1)
                finished = Derivative(
                    kind="keogram",
                    created_at=frame.metadata.captured_at,
                    image=image,
                    metadata={"date": str(self._current_date), "frame_count": len(self._buffer)},
                )
            self._buffer = [self._extract_column(frame.image)]
            self._current_date = frame.metadata.captured_at.date()
            self._rollover_pending = False
            self._last_live_flush_monotonic = time.monotonic()
            return finished

        now = time.monotonic()
        if self._buffer and (now - self._last_live_flush_monotonic) >= self._live_flush_interval_s:
            self._last_live_flush_monotonic = now
            image = np.concatenate(self._buffer, axis=1)
            return Derivative(
                kind="keogram_live",
                created_at=frame.metadata.captured_at,
                image=image,
                metadata={"date": str(self._current_date), "frame_count": len(self._buffer)},
            )
        return None
