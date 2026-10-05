from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

import numpy as np

from caelum.config.schema import CameraConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraCapabilities:
    """What a camera can do — only as much as some backend really uses.

    Nothing is ever refused because of it: a request outside a range is
    clamped into it, an option the camera lacks is left out, and both are
    recorded with the frame (`RawFrame.capture_settings`). A range of None
    means unknown — the value is passed through as is."""

    max_resolution: tuple[int, int]
    supports_streaming: bool = False
    model: str = ""
    exposure_us: tuple[int, int] | None = None
    analogue_gain: tuple[float, float] | None = None
    #: Delivers the sensor's raw (Bayer) data — i.e. a DNG can be written.
    raw: bool = False
    #: Accepts per-capture colour gains.
    colour_gains: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_resolution": list(self.max_resolution),
            "exposure_us": list(self.exposure_us) if self.exposure_us else None,
            "analogue_gain": list(self.analogue_gain) if self.analogue_gain else None,
            "raw": self.raw,
            "colour_gains": self.colour_gains,
        }


@dataclass(frozen=True)
class CaptureRequest:
    """What a capture program asks the camera for, for one frame.

    `extra` takes parameters no backend supports yet (ROI, binning, focus,
    filter, ...): they are ignored, and recorded as such, until one does."""

    exposure_us: int
    analogue_gain: float = 1.0
    #: (red, blue); None = the camera's configured white balance.
    colour_gains: tuple[float, float] | None = None
    raw: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"exposure_us": int(self.exposure_us), "analogue_gain": float(self.analogue_gain)}
        if self.colour_gains is not None:
            out["colour_gains"] = [float(g) for g in self.colour_gains]
        out["raw"] = self.raw
        if self.extra:
            out["extra"] = dict(self.extra)
        return out


def _clamp(value, bounds):
    if bounds is None:
        return value, False
    low, high = bounds
    clamped = min(max(value, low), high)
    return clamped, clamped != value


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
    #: For frames taken through a `CaptureRequest`: what was requested, what
    #: the camera really used, and what it clamped or ignored
    #: (`CameraBackend.capture`).
    capture_settings: dict[str, Any] | None = None


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

    def set_request_colour_gains(self, gains: tuple[float, float] | None) -> None:  # noqa: B027
        """Colour gains for the next capture only; None goes back to the
        configured white balance. Backends with `capabilities.colour_gains`
        implement it."""

    # ---- best-effort requests ---------------------------------------------

    def apply_request(self, req: CaptureRequest) -> dict[str, Any]:
        """Set the camera up for `req` as far as it can go: values outside
        the camera's ranges are clamped, options it lacks are ignored.
        Returns the record of that for `finish_request()`."""
        caps = self.capabilities
        clamped: list[str] = []
        ignored: list[str] = []
        exposure_us, was = _clamp(int(req.exposure_us), caps.exposure_us)
        if was:
            clamped.append("exposure_us")
        gain, was = _clamp(float(req.analogue_gain), caps.analogue_gain)
        if was:
            clamped.append("analogue_gain")
        if caps.colour_gains:
            self.set_request_colour_gains(req.colour_gains)
        elif req.colour_gains is not None:
            ignored.append("colour_gains")
        if req.raw and not caps.raw:
            ignored.append("raw")
        ignored.extend(f"extra.{key}" for key in req.extra)
        self.set_controls(exposure_us, gain)
        if clamped or ignored:
            logger.info(
                "Capture request adjusted to the camera: clamped %s, ignored %s (exposure %d us, gain %.2f)",
                clamped or "-", ignored or "-", exposure_us, gain,
            )
        return {
            "requested": req.to_dict(),
            "commanded": {"exposure_us": exposure_us, "analogue_gain": gain},
            "clamped": clamped,
            "ignored": ignored,
        }

    @staticmethod
    def finish_request(frame: RawFrame, record: dict[str, Any]) -> RawFrame:
        """`frame` with its `capture_settings`: the record from
        `apply_request()` plus what the camera reports it actually used."""
        applied: dict[str, Any] = {"exposure_us": frame.exposure_us, "analogue_gain": frame.analogue_gain}
        gains = frame.camera_metadata.get("ColourGains")
        if gains:
            applied["colour_gains"] = [float(g) for g in gains]
        applied["raw"] = frame.raw_bayer is not None
        return replace(frame, capture_settings={**record, "applied": applied})

    def capture(self, req: CaptureRequest) -> RawFrame:
        """One frame for `req`, best effort (see `apply_request`)."""
        record = self.apply_request(req)
        return self.finish_request(self.capture_frame(), record)
