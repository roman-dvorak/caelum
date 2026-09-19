"""Frame-difference streak detector — real but intentionally simple for
this MVP (not a full astrometric pipeline): threshold the difference
between consecutive downscaled frames and look for an elongated bright
blob. The actual diff+contour computation is a stateless module-level
function so it can run in the shared `ProcessPoolExecutor` (see pool.py) —
the worker instance itself only holds the small bit of state (the previous
frame, the pending detection) in the main process.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, Field

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement
from caelum.plugins.base import Plugin

from .base import Derivative

BoundingBox = tuple[int, int, int, int]


def detect_streak(
    prev_gray: np.ndarray,
    curr_gray: np.ndarray,
    threshold: float,
    min_elongation: float = 3.0,
    min_area: float = 4.0,
) -> BoundingBox | None:
    """Module-level + only numpy/OpenCV arguments so this is picklable and
    can run in a ProcessPoolExecutor worker."""
    diff = cv2.absdiff(curr_gray, prev_gray)
    _, mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best: BoundingBox | None = None
    best_elongation = 0.0
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        elongation = max(w, h) / max(min(w, h), 1)
        area = cv2.contourArea(contour)
        if elongation >= min_elongation and area >= min_area and elongation > best_elongation:
            best_elongation = elongation
            best = (x, y, w, h)
    return best


class MeteorDetectionSettings(BaseModel):
    """Validated against `AppConfig.plugins["meteor_detection"].settings`."""

    #: Per-pixel brightness change that counts as motion. Lower catches
    #: fainter trails and more noise; raise it on a noisy sensor.
    diff_threshold: float = Field(default=40.0, ge=0.0, le=255.0)
    #: Frames are differenced at this size, not full resolution — a 12 MP
    #: diff every capture would not keep up on a Pi.
    max_dim: int = Field(default=480, ge=64, le=4096)
    #: How many times longer than wide a blob must be to count as a streak,
    #: which is what separates a meteor from a satellite glint or hot pixel.
    min_elongation: float = Field(default=3.0, ge=1.0)
    #: Minimum blob area in downscaled pixels — rejects single-pixel noise.
    min_area: float = Field(default=4.0, ge=0.0)


class MeteorDetectionWorker(Plugin):
    """Frame-difference streak detector, shipped built-in but loaded through
    the same `PluginLoader` path as any third-party plugin — so `enabled`,
    `order` and `settings` in the config work on it identically."""

    id = "meteor_detection"
    config_schema = MeteorDetectionSettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings or {})
        self._settings = MeteorDetectionSettings.model_validate(self.settings)
        self._prev_gray: np.ndarray | None = None
        self._last_detection: dict[str, float] | None = None

    def _downscale_gray(self, image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
        h, w = gray.shape[:2]
        scale = self._settings.max_dim / max(h, w)
        if scale < 1.0:
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(gray)

    def _detect(self, prev_gray: np.ndarray, gray: np.ndarray) -> BoundingBox | None:
        args = (
            prev_gray,
            gray,
            self._settings.diff_threshold,
            self._settings.min_elongation,
            self._settings.min_area,
        )
        # Offloaded to a second CPU core when a pool is available; falls back
        # to running inline so the worker is usable standalone (unit tests,
        # or a caller that never registers it with a DerivativePool).
        if self.process_pool is not None:
            return self.process_pool.submit(detect_streak, *args).result()
        return detect_streak(*args)

    def on_frame(self, frame: ProcessedFrame) -> None:
        gray = self._downscale_gray(frame.image)
        self._last_detection = None
        if self._prev_gray is not None and self._prev_gray.shape == gray.shape:
            bbox = self._detect(self._prev_gray, gray)
            if bbox is not None:
                x, y, w, h = bbox
                gh, gw = gray.shape[:2]
                self._last_detection = {"x": x / gw, "y": y / gh, "w": w / gw, "h": h / gh}
        self._prev_gray = gray

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        if self._last_detection is None:
            return []
        return [
            OverlayElement(
                type="detection_box",
                source=self.id,
                payload={**self._last_detection, "label": "possible meteor"},
            )
        ]

    def create_derivative(self, context: dict[str, Any]) -> Derivative | None:
        if self._last_detection is None:
            return None
        frame: ProcessedFrame | None = context.get("frame")
        if frame is None:
            return None
        detection = self._last_detection
        self._last_detection = None  # emit once per detection
        return Derivative(
            kind="meteor_crop",
            created_at=frame.metadata.captured_at,
            image=frame.image,
            metadata={"bbox": detection},
        )
