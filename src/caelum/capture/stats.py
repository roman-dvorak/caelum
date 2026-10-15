"""Frame statistics for the exposure feedback loop and a cheap focus proxy.

Computed on a downscaled copy so this stays cheap on RPi CPU regardless of
the sensor's native resolution.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

_STATS_MAX_DIM = 640


@dataclass(frozen=True)
class FrameStats:
    mean: float
    p95: float
    p99: float
    saturated_fraction: float
    focus_score: float
    #: Median of the exposure loop's central brightness circle (see
    #: `capture/brightness.py`) — what the controller actually regulates on.
    median: float = 0.0


def _downscale_grayscale(image: np.ndarray, max_dim: int = _STATS_MAX_DIM) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    h, w = gray.shape[:2]
    scale = max_dim / max(h, w)
    if scale < 1.0:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return gray


def extract(image: np.ndarray, saturation_value: float = 255.0) -> FrameStats:
    gray = _downscale_grayscale(image).astype(np.float32)
    mean = float(np.mean(gray))
    p95 = float(np.percentile(gray, 95))
    p99 = float(np.percentile(gray, 99))
    saturated_fraction = float(np.mean(gray >= saturation_value))
    # Laplacian variance: a standard cheap sharpness/focus proxy — high
    # variance means lots of crisp edges (stars), low variance means a blurry
    # or featureless (e.g. cloudy) frame.
    focus_score = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    return FrameStats(
        mean=mean,
        p95=p95,
        p99=p99,
        saturated_fraction=saturated_fraction,
        focus_score=focus_score,
    )
