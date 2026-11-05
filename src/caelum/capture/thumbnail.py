"""In-memory thumbnail encoding — no temp files, ever.

The stored per-capture thumbnail is WebP; the live stream
(`/api/frame/latest.jpg`, `/ws/stream`) stays JPEG. Both come from one
`resize()` of the frame.
"""

from __future__ import annotations

import math
from typing import Literal

import cv2
import numpy as np

Downscale = Literal["area", "peak"]

#: How far "peak" pulls a block's brightness from its mean towards its
#: brightest pixel. Full weight would turn every noise spike into a star.
_PEAK_WEIGHT = 0.5


def resize(image: np.ndarray, max_dim: int = 1024, mode: Downscale = "area") -> np.ndarray:
    """Shrink to `max_dim` on the longest side. "area" averages each block of
    source pixels, which flattens a 1-2 px star by the block area; "peak"
    additionally lifts each block's brightness towards its brightest pixel
    (hue kept), so stars survive the reduction."""
    h, w = image.shape[:2]
    scale = max_dim / max(h, w)
    if scale >= 1.0:
        return image
    size = (int(w * scale), int(h * scale))
    small = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    if mode == "peak" and image.ndim == 3 and image.dtype == np.uint8:
        small = _lift_peaks(image, small, math.ceil(1.0 / scale))
    return small


def _lift_peaks(image: np.ndarray, small: np.ndarray, block: int) -> np.ndarray:
    peak = cv2.dilate(image.max(axis=2), np.ones((block, block), np.uint8))
    peak = cv2.resize(peak, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST).astype(np.float32)
    mean = small.max(axis=2).astype(np.float32)
    target = mean + _PEAK_WEIGHT * np.maximum(peak - mean, 0.0)
    gain = np.where(mean > 0.0, target / np.maximum(mean, 1.0), 1.0)
    return np.clip(small * gain[..., None] + 0.5, 0, 255).astype(np.uint8)


def apply_gamma(image: np.ndarray, gamma: float = 1.0) -> np.ndarray:
    """Tone curve `out = in ** (1 / gamma)` on 8-bit values: above 1 lifts
    the shadows (faint stars), 1 leaves the image untouched."""
    if gamma == 1.0 or image.dtype != np.uint8:
        return image
    lut = (np.power(np.arange(256) / 255.0, 1.0 / gamma) * 255.0 + 0.5).astype(np.uint8)
    return cv2.LUT(image, lut)


def _encode(image: np.ndarray, ext: str, params: list[int]) -> bytes:
    # cv2 expects BGR; our pipeline carries RGB throughout, so swap once here.
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if image.ndim == 3 else image
    ok, buf = cv2.imencode(ext, bgr, params)
    if not ok:
        raise RuntimeError(f"{ext} encode failed")
    return buf.tobytes()


def encode_jpeg(image: np.ndarray, quality: int = 85) -> bytes:
    """Encode an already-resized RGB image as JPEG."""
    return _encode(image, ".jpg", [cv2.IMWRITE_JPEG_QUALITY, quality])


def encode_webp(image: np.ndarray, quality: int = 80) -> bytes:
    """Encode an already-resized RGB image as (lossy) WebP."""
    return _encode(image, ".webp", [cv2.IMWRITE_WEBP_QUALITY, quality])


def encode(image: np.ndarray, max_dim: int = 1024, quality: int = 85) -> bytes:
    """Resize + JPEG in one go (derivative thumbnails)."""
    return encode_jpeg(resize(image, max_dim), quality)
