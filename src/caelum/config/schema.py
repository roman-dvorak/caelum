"""Pydantic models for the runtime AppConfig.

This is the single schema kept in sync between disk and Redis by
`config/manager.py`. `config/default.json` is a JSON dump of `AppConfig()`'s
defaults (see `scripts/dev_run.sh` / tests for how it's (re)generated).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class CameraConfig(StrictModel):
    backend: Literal["mock", "picamera2", "opencv"] = "mock"
    # For "opencv": doubles as the V4L2 device selector — a bare index like
    # "0" opens /dev/video0, anything else is an explicit device path.
    sensor_id: str = "cam0"
    resolution: tuple[int, int] = (4056, 3040)


class LocationConfig(StrictModel):
    lat: float = 50.0755
    lon: float = 14.4378
    elevation_m: float = 200.0
    timezone: str = "Europe/Prague"


class ExposurePreset(StrictModel):
    exposure_us_min: int = 100
    exposure_us_max: int = 10_000
    gain_min: float = 1.0
    gain_max: float = 4.0
    target_mean_adu: float = 128.0
    saturation_threshold: float = 250.0


def _default_exposure_policy() -> dict[SkyPeriod, ExposurePreset]:
    return {
        "day": ExposurePreset(
            exposure_us_min=100,
            exposure_us_max=10_000,
            gain_min=1.0,
            gain_max=2.0,
            target_mean_adu=128,
            saturation_threshold=250,
        ),
        "civil_twilight": ExposurePreset(
            exposure_us_min=200,
            exposure_us_max=100_000,
            gain_min=1.0,
            gain_max=4.0,
            target_mean_adu=120,
            saturation_threshold=250,
        ),
        "nautical_twilight": ExposurePreset(
            exposure_us_min=1_000,
            exposure_us_max=2_000_000,
            gain_min=1.0,
            gain_max=8.0,
            target_mean_adu=110,
            saturation_threshold=250,
        ),
        "astronomical_twilight": ExposurePreset(
            exposure_us_min=10_000,
            exposure_us_max=8_000_000,
            gain_min=1.0,
            gain_max=12.0,
            target_mean_adu=100,
            saturation_threshold=250,
        ),
        "night": ExposurePreset(
            exposure_us_min=100_000,
            exposure_us_max=15_000_000,
            gain_min=1.0,
            gain_max=16.0,
            target_mean_adu=100,
            saturation_threshold=250,
        ),
    }


class ExposurePolicyConfig(StrictModel):
    presets: dict[SkyPeriod, ExposurePreset] = Field(default_factory=_default_exposure_policy)

    def preset_for(self, period: SkyPeriod) -> ExposurePreset:
        return self.presets[period]


class StoragePolicyConfig(StrictModel):
    """Per-frame decision: keep a full raw frame, or a thumbnail only."""

    raw_periods: tuple[SkyPeriod, ...] = ("astronomical_twilight", "night")
    thumbnail_max_dim: int = 1024
    jpeg_quality: int = 85
    night_capture_interval_s: float = 30.0
    day_capture_interval_s: float = 60.0
    realtime_stream_fps: float = 2.0


class RetentionConfig(StrictModel):
    """Local-disk rotation only — the remote upload target is never rotated."""

    max_age_days: int = 14
    min_free_space_mb: int = 1024
    sweep_interval_s: float = 3600.0


class UploadConfig(StrictModel):
    enabled: bool = False
    remote_host: str = ""
    remote_user: str = ""
    remote_base_path: str = "/var/www/allsky-data"
    ssh_key_path: str = "/etc/caelum/upload_key"
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
    """The two built-in derivative workers, seeded so they show up on the
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
    }


class AppConfig(StrictModel):
    config_version: int = 1
    camera: CameraConfig = Field(default_factory=CameraConfig)
    location: LocationConfig = Field(default_factory=LocationConfig)
    exposure_policy: ExposurePolicyConfig = Field(default_factory=ExposurePolicyConfig)
    storage_policy: StoragePolicyConfig = Field(default_factory=StoragePolicyConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    docs: DocsConfig = Field(default_factory=DocsConfig)
    plugins: dict[str, PluginConfig] = Field(default_factory=_default_plugins)
