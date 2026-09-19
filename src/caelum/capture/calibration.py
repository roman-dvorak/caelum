"""In-memory dark-frame library + subtraction.

Dark frames are loaded once into RAM at startup (never re-read from disk per
capture) and matched to the current exposure/gain within a tolerance; if no
dark frame is close enough — including the common case of no library at all
yet — calibration is a pass-through, never a hard failure.

Dark frame files: `<darks_dir>/dark_<exposure_us>us_<gain>g_<width>x<height>.npy`,
a `uint8` array shaped like the sensor's RGB output.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_DARK_FILENAME_RE = re.compile(r"dark_(\d+)us_([\d.]+)g_(\d+)x(\d+)\.npy$")

# How far off a dark frame's exposure/gain may be from the current capture
# and still be considered "close enough" to subtract.
_MAX_LOG_EXPOSURE_DISTANCE = math.log(2.0)  # within a factor of 2x
_MAX_GAIN_DISTANCE = 1.5


@dataclass(frozen=True)
class DarkFrameKey:
    exposure_us: int
    gain: float
    resolution: tuple[int, int]


class DarkLibrary:
    def __init__(self, darks_dir: Path | None = None) -> None:
        self._darks: dict[DarkFrameKey, np.ndarray] = {}
        if darks_dir is not None and darks_dir.exists():
            self._load(darks_dir)

    def _load(self, darks_dir: Path) -> None:
        for path in sorted(darks_dir.glob("dark_*.npy")):
            match = _DARK_FILENAME_RE.match(path.name)
            if not match:
                logger.warning("Ignoring dark frame with unrecognized filename: %s", path.name)
                continue
            exposure_us, gain, width, height = match.groups()
            key = DarkFrameKey(int(exposure_us), float(gain), (int(width), int(height)))
            try:
                self._darks[key] = np.load(path)
            except Exception:
                logger.exception("Failed loading dark frame %s", path)
        if self._darks:
            logger.info("Loaded %d dark frame(s) into memory", len(self._darks))

    def __len__(self) -> int:
        return len(self._darks)

    def _nearest(self, exposure_us: int, gain: float, resolution: tuple[int, int]) -> DarkFrameKey | None:
        candidates = [k for k in self._darks if k.resolution == resolution]
        if not candidates:
            return None

        def distance(k: DarkFrameKey) -> float:
            log_exposure_dist = abs(math.log(max(k.exposure_us, 1)) - math.log(max(exposure_us, 1)))
            gain_dist = abs(k.gain - gain)
            return log_exposure_dist + gain_dist

        best = min(candidates, key=distance)
        log_exposure_dist = abs(math.log(max(best.exposure_us, 1)) - math.log(max(exposure_us, 1)))
        gain_dist = abs(best.gain - gain)
        if log_exposure_dist > _MAX_LOG_EXPOSURE_DISTANCE or gain_dist > _MAX_GAIN_DISTANCE:
            return None
        return best

    def apply_dark(self, image: np.ndarray, exposure_us: int, gain: float) -> np.ndarray:
        resolution = (image.shape[1], image.shape[0])
        key = self._nearest(exposure_us, gain, resolution)
        if key is None:
            return image
        dark = self._darks[key]
        if dark.shape != image.shape:
            logger.warning("Dark frame shape %s does not match image shape %s — skipping", dark.shape, image.shape)
            return image
        return np.clip(image.astype(np.int16) - dark.astype(np.int16), 0, 255).astype(np.uint8)
