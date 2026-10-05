"""Value objects passed between the capture thread, the sinks and the
processing process. Everything that crosses the process boundary is plain
picklable data — pixel arrays never do, they travel through shared memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from caelum.cameras.base import RawFrame
from caelum.capture.brightness import BrightnessSample
from caelum.capture.metadata import SkyStateModel
from caelum.capture.stats import FrameStats
from caelum.config.schema import FULL_SCALE_ADU, AppConfig


@dataclass(frozen=True)
class ProcessingSettings:
    thumbnail_max_dim: int
    webp_quality: int
    jpeg_quality: int
    #: Pixel level counted as saturated in the frame stats (ADU).
    saturation_adu: float
    brightness_roi_diameter_frac: float
    target_ev: float
    #: `LocationConfig` as a dict — goes into the DNG's XMP.
    location: dict[str, Any] = field(default_factory=dict)
    software: str = "caelum"
    dng_compress: bool = True

    @classmethod
    def from_config(cls, cfg: AppConfig, period: str) -> ProcessingSettings:
        from caelum import __version__

        preset = cfg.exposure_policy.preset_for(period)
        return cls(
            thumbnail_max_dim=cfg.storage_policy.thumbnail_max_dim,
            webp_quality=cfg.storage_policy.webp_quality,
            jpeg_quality=cfg.storage_policy.jpeg_quality,
            saturation_adu=FULL_SCALE_ADU * 2.0**preset.saturation_ev,
            brightness_roi_diameter_frac=cfg.exposure_policy.brightness_roi_diameter_frac,
            target_ev=preset.target_ev,
            location=cfg.location.model_dump(),
            software=f"caelum {__version__}",
            dng_compress=cfg.storage_policy.dng_compress,
        )


@dataclass(frozen=True)
class FrameSubmission:
    """What the capture thread hands to a `FrameSink` — one per capture."""

    raw: RawFrame
    sky_state: SkyStateModel
    save_raw: bool
    settings: ProcessingSettings
    #: The capture thread's own measurement, used by the exposure loop.
    brightness: BrightnessSample | None = None
    #: `control.exposure.exposure_control_snapshot` of the loop's cycle on
    #: this frame.
    exposure_control: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    #: See `FrameMetadata.capture_set`; members other than the
    #: representative are stored under `<stem>_set/` and never published.
    capture_set: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None


@dataclass(frozen=True)
class FrameInfo:
    """Everything about a capture except its pixels."""

    captured_at: datetime
    exposure_us: int
    analogue_gain: float
    sensor_timestamp_ns: int
    sky_state: dict[str, Any]
    save_raw: bool
    settings: ProcessingSettings
    raw_config: dict[str, Any] | None
    camera_metadata: dict[str, Any]
    camera_model: str
    brightness_median: float | None
    exposure_control: dict[str, Any] | None = None
    capture_settings: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    capture_set: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None

    @property
    def is_hidden_member(self) -> bool:
        """A capture-set member that isn't the representative."""
        return bool(self.capture_set) and self.capture_set.get("role") == "member"

    @property
    def set_time(self) -> datetime:
        """The capture time files are named after — the representative's."""
        if self.capture_set and self.capture_set.get("representative_captured_at"):
            return datetime.fromisoformat(self.capture_set["representative_captured_at"])
        return self.captured_at

    @classmethod
    def from_submission(cls, submission: FrameSubmission) -> FrameInfo:
        raw = submission.raw
        return cls(
            captured_at=raw.captured_at,
            exposure_us=raw.exposure_us,
            analogue_gain=raw.analogue_gain,
            sensor_timestamp_ns=raw.sensor_timestamp_ns,
            sky_state=submission.sky_state.model_dump(),
            save_raw=submission.save_raw,
            settings=submission.settings,
            raw_config=dict(raw.raw_stream_config) if raw.raw_stream_config is not None else None,
            camera_metadata=dict(raw.camera_metadata),
            camera_model=raw.camera_model,
            brightness_median=submission.brightness.median if submission.brightness else None,
            exposure_control=submission.exposure_control,
            capture_settings=raw.capture_settings,
            provenance=submission.provenance,
            capture_set=submission.capture_set,
            annotations=submission.annotations,
        )


@dataclass(frozen=True)
class ProcessingJob:
    """Main -> processing process. Pixels are in the named shared-memory
    slot: RGB at offset 0, the raw Bayer buffer (if any) at `raw_offset`."""

    job_id: int
    generation: int
    slot_name: str
    rgb_shape: tuple[int, ...]
    raw_shape: tuple[int, ...] | None
    raw_offset: int
    info: FrameInfo


@dataclass(frozen=True)
class FrameResult:
    """Processing process -> main, as soon as the frame is viewable (before
    the slow raw write): the calibrated RGB is back in the slot by then."""

    job_id: int
    stats: FrameStats
    live_jpeg: bytes
    metadata_json: str
    thumbnail_path: str | None


@dataclass(frozen=True)
class JobDone:
    """Processing process -> main, once the slot may be reused."""

    job_id: int
    raw_path: str | None = None
    error: str | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)


class FrameSink(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def submit(self, submission: FrameSubmission) -> bool:
        """Hand one capture off. Must not block on processing; returns False
        if the frame was dropped instead."""
        ...

    def submit_set(self, submissions: list[FrameSubmission]) -> bool:
        """Hand off all members of a capture set — all or nothing."""
        ...

    @property
    def stats(self) -> dict[str, Any]: ...
