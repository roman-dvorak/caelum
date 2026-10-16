"""Keogram: one resized centre-column strip per frame, stacked side by side,
one image per *observation day* (see `control/observation_day.py`).

The image is rewritten in place every `live_flush_interval_s` while the day
runs — same file, so it is viewable (and uploaded) as it grows rather than
as a pile of partial copies — and written a last time when the next day
starts. With a morning day start the whole night lands in one image.

The file is also the worker's memory: after a restart, an update or a
settings change, the first frame of a day picks the day's image back up
from disk and keeps appending to it.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, Field

from caelum.capture.frame_store import ProcessedFrame
from caelum.config.schema import OBSERVATION_DAY_START_PATTERN, AppConfig
from caelum.control.observation_day import ObservationDays
from caelum.plugins.base import Plugin

from .base import Derivative
from .pool import derivative_path

logger = logging.getLogger(__name__)

_LIVE_FLUSH_INTERVAL_S = 300.0  # rewrite the day's keogram at most this often


class KeogramSettings(BaseModel):
    """Validated against `AppConfig.plugins["keogram"].settings`."""

    #: Pixels each frame contributes to the finished strip. Wider makes a
    #: short night readable; narrower fits a long one on screen.
    column_width: int = Field(default=2, ge=1, le=32)
    #: Height the extracted centre column is resized to — the keogram's
    #: vertical resolution, independent of the sensor's.
    strip_height: int = Field(default=240, ge=8, le=2048)
    #: How often the day's keogram file is rewritten while the day runs.
    live_flush_interval_s: float = Field(default=_LIVE_FLUSH_INTERVAL_S, ge=0.0)
    #: When a keogram day starts: `"sunrise"` or local `"HH:MM"`. Unset
    #: follows the global `observation_day.start`, which is also what the
    #: recordings are grouped by.
    day_start: str | None = Field(default=None, pattern=OBSERVATION_DAY_START_PATTERN)


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
        self._day_start = parsed.day_start
        self._days: ObservationDays | None = None
        self._buffer: list[np.ndarray] = []
        self._current_day: str | None = None
        self._finished: Derivative | None = None
        self._dirty = False
        self._last_flush_monotonic: float = time.monotonic()

    def _observation_days(self) -> ObservationDays:
        if self._days is None:
            cfg = self.config_manager.current if self.config_manager is not None else AppConfig()
            self._days = ObservationDays.from_config(cfg, start=self._day_start)
        return self._days

    def _extract_column(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        cx = w // 2
        column = image[:, cx : cx + 1, :]
        return cv2.resize(column, (self._column_width, self._strip_height), interpolation=cv2.INTER_AREA)

    def _derivative(self, day: str, image: np.ndarray, *, complete: bool) -> Derivative:
        start, end = self._observation_days().window(day)
        # Stamped with the day's start, not a frame's time: that is what keeps
        # the file name — and so the file — the same for the whole day.
        return Derivative(
            kind="keogram",
            created_at=start,
            image=image,
            metadata={"date": day, "start": start.isoformat(), "end": end.isoformat(), "complete": complete},
        )

    def _resume_from_disk(self, day: str) -> list[np.ndarray]:
        """The day's keogram as already written, if any — after a restart the
        night continues in the same image instead of starting over."""
        if self.data_dir is None:
            return []
        path = derivative_path(self.data_dir, self._derivative(day, np.empty(0), complete=False), self.id)
        if not path.is_file():
            return []
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            logger.warning("Keogram %s is unreadable — starting the day afresh", path)
            return []
        image = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if image.shape[0] != self._strip_height:
            width = max(1, round(image.shape[1] * self._strip_height / image.shape[0]))
            image = cv2.resize(image, (width, self._strip_height), interpolation=cv2.INTER_AREA)
        logger.info("Keogram for %s resumed from %s (%d px wide)", day, path.name, image.shape[1])
        return [image]

    def on_frame(self, frame: ProcessedFrame) -> None:
        day = self._observation_days().label_of(frame.metadata.captured_at)
        if day != self._current_day:
            if self._current_day is not None and self._buffer:
                self._finished = self._derivative(
                    self._current_day, np.concatenate(self._buffer, axis=1), complete=True
                )
            self._current_day = day
            self._buffer = self._resume_from_disk(day)
            self._last_flush_monotonic = time.monotonic()
        self._buffer.append(self._extract_column(frame.image))
        self._dirty = True

    def create_derivative(self, context: dict[str, Any]) -> Derivative | None:
        # The day that just ended takes priority; the new day's first flush
        # follows on a later frame.
        if self._finished is not None:
            finished, self._finished = self._finished, None
            return finished

        now = time.monotonic()
        due = now - self._last_flush_monotonic >= self._live_flush_interval_s
        if self._dirty and self._current_day is not None and due:
            self._last_flush_monotonic = now
            self._dirty = False
            return self._derivative(self._current_day, np.concatenate(self._buffer, axis=1), complete=False)
        return None
