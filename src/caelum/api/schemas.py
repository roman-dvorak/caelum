from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from caelum.auth import Role
from caelum.capture.stats import FrameStats
from caelum.config.schema import CameraConfig


class ExposureDiagnosticsResponse(BaseModel):
    """Mirrors `control.exposure.ExposureDiagnostics` — all in EV. Image
    brightness is relative to full scale (0 EV = 255 ADU); exposure*gain
    is log2(seconds) + log2(gain)."""

    sky_period: str
    target_ev: float
    deadband_ev: float
    ev_min: float
    ev_max: float
    kp: float
    ki: float
    kd: float
    measured_ev: float | None = None
    p99_ev: float | None = None
    error_ev: float | None = None
    correction_ev: float | None = None
    applied_ev: float | None = None
    required_ev: float | None = None
    remaining_ev: float | None = None
    p_term_ev: float | None = None
    i_term_ev: float | None = None
    d_term_ev: float | None = None
    output_ev: float | None = None
    change_ev: float | None = None
    ev_exposure: float | None = None
    ev_gain: float | None = None
    limited: Literal["none", "upper", "lower"] = "none"
    integrating: bool = False
    within_deadband: bool = False
    saturated: bool = False
    manual: bool = False


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
    #: What the exposure controller measured last cycle and would do next —
    #: None only if sky state can't be computed (should not happen in
    #: practice; the calculator has no failure mode today).
    exposure_diagnostics: ExposureDiagnosticsResponse | None = None
    #: Counters from the frame-processing sink (worker pid/liveness,
    #: in-flight/dropped/failed frames, last latency) — None if not wired.
    processing: dict[str, Any] | None = None
    #: Current spacing between captures — `capture_interval_s`, or a whole
    #: multiple of it while the exposure doesn't fit in one interval.
    frame_period_s: float | None = None
    #: The capture program running (see /api/capture-programs): name,
    #: sha256, origin, failures, whether default.py stands in for it.
    capture_program: dict[str, Any] | None = None
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
    #: Set when `CAELUM_CAMERA_BACKEND` is pinning the backend regardless of
    #: `configured`/`active` — the UI shows this so a selection that never
    #: seems to "apply" is explained rather than left looking broken.
    backend_override: str | None = None


class ExposureOverrideRequest(BaseModel):
    exposure_us: int | None = None
    analogue_gain: float | None = None
    clear: bool = False


class WhiteBalanceRequest(BaseModel):
    red_gain: float = Field(ge=0.1, le=8.0)
    blue_gain: float = Field(ge=0.1, le=8.0)


class WhiteBalanceResponse(BaseModel):
    red_gain: float
    blue_gain: float
    auto: bool


class WhiteBalanceAutoCalibrateRequest(BaseModel):
    #: Fractional (0..1) patch over the latest frame — should cover a
    #: neutral gray/white surface for the derived gains to be meaningful.
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)


class RawWhiteBalanceInfo(BaseModel):
    #: Relative to the data directory — pass it back to `/pixels` and `PUT`.
    path: str
    captured_at: str | None
    sensor_width: int
    sensor_height: int
    #: Size of the `/pixels` image for the same `max_dim`.
    width: int
    height: int
    #: The file's `AsShotNeutral` — `[1/red_gain, 1, 1/blue_gain]`.
    as_shot_neutral: list[float] | None
    red_gain: float
    blue_gain: float
    #: The camera's gains when the frame was taken (XMP), i.e. before any edit.
    captured_red_gain: float | None
    captured_blue_gain: float | None
    #: White-balanced camera RGB -> linear sRGB, 3x3 row-major.
    render_matrix: list[list[float]]
    camera_wb_auto: bool
    camera_red_gain: float
    camera_blue_gain: float


class RawWhiteBalanceSaveRequest(BaseModel):
    path: str = Field(min_length=1)
    red_gain: float = Field(ge=0.1, le=8.0)
    blue_gain: float = Field(ge=0.1, le=8.0)


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
    media: Literal["image", "fits", "raw", "json", "text", "other"]


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


class DerivativeKindSummary(BaseModel):
    """One row per derivative kind (keogram, keogram_live, meteor_crop, ...)
    present in a date/night — drives the Recordings UI's derivative sub-tabs."""

    kind: str
    count: int


class DerivativeEntry(BaseModel):
    #: The derivative file's own stem (`<YYYYMMDD-HHMMSS>_<worker_id>_<kind>`)
    #: — a unique id for this one derivative, since more than one worker
    #: could in principle produce output in the same second.
    stem: str
    captured_at: str
    #: Small backend-generated JPEG for the gallery grid; None only if the
    #: thumbnail write somehow failed while the full file succeeded.
    thumbnail: str | None
    full: str
    size: int


class DerivativeListResponse(BaseModel):
    kind: str
    entries: list[DerivativeEntry]
    total: int
    limit: int
    offset: int


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


# ---- overlay assets --------------------------------------------------------


class OverlayAssetInfo(BaseModel):
    name: str
    size: int


# ---- system ----------------------------------------------------------------


class DiskUsageInfo(BaseModel):
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


class NetworkInterfaceInfo(BaseModel):
    name: str
    is_up: bool
    #: None when the driver doesn't report a link speed (common for loopback
    #: and virtual interfaces, and for a down link).
    speed_mbps: int | None
    addresses: list[str]


class SystemInfoResponse(BaseModel):
    hostname: str
    uptime_s: float
    cpu_percent: float
    cpu_count: int
    #: 1/5/15-minute load average. None on platforms without one (Windows).
    load_avg: tuple[float, float, float] | None
    mem_total_bytes: int
    mem_used_bytes: int
    mem_percent: float
    disks: list[DiskUsageInfo]
    #: Sensor label -> degrees Celsius. Empty where the platform exposes none
    #: (e.g. no `/sys/class/thermal`, or running outside Linux).
    temperatures_c: dict[str, float]
    network: list[NetworkInterfaceInfo]


class SystemActionResponse(BaseModel):
    ok: bool
    message: str


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
