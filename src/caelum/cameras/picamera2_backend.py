"""Raspberry Pi camera backend via picamera2/libcamera.

Only importable where `picamera2` is installed (the `picamera2` extra,
ARM-only) — see registry.py for the lazy import that keeps this module out
of the way on dev machines. Not exercised by the test suite (no hardware
here); validate on real hardware per the project plan's verification
checklist.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from caelum.config.schema import CameraConfig

from .base import CameraBackend, CameraCapabilities, RawFrame

try:
    from picamera2 import Picamera2
except ImportError as exc:  # pragma: no cover - exercised only on real hardware
    Picamera2 = None  # type: ignore[assignment,misc]
    _import_error: Exception | None = exc
else:
    _import_error = None


class Picamera2Backend(CameraBackend):
    def __init__(self, cfg: CameraConfig) -> None:
        if Picamera2 is None:
            raise RuntimeError(
                "picamera2 is not installed — install the 'picamera2' extra on a Raspberry Pi"
            ) from _import_error
        self.capabilities = CameraCapabilities(max_resolution=cfg.resolution, supports_streaming=True)
        self._resolution = cfg.resolution
        self._picam2: Picamera2 | None = None

    def open(self) -> None:
        self._picam2 = Picamera2()
        config = self._picam2.create_still_configuration(main={"size": self._resolution})
        self._picam2.configure(config)
        self._picam2.start()

    def close(self) -> None:
        if self._picam2 is not None:
            self._picam2.stop()
            self._picam2.close()
            self._picam2 = None

    def configure(self, cfg: CameraConfig) -> None:
        self._resolution = cfg.resolution
        if self._picam2 is not None:
            self.close()
            self.open()

    def set_controls(self, exposure_us: int, analogue_gain: float) -> None:
        assert self._picam2 is not None, "set_controls() called before open()"
        self._picam2.set_controls(
            {
                "AeEnable": False,  # the app owns exposure, never the camera's built-in AE
                "ExposureTime": exposure_us,
                "AnalogueGain": analogue_gain,
            }
        )

    def capture_frame(self) -> RawFrame:
        assert self._picam2 is not None, "capture_frame() called before open()"
        request = self._picam2.capture_request()
        try:
            image = request.make_array("main")
            meta = request.get_metadata()
        finally:
            request.release()

        # picamera2's "main" stream for a still configuration is ISP-processed
        # (already debayered); drop an alpha channel if the platform's default
        # format includes one, keeping RGB order — verify on real hardware,
        # per the project plan's verification checklist.
        if image.ndim == 3 and image.shape[2] == 4:
            image = image[:, :, :3]
        image = np.ascontiguousarray(image)

        return RawFrame(
            image=image,
            exposure_us=int(meta.get("ExposureTime", 0)),
            analogue_gain=float(meta.get("AnalogueGain", 0.0)),
            sensor_timestamp_ns=int(meta.get("SensorTimestamp", 0)),
            captured_at=datetime.now(UTC),
        )
