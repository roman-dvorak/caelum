"""Frame-difference streak detector — real but intentionally simple for
this MVP (not a full astrometric pipeline): threshold the difference
between consecutive downscaled frames and look for an elongated bright
blob. The actual diff+contour computation is a stateless module-level
function so it can run in the shared `ProcessPoolExecutor` (see pool.py) —
the worker instance itself only holds the small bit of state (the previous
frame, the pending detection) in the main process.
"""

from __future__ import annotations

from concurrent.futures import Executor
from typing import Any

import cv2
import numpy as np

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement

from .base import Derivative, DerivativeWorker

BoundingBox = tuple[int, int, int, int]


def detect_streak(prev_gray: np.ndarray, curr_gray: np.ndarray, threshold: float) -> BoundingBox | None:
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
        if elongation >= 3.0 and area >= 4 and elongation > best_elongation:
            best_elongation = elongation
            best = (x, y, w, h)
    return best


class MeteorDetectionWorker(DerivativeWorker):
    id = "meteor_detection"

    def __init__(self, process_pool: Executor, diff_threshold: float = 40.0, max_dim: int = 480) -> None:
        self._process_pool = process_pool
        self._diff_threshold = diff_threshold
        self._max_dim = max_dim
        self._prev_gray: np.ndarray | None = None
        self._last_detection: dict[str, float] | None = None

    def _downscale_gray(self, image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
        h, w = gray.shape[:2]
        scale = self._max_dim / max(h, w)
        if scale < 1.0:
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(gray)

    def on_frame(self, frame: ProcessedFrame) -> None:
        gray = self._downscale_gray(frame.image)
        self._last_detection = None
        if self._prev_gray is not None and self._prev_gray.shape == gray.shape:
            bbox = self._process_pool.submit(detect_streak, self._prev_gray, gray, self._diff_threshold).result()
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
