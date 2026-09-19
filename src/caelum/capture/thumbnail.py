"""In-memory JPEG thumbnail encoding — no temp files, ever."""

from __future__ import annotations

import cv2
import numpy as np


def encode(image: np.ndarray, max_dim: int = 1024, quality: int = 85) -> bytes:
    h, w = image.shape[:2]
    scale = max_dim / max(h, w)
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    # cv2 expects BGR; our pipeline carries RGB throughout, so swap once here.
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()
