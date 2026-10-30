"""Frame-difference streak detector — real but intentionally simple for
this MVP (not a full astrometric pipeline): threshold the difference
between consecutive downscaled frames and look for an elongated bright
blob. The actual diff+contour computation is a stateless module-level
function so it can run in the shared `ProcessPoolExecutor` (see pool.py) —
the worker instance itself only holds the small bit of state (the previous
frame, the pending detection) in the main process.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime
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
    min_length: float = 8.0,
    noise_sigmas: float = 5.0,
    max_changed_fraction: float = 0.02,
) -> BoundingBox | None:
    """Module-level + only numpy/OpenCV arguments so this is picklable and
    can run in a ProcessPoolExecutor worker.

    Looks for something that *appeared* between the two frames and is long
    and thin. What keeps it from firing on everything else:

    * the difference is signed (`curr - prev`, positive only): a trail that
      was in the previous frame and is gone now is not a second detection;
    * `prev` is shifted to `curr`'s median brightness, so an auto-exposure
      step or a passing cloud's glow does not light up the whole frame;
    * both frames are lightly blurred first (hot pixels, star scintillation);
    * the threshold is at least `noise_sigmas` times the noise of the
      difference itself, so a noisy sensor raises its own bar;
    * when more than `max_changed_fraction` of the frame changed it is a
      global event (cloud, lightning, headlights) and nothing is reported;
    * elongation is measured on the rotated minimum-area rectangle, not the
      axis-aligned box — a diagonal streak has a nearly square bounding box.
    """
    prev = cv2.GaussianBlur(prev_gray, (0, 0), 1.0).astype(np.float32)
    curr = cv2.GaussianBlur(curr_gray, (0, 0), 1.0).astype(np.float32)
    prev += float(np.median(curr) - np.median(prev))
    diff = curr - prev

    sigma = 1.4826 * float(np.median(np.abs(diff - np.median(diff))))
    mask = (diff > max(threshold, noise_sigmas * sigma)).astype(np.uint8)
    # Measured after eroding, so a long thin trail (which is what we are here
    # for) does not count as a "global" change, but a cloud or a lit-up area does.
    if cv2.erode(mask, np.ones((5, 5), np.uint8)).mean() > max_changed_fraction:
        return None
    # Bridges the gaps of a trail that fades in and out along its length.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best: BoundingBox | None = None
    best_length = 0.0
    for contour in contours:
        if cv2.contourArea(contour) < min_area and len(contour) < min_length:
            continue  # a 1 px wide line has no area, but it does have length
        (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
        length, width = max(rw, rh), max(min(rw, rh), 1.0)
        if length >= min_length and length / width >= min_elongation and length > best_length:
            best_length = length
            best = cv2.boundingRect(contour)
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
    #: Minimum streak length in downscaled pixels (shorter ones are stars
    #: twinkling or insects, not meteors).
    min_length: float = Field(default=8.0, ge=1.0)
    #: The difference threshold is raised to this many times the noise of the
    #: frame difference — a noisy sensor automatically gets a higher bar.
    noise_sigmas: float = Field(default=5.0, ge=0.0)
    #: A frame where more than this fraction of the pixels brightened is a
    #: cloud, lightning or a light being switched on — never a meteor.
    max_changed_fraction: float = Field(default=0.02, gt=0.0, le=1.0)


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
        self._prev_time: datetime | None = None
        # Frames are dispatched on a thread pool, so `on_frame` of the next
        # frame can run before the previous frame's overlay/derivative hooks
        # have read their result: detections are kept per frame, not in one
        # "last detection" slot that a neighbour could overwrite.
        self._lock = threading.Lock()
        self._detections: OrderedDict[datetime, dict[str, float]] = OrderedDict()

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
            self._settings.min_length,
            self._settings.noise_sigmas,
            self._settings.max_changed_fraction,
        )
        # Offloaded to a second CPU core when a pool is available; falls back
        # to running inline so the worker is usable standalone (unit tests,
        # or a caller that never registers it with a DerivativePool).
        if self.process_pool is not None:
            return self.process_pool.submit(detect_streak, *args).result()
        return detect_streak(*args)

    def on_frame(self, frame: ProcessedFrame) -> None:
        captured_at = frame.metadata.captured_at
        gray = self._downscale_gray(frame.image)
        with self._lock:
            prev, prev_time = self._prev_gray, self._prev_time
            if prev_time is not None and captured_at <= prev_time:
                return  # a late, out-of-order frame must not become the reference
            self._prev_gray, self._prev_time = gray, captured_at
        if prev is None or prev.shape != gray.shape:
            return
        bbox = self._detect(prev, gray)
        if bbox is not None:
            x, y, w, h = bbox
            gh, gw = gray.shape[:2]
            with self._lock:
                self._detections[captured_at] = {"x": x / gw, "y": y / gh, "w": w / gw, "h": h / gh}
                while len(self._detections) > 16:
                    self._detections.popitem(last=False)

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        with self._lock:
            detection = self._detections.get(frame.metadata.captured_at)
        if detection is None:
            return []
        return [
            OverlayElement(
                type="detection_box",
                source=self.id,
                payload={**detection, "label": "possible meteor"},
            )
        ]

    def create_derivative(self, context: dict[str, Any]) -> Derivative | None:
        frame: ProcessedFrame | None = context.get("frame")
        if frame is None:
            return None
        with self._lock:
            detection = self._detections.get(frame.metadata.captured_at)  # kept for the overlay
        if detection is None:
            return None
        return Derivative(
            kind="meteor_crop",
            created_at=frame.metadata.captured_at,
            image=frame.image,
            metadata={"bbox": detection},
        )
