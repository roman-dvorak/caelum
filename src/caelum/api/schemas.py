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
    #: IANA name from `location.timezone` (e.g. "Europe/Prague") — every
    #: timestamp elsewhere in the API is UTC; this is what the frontend
    #: converts to and labels, so "what timezone am I looking at" is never
    #: a guess. See packages/ui's `formatLocalTime`.
    timezone: str


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
    #: The full `YYYYMMDD-HHMMSS` (UTC) stem every file for this capture
    #: shares — self-sufficient: it is what `DELETE /api/frames` takes back,
    #: and it is enough on its own to know which UTC date directory the
    #: files live in, so a night-mode selection spanning two UTC dates
    #: needs no separate date field to delete correctly.
    time: str
    captured_at: str
    thumbnail: str | None
    raw: str | None
    metadata: str | None
    total_bytes: int


class FrameListResponse(BaseModel):
    #: Echoes whichever of `date`/`night` the request used.
    date: str
    frames: list[FrameEntry]
    derivatives: list[FileEntry]
    #: Total frames in this date/night before `limit`/`offset` were applied
    #: — what the UI needs to render "51-100 of 1200" and page count.
    total_frames: int
    limit: int
    offset: int
    #: Every UTC date this response draws from — one entry in date mode,
    #: up to two in night mode. Lets the UI bulk-delete a whole observation
    #: night correctly (one DELETE per UTC date) without needing every page
    #: of results loaded first to know which dates are involved.
    utc_dates: list[str]


class ObservationNightSummary(BaseModel):
    """Same shape as `FrameDateSummary`, but `date` is the *local* calendar
    date the night started on (see `next_sunrise`-based grouping in
    api/routes/frames.py) rather than the UTC directory date — a session
    that runs past UTC midnight stays one entry instead of splitting."""

    date: str
    thumbnails: int
    raws: int
    derivatives: int
    total_bytes: int


class DeleteFramesRequest(BaseModel):
    #: Required when `times` is empty (the whole-date bulk-delete case).
    #: Ignored otherwise — each entry in `times` is a full `YYYYMMDD-HHMMSS`
    #: stem and carries its own date, so a selection spanning two UTC dates
    #: (an observation night crossing midnight) deletes correctly without it.
    date: str | None = None
    times: list[str] = Field(default_factory=list)
    kinds: list[Literal["raw", "thumbnails", "derivatives"]] = Field(
        default_factory=lambda: ["raw", "thumbnails", "derivatives"]
    )
