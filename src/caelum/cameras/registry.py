"""Backend selection — explicit, never a silent fallback on real hardware.

`picamera2` is only imported lazily, inside this function, so a dev machine
without it installed can still import this package freely as long as it
never actually selects the "picamera2" backend.
"""

from __future__ import annotations

from caelum.config.schema import CameraConfig

from .base import CameraBackend
from .mock_backend import MockCameraBackend
from .opencv_backend import OpenCVBackend


def create_camera_backend(cfg: CameraConfig) -> CameraBackend:
    if cfg.backend == "mock":
        return MockCameraBackend(cfg)
    if cfg.backend == "opencv":
        return OpenCVBackend(cfg)
    if cfg.backend == "picamera2":
        from .picamera2_backend import Picamera2Backend

        return Picamera2Backend(cfg)
    raise ValueError(f"Unknown camera backend: {cfg.backend!r}")
