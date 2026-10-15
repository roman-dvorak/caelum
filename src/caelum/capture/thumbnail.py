"""In-memory thumbnail encoding — no temp files, ever.

The stored per-capture thumbnail is WebP; the live stream
(`/api/frame/latest.jpg`, `/ws/stream`) stays JPEG. Both come from one
`resize()` of the frame.
"""

from __future__ import annotations

import cv2
import numpy as np


def resize(image: np.ndarray, max_dim: int = 1024) -> np.ndarray:
    h, w = image.shape[:2]
    scale = max_dim / max(h, w)
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return image


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
