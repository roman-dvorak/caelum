"""Generic UVC/V4L2 webcam backend via OpenCV — lets the whole pipeline
(capture loop, sky-state driven policy, derivatives, API, web UI) be
exercised on an ordinary PC with a plugged-in webcam, no astro hardware
required.

Honest caveat: consumer UVC webcams' manual exposure/gain controls are
inconsistent across drivers — units, ranges, and whether manual mode is
even honored all vary by device/driver. This backend disables auto-exposure
and maps our microsecond/gain units onto whatever V4L2 reports on a
best-effort basis; it's a pipeline-testing tool, not a substitute for
picamera2/ZWO-grade control on real astro hardware.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import cv2
import numpy as np

from caelum.config.schema import CameraConfig

from .base import CameraBackend, CameraCapabilities, RawFrame

logger = logging.getLogger(__name__)

# UVC exposure is conventionally reported in 100-microsecond units once
# manual mode is engaged (the common convention across V4L2 UVC drivers).
_UVC_EXPOSURE_UNIT_US = 100.0

# V4L2's own enum for manual exposure mode (V4L2_EXPOSURE_MANUAL) — passed
# through directly by OpenCV's V4L2 backend on Linux (unlike the 0.25/0.75
# convention some other backends use).
_V4L2_EXPOSURE_MANUAL = 1


def _parse_device(sensor_id: str) -> int | str:
    try:
        return int(sensor_id)
    except ValueError:
        return sensor_id


class OpenCVBackend(CameraBackend):
    def __init__(self, cfg: CameraConfig) -> None:
        self.capabilities = CameraCapabilities(max_resolution=cfg.resolution, supports_streaming=True)
        self._device = _parse_device(cfg.sensor_id)
        self._resolution = cfg.resolution
        self._cap: cv2.VideoCapture | None = None
        self._last_exposure_us = 10_000
        self._last_gain = 1.0

    def open(self) -> None:
        cap = cv2.VideoCapture(self._device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open V4L2 camera at {self._device!r}")

        width, height = self._resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, _V4L2_EXPOSURE_MANUAL):
            logger.warning("Camera %r did not accept manual-exposure mode — AE may still be active", self._device)

        actual = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if actual != tuple(self._resolution):
            logger.info("Camera %r negotiated %s instead of requested %s", self._device, actual, self._resolution)
            self._resolution = actual
            self.capabilities = CameraCapabilities(max_resolution=actual, supports_streaming=True)

        self._cap = cap

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def configure(self, cfg: CameraConfig) -> None:
        self._resolution = cfg.resolution
        if self._cap is not None:
            self.close()
            self.open()

    def set_controls(self, exposure_us: int, analogue_gain: float) -> None:
        assert self._cap is not None, "set_controls() called before open()"
        self._cap.set(cv2.CAP_PROP_EXPOSURE, exposure_us / _UVC_EXPOSURE_UNIT_US)
        self._cap.set(cv2.CAP_PROP_GAIN, analogue_gain)
        self._last_exposure_us = exposure_us
        self._last_gain = analogue_gain

    def capture_frame(self) -> RawFrame:
        assert self._cap is not None, "capture_frame() called before open()"
        ok, frame_bgr = self._cap.read()
        if not ok or frame_bgr is None:
            raise RuntimeError(f"V4L2 frame grab failed on {self._device!r}")
        image = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return RawFrame(
            image=np.ascontiguousarray(image),
            exposure_us=self._last_exposure_us,
            analogue_gain=self._last_gain,
            sensor_timestamp_ns=0,  # UVC devices don't expose a hardware timestamp worth trusting
            captured_at=datetime.now(UTC),
        )
