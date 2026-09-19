from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from caelum.config.schema import CameraConfig


@dataclass(frozen=True)
class CameraCapabilities:
    max_resolution: tuple[int, int]
    supports_streaming: bool = False


@dataclass(frozen=True)
class RawFrame:
    """One capture as delivered by a backend. `image` is already RGB — for
    the MVP, backends are expected to hand back ISP-debayered frames (e.g.
    picamera2's "main" stream); a raw-Bayer capture path with its own
    debayer step is a future extension, not needed while only picamera2 is
    supported."""

    image: np.ndarray
    exposure_us: int
    analogue_gain: float
    sensor_timestamp_ns: int
    captured_at: datetime


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
    def set_controls(self, exposure_us: int, analogue_gain: float) -> None: ...

    @abstractmethod
    def capture_frame(self) -> RawFrame:
        """Blocking. Called only from the owning CaptureWorker's thread."""
        ...
