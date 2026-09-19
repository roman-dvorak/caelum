from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from caelum.auth import Role
from caelum.capture.stats import FrameStats
from caelum.config.schema import CameraConfig


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


class CameraOptionsResponse(BaseModel):
    """Everything the UI needs to offer a camera choice rather than a guess."""

    backends: list[str]
    #: Device nodes present on this host, for the `opencv` backend's sensor_id.
    v4l2_devices: list[str]
    configured: CameraConfig
    #: What the capture thread currently has open — None before the first
    #: successful open, and different from `configured` while a change is
    #: still pending or if opening the new camera is failing.
    active: CameraConfig | None
    active_backend_class: str
    applied: bool


class ExposureOverrideRequest(BaseModel):
    exposure_us: int | None = None
    analogue_gain: float | None = None
    clear: bool = False


class PluginUpdateRequest(BaseModel):
    enabled: bool | None = None
    order: int | None = None
    settings: dict[str, Any] | None = None


# ---- auth ----------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: Role = "viewer"


class UpdateUserRequest(BaseModel):
    role: Role | None = None
    password: str | None = None


class AuthContextResponse(BaseModel):
    """Unauthenticated bootstrap for the SPA — what is this deployment, and
    who am I on it? Deliberately leaks no account names or config values."""

    auth_enabled: bool
    preview_access: str
    terminal_enabled: bool
    docs_url: str
    authenticated: bool
    username: str | None
    role: str | None


# ---- files & frames ------------------------------------------------------


class FileEntry(BaseModel):
    name: str
    path: str
    kind: Literal["dir", "file"]
    size: int
    modified_at: str
    media: Literal["image", "fits", "json", "text", "other"]


class DirectoryListing(BaseModel):
    path: str
    parent: str | None
    entries: list[FileEntry]
    total_bytes: int


class UsageResponse(BaseModel):
    by_subdir: dict[str, int]
    total_bytes: int
    disk_free_bytes: int
    disk_total_bytes: int


class FrameDateSummary(BaseModel):
    date: str
    thumbnails: int
    raws: int
    derivatives: int
    total_bytes: int


class FrameEntry(BaseModel):
    time: str
    captured_at: str
    thumbnail: str | None
    raw: str | None
    metadata: str | None
    total_bytes: int


class FrameListResponse(BaseModel):
    date: str
    frames: list[FrameEntry]
    derivatives: list[FileEntry]


class DeleteFramesRequest(BaseModel):
    date: str
    #: Empty means "the whole date", which is the bulk-delete case.
    times: list[str] = Field(default_factory=list)
    kinds: list[Literal["raw", "thumbnails", "derivatives"]] = Field(
        default_factory=lambda: ["raw", "thumbnails", "derivatives"]
    )
