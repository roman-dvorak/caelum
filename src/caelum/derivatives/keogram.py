"""Keogram: the north-south meridian of every frame — a line through the
zenith, north at the top — laid out along a time axis, one image per
*observation day* (see `control/observation_day.py`).

Full resolution: the line is sampled at the sensor's own pixel pitch, as long
as the lens's image circle is wide (`camera.lens`: centre, radius, and
`azimuth_offset_deg` / `mirror`, so the line really runs north-south however
the camera is turned). The image is as wide as the whole day divided by
`seconds_per_pixel`, allocated up front: each frame paints the columns of its
own moment and the rest stays black until its time comes (or for good, where
the camera was not capturing). A band at the bottom carries the time axis —
hour ticks and local clock labels.

The image is rewritten in place every `live_flush_interval_s` while the day
runs — same file, so it is viewable (and uploaded) as it grows rather than
as a pile of partial copies — and written a last time when the next day
starts. The file is also the worker's memory: after a restart, an update or
a settings change, the first frame of a day picks the day's image back up
from disk and keeps painting into it.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from caelum.capture.frame_store import ProcessedFrame
from caelum.config.schema import OBSERVATION_DAY_START_PATTERN, AppConfig, LensConfig
from caelum.control.observation_day import ObservationDays
from caelum.derivatives.projection import project_altaz_to_pixel
from caelum.plugins.base import Plugin

from .base import Derivative
from .pool import derivative_path

logger = logging.getLogger(__name__)


_LIVE_FLUSH_INTERVAL_S = 300.0  # rewrite the day's keogram at most this often
#: Never wider than this: seconds_per_pixel is raised for the day instead.
_MAX_WIDTH_PX = 20000
#: Height of the time-axis band under the image.
AXIS_HEIGHT_PX = 64
_FONT = Path(__file__).with_name("fonts") / "DejaVuSansMono.ttf"


class KeogramSettings(BaseModel):
    """Validated against `AppConfig.plugins["keogram"].settings`."""

    #: Time covered by one pixel column; the image is as wide as the day is
    #: long divided by this (30 s: 2880 px for 24 h).
    seconds_per_pixel: float = Field(default=30.0, ge=1.0, le=600.0)
    #: A frame's column is repeated over the gap since the previous frame,
    #: but at most this long — a longer gap (capture off) stays black.
    max_fill_s: float = Field(default=180.0, ge=0.0, le=3600.0)
    #: Cap on the image height; unset keeps the lens's full resolution (the
    #: image circle's diameter in sensor pixels).
    max_height: int | None = Field(default=None, ge=16, le=16384)
    #: How often the day's keogram file is rewritten while the day runs.
    live_flush_interval_s: float = Field(default=_LIVE_FLUSH_INTERVAL_S, ge=0.0)
    #: When a keogram day starts: `"sunrise"` or local `"HH:MM"`. Unset
    #: follows the global `observation_day.start`, which is also what the
    #: recordings are grouped by.
    day_start: str | None = Field(default=None, pattern=OBSERVATION_DAY_START_PATTERN)


@lru_cache(maxsize=4)
def _meridian_map(width: int, height: int, lens_json: str, max_height: int | None) -> tuple[np.ndarray, np.ndarray]:
    """remap() coordinates of the north-south line through the zenith: one
    sample per sensor pixel along it, north first. The direction of north in
    the image comes from the lens projection, so `azimuth_offset_deg` and
    `mirror` are honoured."""
    lens = LensConfig.model_validate_json(lens_json)
    # Fractions address pixel edges, remap() pixel centres: hence the half pixel.
    cx, cy = lens.center_x * width - 0.5, lens.center_y * height - 0.5
    radius_px = max(1.0, lens.radius * min(width, height))
    north = project_altaz_to_pixel(45.0, 0.0, lens, width / height)
    if north is None:
        ux, uy = 0.0, -1.0
    else:
        dx, dy = north.x * width - 0.5 - cx, north.y * height - 0.5 - cy
        norm = math.hypot(dx, dy) or 1.0
        ux, uy = dx / norm, dy / norm
    n = max(2, round(2 * radius_px) + 1)
    if max_height is not None:
        n = min(n, max_height)
    d = np.linspace(radius_px, -radius_px, n, dtype=np.float32)
    return (cx + ux * d).reshape(n, 1).astype(np.float32), (cy + uy * d).reshape(n, 1).astype(np.float32)


def meridian_column(image: np.ndarray, lens: LensConfig, max_height: int | None = None) -> np.ndarray:
    """The north-south line through the zenith as an (n, 1, 3) column, north
    on top; samples that fall outside the frame are black."""
    h, w = image.shape[:2]
    map_x, map_y = _meridian_map(w, h, lens.model_dump_json(), max_height)
    return cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def time_axis(width: int, start: datetime, end: datetime, tz: Any) -> np.ndarray:
    """The band under the keogram: ticks and local `HH:MM` labels."""
    band = Image.new("RGB", (width, AXIS_HEIGHT_PX), (14, 16, 22))
    draw = ImageDraw.Draw(band)
    font = ImageFont.truetype(str(_FONT), 20)
    small = ImageFont.truetype(str(_FONT), 15)
    seconds = (end - start).total_seconds()
    px_per_s = width / seconds
    draw.text((6, 46), "N top · S bottom", font=small, fill=(120, 126, 140))
    # Ten-minute ticks only where they are at least 6 px apart.
    step_min = 10 if 600 * px_per_s >= 6 else 60
    local_start = start.astimezone(tz)
    tick = local_start.replace(minute=local_start.minute // step_min * step_min, second=0, microsecond=0)
    if tick < local_start:
        tick += timedelta(minutes=step_min)
    while tick < end:
        x = round((tick - start).total_seconds() * px_per_s)
        major = tick.minute == 0
        draw.line([(x, 0), (x, 18 if major else 8)], fill=(200, 205, 215) if major else (110, 116, 130), width=1)
        if major:
            draw.text((x + 4, 22), tick.strftime("%H:%M"), font=font, fill=(229, 229, 229))
            if tick.hour == 0:  # a new calendar day
                draw.text((x + 4, 46), tick.strftime("%d.%m."), font=small, fill=(232, 161, 58))
        tick += timedelta(minutes=step_min)
    return np.asarray(band)


class KeogramWorker(Plugin):
    """Shipped built-in, but loaded through `PluginLoader` like any
    third-party plugin — so `enabled`, `order` and `settings` apply to it."""

    id = "keogram"
    config_schema = KeogramSettings

    def __init__(self, settings: dict | None = None) -> None:
        super().__init__(settings or {})
        parsed = KeogramSettings.model_validate(self.settings)
        self._seconds_per_pixel = parsed.seconds_per_pixel
        self._max_fill_s = parsed.max_fill_s
        self._max_height = parsed.max_height
        self._live_flush_interval_s = parsed.live_flush_interval_s
        self._day_start = parsed.day_start
        self._days: ObservationDays | None = None
        #: The current day's data area (height, width, 3); None between days.
        self._canvas: np.ndarray | None = None
        self._window: tuple[datetime, datetime] | None = None
        self._last_frame_at: datetime | None = None
        self._current_day: str | None = None
        self._finished: Derivative | None = None
        self._dirty = False
        self._last_flush_monotonic: float = time.monotonic()

    def _observation_days(self) -> ObservationDays:
        if self._days is None:
            cfg = self.config_manager.current if self.config_manager is not None else AppConfig()
            self._days = ObservationDays.from_config(cfg, start=self._day_start)
        return self._days

    def _lens(self) -> LensConfig:
        return self.config_manager.current.camera.lens if self.config_manager is not None else LensConfig()

    def _width_for(self, window: tuple[datetime, datetime]) -> int:
        return max(1, min(_MAX_WIDTH_PX, math.ceil((window[1] - window[0]).total_seconds() / self._seconds_per_pixel)))

    def _render(self) -> np.ndarray:
        assert self._canvas is not None and self._window is not None
        axis = time_axis(self._canvas.shape[1], *self._window, self._observation_days().tz)
        return np.concatenate([self._canvas, axis], axis=0)

    def _derivative(self, day: str, image: np.ndarray, *, complete: bool) -> Derivative:
        start, end = self._observation_days().window(day)
        # Stamped with the day's start, not a frame's time: that is what keeps
        # the file name — and so the file — the same for the whole day.
        return Derivative(
            kind="keogram",
            created_at=start,
            image=image,
            metadata={
                "date": day, "start": start.isoformat(), "end": end.isoformat(), "complete": complete,
                "seconds_per_pixel": (end - start).total_seconds() / max(1, image.shape[1]),
                "axis_height_px": AXIS_HEIGHT_PX,
            },
        )

    def _resume_from_disk(self, day: str, height: int, width: int) -> np.ndarray | None:
        """The day's data area as already written, if it fits this setup —
        after a restart the night continues in the same image. A file from
        another resolution (settings or lens changed, or an older keogram
        without a time axis) is not resampled onto the new time axis; the day
        starts afresh."""
        if self.data_dir is None:
            return None
        path = derivative_path(self.data_dir, self._derivative(day, np.empty((0, 1)), complete=False), self.id)
        if not path.is_file():
            return None
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            logger.warning("Keogram %s is unreadable — starting the day afresh", path)
            return None
        if bgr.shape[0] != height + AXIS_HEIGHT_PX or bgr.shape[1] != width:
            logger.info("Keogram %s has another layout (%s) — starting the day afresh", path.name, bgr.shape[:2])
            return None
        logger.info("Keogram for %s resumed from %s (%d px wide)", day, path.name, width)
        return cv2.cvtColor(bgr[:height], cv2.COLOR_BGR2RGB)

    def _finish_day(self) -> None:
        if self._current_day is not None and self._canvas is not None and self._last_frame_at is not None:
            self._finished = self._derivative(self._current_day, self._render(), complete=True)

    def on_frame(self, frame: ProcessedFrame) -> None:
        captured_at = frame.metadata.captured_at
        day = self._observation_days().label_of(captured_at)
        column = meridian_column(frame.image, self._lens(), self._max_height)
        if day != self._current_day:
            self._finish_day()
            self._current_day = day
            self._window = self._observation_days().window(day)
            width = self._width_for(self._window)
            self._canvas = self._resume_from_disk(day, column.shape[0], width)
            if self._canvas is None:
                self._canvas = np.zeros((column.shape[0], width, 3), dtype=np.uint8)
            self._last_frame_at = None
            self._last_flush_monotonic = time.monotonic()
        assert self._canvas is not None and self._window is not None
        height, width = self._canvas.shape[:2]
        if column.shape[0] != height:  # the lens was recalibrated mid-day
            column = cv2.resize(column, (1, height), interpolation=cv2.INTER_AREA)
        start, end = self._window
        px_per_s = width / (end - start).total_seconds()
        x0 = int((captured_at - start).total_seconds() * px_per_s)
        gap_s = (captured_at - self._last_frame_at).total_seconds() if self._last_frame_at else 0.0
        span = max(1, math.ceil(min(max(gap_s, 0.0), self._max_fill_s) * px_per_s))
        x0 = max(0, min(width - 1, x0))
        self._canvas[:, x0 : min(width, x0 + span)] = column.reshape(height, 1, 3)
        self._last_frame_at = captured_at
        self._dirty = True

    def create_derivative(self, context: dict[str, Any]) -> Derivative | None:
        # The day that just ended takes priority; the new day's first flush
        # follows on a later frame.
        if self._finished is not None:
            finished, self._finished = self._finished, None
            return finished

        now = time.monotonic()
        due = now - self._last_flush_monotonic >= self._live_flush_interval_s
        if self._dirty and self._current_day is not None and self._canvas is not None and due:
            self._last_flush_monotonic = now
            self._dirty = False
            return self._derivative(self._current_day, self._render(), complete=False)
        return None
