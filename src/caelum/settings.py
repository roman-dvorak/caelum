"""Bootstrap settings read once from the environment at process start.

This is deliberately separate from the runtime `AppConfig` (see
`config/schema.py`): these are the handful of things the process needs
*before* it can even open the config store (where to find it, which port to
bind) and are not expected to change without a restart.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    config_dir: Path
    data_dir: Path
    http_host: str
    http_port: int
    redis_url: str
    camera_backend_override: str | None
    log_level: str
    #: Extra browser origins allowed to call the API cross-site — e.g. the
    #: static caelum-viewer on GitHub Pages reading frames straight off the
    #: camera. Comma-separated in CAELUM_CORS_ORIGINS.
    cors_origins: tuple[str, ...] = ()
    #: User capture programs (CAELUM_CAPTURE_PROGRAMS_DIR); None means
    #: `<data_dir>/capture-programs`.
    capture_programs_dir_override: Path | None = None

    @property
    def capture_programs_dir(self) -> Path:
        return self.capture_programs_dir_override or self.data_dir / "capture-programs"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def default_config_file(self) -> Path:
        return self.config_dir / "default.json"


def load_settings() -> Settings:
    return Settings(
        config_dir=_env_path("CAELUM_CONFIG_DIR", "./config"),
        data_dir=_env_path("CAELUM_DATA_DIR", "./data"),
        http_host=os.environ.get("CAELUM_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.environ.get("CAELUM_HTTP_PORT", "8000")),
        redis_url=os.environ.get("CAELUM_REDIS_URL", "redis://127.0.0.1:6379/0"),
        # Config (camera.backend) is authoritative; this only overrides it
        # when explicitly set — a dev/CI convenience, never a silent
        # auto-detect on real hardware. Unset by default.
        camera_backend_override=os.environ.get("CAELUM_CAMERA_BACKEND"),
        log_level=os.environ.get("CAELUM_LOG_LEVEL", "INFO"),
        capture_programs_dir_override=(
            _env_path("CAELUM_CAPTURE_PROGRAMS_DIR", "") if os.environ.get("CAELUM_CAPTURE_PROGRAMS_DIR") else None
        ),
        cors_origins=tuple(
            o.strip().rstrip("/")
            for o in os.environ.get("CAELUM_CORS_ORIGINS", "https://roman-dvorak.github.io").split(",")
            if o.strip()
        ),
    )
