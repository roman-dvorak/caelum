"""Synthetic-frame backend for dev/CI — no hardware required.

`CameraRegistry` picks this only when explicitly configured/overridden
(never a silent fallback on real hardware — see registry.py).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import numpy as np

from caelum.config.schema import CameraConfig

from .base import CameraBackend, CameraCapabilities, RawFrame

# Deliberately small and fixed, independent of the configured resolution:
# this backend exists to exercise the control loop (exposure/gain feedback,
# sky-state driven policy, event bus, derivatives) fast and deterministically
# — not to simulate a real sensor's image size.
_RESOLUTION = (320, 240)


def _build_base_scene() -> np.ndarray:
    w, h = _RESOLUTION
    yy, _xx = np.mgrid[0:h, 0:w]
    scene = (yy / h) * 40.0  # brighter near the "horizon" row
    star_rng = np.random.default_rng(42)  # fixed seed: stars are stable across instances
    for _ in range(15):
        cy, cx = int(star_rng.integers(1, h - 1)), int(star_rng.integers(1, w - 1))
        scene[cy - 1 : cy + 2, cx - 1 : cx + 2] += star_rng.uniform(150, 255)
    return scene


class MockCameraBackend(CameraBackend):
    def __init__(self, cfg: CameraConfig | None = None, seed: int = 0) -> None:
        self.capabilities = CameraCapabilities(max_resolution=_RESOLUTION, supports_streaming=True)
        self._rng = np.random.default_rng(seed)
        self._exposure_us = 10_000
        self._analogue_gain = 1.0
        self._opened = False
        self._base_scene = _build_base_scene()

    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def configure(self, cfg: CameraConfig) -> None:
        pass  # resolution intentionally not applied — see module docstring

    def set_controls(self, exposure_us: int, analogue_gain: float) -> None:
        self._exposure_us = exposure_us
        self._analogue_gain = analogue_gain

    def capture_frame(self) -> RawFrame:
        if not self._opened:
            raise RuntimeError("MockCameraBackend.capture_frame() called before open()")

        brightness_factor = (self._exposure_us / 10_000.0) * self._analogue_gain
        noise = self._rng.normal(0.0, 3.0, size=self._base_scene.shape)
        frame = np.clip(self._base_scene * brightness_factor + noise, 0, 255).astype(np.uint8)
        image = np.stack([frame, frame, frame], axis=-1)

        return RawFrame(
            image=image,
            exposure_us=self._exposure_us,
            analogue_gain=self._analogue_gain,
            sensor_timestamp_ns=time.time_ns(),
            captured_at=datetime.now(UTC),
        )
