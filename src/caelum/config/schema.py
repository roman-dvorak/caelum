"""Pydantic models for the runtime AppConfig.

This is the single schema kept in sync between disk and Redis by
`config/manager.py`. `config/default.json` is a JSON dump of `AppConfig()`'s
defaults (see `scripts/dev_run.sh` / tests for how it's (re)generated).
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SkyPeriod = Literal[
    "day",
    "civil_twilight",
    "nautical_twilight",
    "astronomical_twilight",
    "night",
]

SKY_PERIODS: tuple[SkyPeriod, ...] = (
    "day",
    "civil_twilight",
    "nautical_twilight",
    "astronomical_twilight",
    "night",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LensConfig(StrictModel):
    """Fisheye lens calibration — lets a pixel position in a captured frame
    be converted to an alt/az sky position (see
    `caelum.derivatives.projection.fraction_to_altaz`). Deliberately mirrors
    `TelescopePositionSettings`'s field shapes (same physical projection,
    see `projection.py`'s module docstring for why they stay separate
    config objects). Manual entry only for now — `center_x`/`center_y`/
    `radius` are meant to eventually be filled in by a visual, star-based
    calibration tool instead of typed by hand."""

    projection: Literal["equidistant_fisheye"] = "equidistant_fisheye"
    #: Fractional (0..1) zenith pixel — where straight up lands in the frame.
    center_x: float = Field(default=0.5, ge=0.0, le=1.0)
    center_y: float = Field(default=0.5, ge=0.0, le=1.0)
    #: Fractional (0..1) radius from zenith to the horizon.
    radius: float = Field(default=0.48, ge=0.0, le=1.0)
    #: Corrects for the camera's rotation relative to true north.
    azimuth_offset_deg: float = 0.0
    #: Flip east/west — needed when the lens/mirror mirrors the sky.
    mirror: bool = False


class CameraConfig(StrictModel):
    backend: Literal["mock", "picamera2", "opencv"] = "mock"
    # For "opencv": doubles as the V4L2 device selector — a bare index like
    # "0" opens /dev/video0, anything else is an explicit device path.
    sensor_id: str = "cam0"
    resolution: tuple[int, int] = (4056, 3040)
    lens: LensConfig = Field(default_factory=LensConfig)
    #: White balance — auto (camera-driven AWB) or fixed manual gains.
    wb_auto: bool = True
    wb_red_gain: float = Field(default=1.0, ge=0.1, le=8.0)
    wb_blue_gain: float = Field(default=1.0, ge=0.1, le=8.0)


class LocationConfig(StrictModel):
    lat: float = 50.0755
    lon: float = 14.4378
    elevation_m: float = 200.0
    timezone: str = "Europe/Prague"


#: Image brightness in EV is relative to full scale: 0 EV = 255 ADU, -1 EV =
#: half of it, and so on (`log2(adu / 255)`).
FULL_SCALE_ADU = 255.0


def adu_to_ev(adu: float) -> float:
    return math.log2(max(adu, 0.5) / FULL_SCALE_ADU)


class ExposurePreset(StrictModel):
    """Bounds and tuning for one sky period. Everything the regulator
    compares is in EV — see `control/exposure.py`."""

    exposure_us_min: int = 100
    exposure_us_max: int = 10_000
    gain_min: float = 1.0
    gain_max: float = 4.0
    #: Setpoint: the median of the central brightness circle, in EV below
    #: full scale (0 EV = 255 ADU; -0.77 EV ≈ 150 ADU, -1 EV ≈ 128 ADU).
    target_ev: float = Field(default=-1.0, ge=-8.0, le=0.0)
    #: No correction while the remaining error is within this many EV.
    deadband_ev: float = Field(default=0.07, ge=0.0, le=2.0)
    #: Pixel level counted as saturated in the frame statistics
    #: (`saturated_fraction`), EV below full scale. Not used for regulation.
    saturation_ev: float = Field(default=-0.03, ge=-3.0, le=0.0)
    #: PID gains. P acts on changes of the EV the scene requires, I on the
    #: remaining distance to it; D (on the change of that change) is off by
    #: default — the loop runs as a PI controller.
    kp: float = Field(default=0.3, ge=0.0, le=2.0)
    ki: float = Field(default=0.5, ge=0.0, le=2.0)
    kd: float = Field(default=0.0, ge=0.0, le=2.0)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_units(cls, data: Any) -> Any:
        """Config files from before everything moved to EV: an ADU target
        and a percentage deadband are converted; the per-cycle step limit
        no longer exists. Where both an old and a new key are present (an
        old file patched through the API), the new one wins."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        adu = data.pop("target_mean_adu", None)
        if adu is not None and "target_ev" not in data:
            data["target_ev"] = round(adu_to_ev(float(adu)), 3)
        pct = data.pop("deadband_pct", None)
        if pct is not None and data.get("deadband_ev") is None:
            data["deadband_ev"] = round(math.log2(1.0 + float(pct)), 3)
        if data.get("deadband_ev") is None:
            data.pop("deadband_ev", None)
        saturation = data.pop("saturation_threshold", None)
        if saturation is not None and "saturation_ev" not in data:
            data["saturation_ev"] = round(adu_to_ev(float(saturation)), 3)
        data.pop("max_step_pct", None)
        data.pop("max_step_ev", None)
        return data


def _default_exposure_policy() -> dict[SkyPeriod, ExposurePreset]:
    return {
        "day": ExposurePreset(
            exposure_us_min=100,
            exposure_us_max=10_000,
            gain_min=1.0,
            gain_max=2.0,
            target_ev=-1.0,
        ),
        "civil_twilight": ExposurePreset(
            exposure_us_min=200,
            exposure_us_max=100_000,
            gain_min=1.0,
            gain_max=4.0,
            target_ev=-1.09,
        ),
        "nautical_twilight": ExposurePreset(
            exposure_us_min=1_000,
            exposure_us_max=2_000_000,
            gain_min=1.0,
            gain_max=8.0,
            target_ev=-1.21,
        ),
        "astronomical_twilight": ExposurePreset(
            exposure_us_min=10_000,
            exposure_us_max=8_000_000,
            gain_min=1.0,
            gain_max=12.0,
            target_ev=-1.35,
        ),
        "night": ExposurePreset(
            exposure_us_min=100_000,
            exposure_us_max=15_000_000,
            gain_min=1.0,
            gain_max=16.0,
            target_ev=-1.35,
        ),
    }


class ExposurePolicyConfig(StrictModel):
    presets: dict[SkyPeriod, ExposurePreset] = Field(default_factory=_default_exposure_policy)
    #: Brightness is measured as the median of a circle centred on the
    #: frame, this fraction of the frame's shorter side across — keeps dead
    #: corners and the horizon ring out of the exposure loop.
    brightness_roi_diameter_frac: float = Field(default=0.8, gt=0.0, le=1.0)
    #: How many EV the image median moves per EV of exposure*gain — below 1
    #: because of the ISP's tone curve (~0.45 in the midtones, closer to 1
    #: in the toe). Turns a measured brightness error into the exposure
    #: change that fixes it. 0.7 is the robust middle: simulated against
    #: true responses of 0.4–1.0 and 0–4 frames of control lag it settles in
    #: at most ~20 frames, without oscillating.
    response_gamma: float = Field(default=0.7, gt=0.05, le=1.5)
    #: With the median itself saturated the real error is unknown — correct
    #: by at least this many EV down instead.
    saturated_step_ev: float = Field(default=2.0, gt=0.0, le=8.0)
    #: Cap on a single frame's estimated correction, either way.
    max_correction_ev: float = Field(default=6.0, gt=0.0, le=16.0)

    def preset_for(self, period: SkyPeriod) -> ExposurePreset:
        return self.presets[period]


class StoragePolicyConfig(StrictModel):
    """Per-frame decision: keep a full raw frame, or a thumbnail only."""

    raw_periods: tuple[SkyPeriod, ...] = ("astronomical_twilight", "night")
    thumbnail_max_dim: int = 1024
    #: Live stream (`/api/frame/latest.jpg`, `/ws/stream`) only — the stored
    #: thumbnail is WebP, see `webp_quality`.
    jpeg_quality: int = 85
    webp_quality: int = Field(default=80, ge=1, le=100)
    #: Store raw DNGs with lossless JPEG compression (bit-identical data,
    #: ~30 % smaller). Off = uncompressed, slightly less CPU.
    dng_compress: bool = True
    night_capture_interval_s: float = 30.0
    day_capture_interval_s: float = 60.0
    realtime_stream_fps: float = 2.0


class ProcessingConfig(StrictModel):
    """Where per-frame processing (calibration, stats, thumbnail encoding,
    DNG/WebP writing) runs. "process" is a separate OS process fed through
    shared memory, so it runs in parallel with capture; "inline" runs it on
    the capture thread (tests, debugging). Read at startup only."""

    mode: Literal["process", "inline"] = "process"
    #: Shared-memory frame slots — how many captures may be waiting for or
    #: in processing at once before new ones are dropped (never blocked).
    slots: int = Field(default=3, ge=1, le=8)
    #: A frame still unfinished after this long counts as a hung worker,
    #: which is then killed and restarted.
    job_timeout_s: float = Field(default=120.0, gt=0.0)


class CaptureProgramConfig(StrictModel):
    """Which capture program runs (see caelum.capture_runtime).

    A user program runs from its archived version `active_sha256` — editing
    the file changes nothing until it is activated again."""

    active_program: str = "default.py"
    #: The archived version of a user program; None for a built-in.
    active_sha256: str | None = None
    #: Lets admins create, edit, test and activate programs through the API.
    #: Programs are arbitrary Python running with the service's rights.
    editing_enabled: bool = True

    #: Parameters per program, by name without `.py` — `ctx.params`.
    params: dict[str, dict] = Field(default_factory=dict)
    #: After this many failed runs in a row a user program is replaced by the
    #: built-in default until it is activated again.
    max_consecutive_failures: int = Field(default=3, ge=1)


class RetentionConfig(StrictModel):
    """Local-disk rotation only — the remote upload target is never rotated."""

    max_age_days: int = 14
    min_free_space_mb: int = 1024
    sweep_interval_s: float = 3600.0


class UploadConfig(StrictModel):
    enabled: bool = False
    #: "rsync" pushes over SSH (or to a local path) with delta transfer;
    #: "scp" pushes over SSH where only scp/sftp is available (whole files,
    #: changed ones found from a remote listing); "s3" pushes to an
    #: S3-compatible object store — see upload/transport_*.py.
    transport: Literal["rsync", "scp", "s3"] = "rsync"
    remote_host: str = ""
    remote_user: str = ""
    remote_base_path: str = "/var/www/allsky-data"
    ssh_key_path: str = "/etc/caelum/upload_key"
    #: SSH port for the rsync and scp transports.
    ssh_port: int = Field(default=22, ge=1, le=65535)
    #: Upload bandwidth cap in KiB/s for rsync and scp; 0 = unlimited.
    bandwidth_limit_kbps: int = Field(default=0, ge=0)
    # S3 transport. Like AuthConfig, this deliberately holds no secrets —
    # it's exposed through /api/config. Keys come from the standard AWS
    # credential chain instead: `s3_profile` names a profile in
    # ~/.aws/credentials, or leave it empty and set AWS_ACCESS_KEY_ID /
    # AWS_SECRET_ACCESS_KEY in .env.
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    #: Key prefix inside the bucket — S3's counterpart of `remote_base_path`.
    s3_prefix: str = ""
    s3_profile: str = ""
    #: Canned ACL for every uploaded object, e.g. "public-read" when the
    #: remote-web app reads straight from the bucket. Empty: bucket default.
    s3_acl: str = ""
    camera_slug: str = "cam0"
    camera_name: str = "Caelum Camera"
    thumbnail_interval_s: float = 60.0
    reconcile_interval_s: float = 1800.0


class RedisConfig(StrictModel):
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    key_prefix: str = "caelum"


class AuthConfig(StrictModel):
    """Access-control *policy* only.

    Deliberately holds no secrets: accounts, password hashes and the session
    signing key live in `<config_dir>/auth.json` (see `auth/store.py`), which
    is never exposed through `/api/config`. That endpoint is rendered as an
    editable JSON tree in the web UI, so anything placed here is effectively
    public to every admin — policy flags are fine, credentials are not.
    """

    enabled: bool = True
    # Who may see the live preview (status, sky state, latest frame,
    # /ws/stream) — as opposed to the control surfaces, which are always
    # admin-only. "public" leaves the preview open to anyone who can reach
    # the port; "viewer" puts it behind any account; "admin" hides it from
    # viewer accounts entirely.
    preview_access: Literal["public", "viewer", "admin"] = "viewer"
    session_ttl_hours: int = 720
    # The web terminal is a real shell running as the caelum process user.
    # Left on for the usual single-operator LAN deployment, but this is the
    # one switch to flip on anything reachable from an untrusted network.
    terminal_enabled: bool = True


class DocsConfig(StrictModel):
    """Where the public documentation site is published.

    The web UI deep-links into it (`DocsLink`), so it has to be configurable
    per deployment rather than hardcoded in the frontend bundle.
    """

    base_url: str = "https://caelum.astrometers.eu"


class PluginConfig(StrictModel):
    """One entry per plugin id under AppConfig.plugins.

    `settings` is intentionally an open dict — each plugin validates its own
    shape against the `config_schema` it declares (see plugins/base.py);
    the app-level config store treats it as an opaque blob.
    """

    enabled: bool = True
    order: int = 100
    settings: dict = Field(default_factory=dict)


def _default_plugins() -> dict[str, PluginConfig]:
    """The built-in derivative workers, seeded so they show up on the
    Plugins page of a fresh install rather than appearing only once someone
    knows to type their ids in by hand. They are loaded through the same
    `PluginLoader` path as third-party plugins, so turning one off or
    reordering it here genuinely takes effect.

    `settings: {}` means "use the plugin's own declared defaults" — see each
    worker's `config_schema`.
    """
    return {
        # Keogram first: it only reads frames, so it cannot be affected by
        # anything a later plugin does.
        "keogram": PluginConfig(enabled=True, order=10),
        "meteor_detection": PluginConfig(enabled=True, order=20),
        # Disabled by default: both require the admin to configure them
        # (elements to draw, a calibrated projection) before they should
        # show anything — an empty mask or a fake telescope marker
        # appearing unasked would be a bad default.
        "overlay": PluginConfig(
            enabled=False,
            order=30,
            settings={"templates": [{"name": "Default", "elements": []}], "active_template": "Default"},
        ),
        "telescope_position": PluginConfig(enabled=False, order=40),
        "timelapse": PluginConfig(enabled=False, order=50),
    }


class AppConfig(StrictModel):
    config_version: int = 1
    camera: CameraConfig = Field(default_factory=CameraConfig)
    location: LocationConfig = Field(default_factory=LocationConfig)
    exposure_policy: ExposurePolicyConfig = Field(default_factory=ExposurePolicyConfig)
    storage_policy: StoragePolicyConfig = Field(default_factory=StoragePolicyConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    capture: CaptureProgramConfig = Field(default_factory=CaptureProgramConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    docs: DocsConfig = Field(default_factory=DocsConfig)
    plugins: dict[str, PluginConfig] = Field(default_factory=_default_plugins)
