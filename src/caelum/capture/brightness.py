"""The exposure loop's brightness measurement: median (and p99, for the
highlight guard) of a circle centred on the frame, `diameter_frac` of the
frame's shorter side across.

The circle keeps the dead corners of a fisheye frame — and most of the
horizon ring — out of the loop; the median keeps a handful of stars, a
streetlight or the moon from dragging it around the way a mean would.

Runs on the capture thread every cycle, so it works on a strided subsample
(every 4th pixel each way — ~770k samples on a 4056x3040 frame, plenty for
a median) and caches the mask per frame shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

_SUBSAMPLE_STRIDE = 4


@dataclass(frozen=True)
class BrightnessSample:
    median: float
    p99: float
    #: Number of pixels inside the circle the statistics came from.
    pixel_count: int


@lru_cache(maxsize=8)
def circle_mask(height: int, width: int, diameter_frac: float) -> np.ndarray:
    """Boolean mask, True inside the circle centred on (height/2, width/2)
    with diameter `diameter_frac * min(height, width)` — in the
    coordinates of whatever (possibly subsampled) array it is applied to."""
    radius = diameter_frac * min(height, width) / 2.0
    cy, cx = (height - 1) / 2.0, (width - 1) / 2.0
    yy, xx = np.ogrid[0:height, 0:width]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= radius**2
    mask.setflags(write=False)
    return mask


def _grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        return cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_RGB2GRAY)
    return image


def measure(image: np.ndarray, diameter_frac: float = 0.8, stride: int = _SUBSAMPLE_STRIDE) -> BrightnessSample:
    subsampled = image[::stride, ::stride]
    gray = _grayscale(subsampled)
    mask = circle_mask(gray.shape[0], gray.shape[1], float(diameter_frac))
    values = gray[mask]
    if values.size == 0:
        # A frame smaller than the stride — fall back to every pixel rather
        # than report nothing.
        values = _grayscale(image).ravel()
    median, p99 = np.percentile(values, (50, 99))
    return BrightnessSample(median=float(median), p99=float(p99), pixel_count=int(values.size))
