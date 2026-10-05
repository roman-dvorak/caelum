from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from caelum.config.schema import CameraConfig


@dataclass(frozen=True)
class CameraCapabilities:
    max_resolution: tuple[int, int]
    supports_streaming: bool = False


@dataclass(frozen=True)
class RawFrame:
    """One capture as delivered by a backend. `image` is always ISP-debayered
    RGB (e.g. picamera2's "main" stream) — everything downstream (exposure
    measurement, thumbnails, derivatives) works on it.

    `raw_bayer` is the sensor's undebayered data from the same exposure, as
    the backend's raw buffer (for picamera2: uint8 rows x stride, possibly
    CSI-2 packed), with `raw_stream_config` describing its layout (`format`,
    `size`, `stride`). Only backends with a real raw stream fill it in —
    for the rest it stays None and no DNG gets written."""

    image: np.ndarray
    exposure_us: int
    analogue_gain: float
    sensor_timestamp_ns: int
    captured_at: datetime
    raw_bayer: np.ndarray | None = None
    raw_stream_config: dict[str, Any] | None = None
    #: The backend's full per-frame metadata (picamera2: ColourGains,
    #: ColourCorrectionMatrix, SensorBlackLevels, DigitalGain, ...), already
    #: reduced to plain JSON-able values.
    camera_metadata: dict[str, Any] = field(default_factory=dict)
    camera_model: str = ""
    #: When the exposure started, CLOCK_MONOTONIC — for backends that know
    #: it (picamera2); lets the capture loop measure its start latency.
    exposure_start_monotonic_ns: int | None = None


class CameraStalled(RuntimeError):
    """The camera stopped delivering frames. Raised by backends that can
    tell, so the capture loop can escalate when reopening doesn't help."""


class CameraBackend(ABC):
    """One instance is owned by exactly one `CaptureWorker` for the whole
    process lifetime — see events.py / the project plan for why."""

    capabilities: CameraCapabilities

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def configure(self, cfg: CameraConfig) -> None: ...

    @abstractmethod
    def set_controls(self, exposure_us: int, analogue_gain: float) -> None:
        """Exposure and gain for the next `capture_frame()`."""

    def set_white_balance(self, red_gain: float, blue_gain: float, auto: bool = False) -> None:  # noqa: B027
        """Default no-op for backends without white-balance control (mock,
        opencv/V4L2). Deliberately not `@abstractmethod` and kept separate
        from `set_controls()` — that method is on the per-cycle exposure
        control path, and this must never be called from there."""

    @abstractmethod
    def capture_frame(self) -> RawFrame:
        """Blocking. Called only from the owning CaptureWorker's thread."""
        ...
