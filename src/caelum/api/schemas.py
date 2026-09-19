from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from caelum.capture.stats import FrameStats


class StatusResponse(BaseModel):
    camera_backend: str
    capturing: bool
    exposure_us: int
    analogue_gain: float
    stream_mode: bool
    manual_exposure_override: bool
    last_capture_at: str | None
    last_stats: FrameStats | None
    last_save_raw: bool | None


class SkyStateResponse(BaseModel):
    sun_altitude_deg: float
    sun_azimuth_deg: float
    moon_altitude_deg: float
    moon_azimuth_deg: float
    moon_illumination: float
    period: str


class ConfigPatchRequest(BaseModel):
    patch: dict[str, Any]


class CameraModeRequest(BaseModel):
    stream_mode: bool


class ExposureOverrideRequest(BaseModel):
    exposure_us: int | None = None
    analogue_gain: float | None = None
    clear: bool = False


class PluginUpdateRequest(BaseModel):
    enabled: bool | None = None
    order: int | None = None
    settings: dict[str, Any] | None = None
