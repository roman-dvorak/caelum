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


# Where the built local-web UI is found, in order of preference after
# CAELUM_WEB_DIR: bundled into the installed package by
# scripts/build-release.sh, else the source checkout's own build output.
_PACKAGED_WEB_DIR = Path(__file__).resolve().parent / "webui"
_DEV_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "apps" / "local-web" / "dist"


def _default_web_dir() -> Path:
    if (_PACKAGED_WEB_DIR / "index.html").is_file():
        return _PACKAGED_WEB_DIR
    return _DEV_WEB_DIST


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
    # Built local-web app (its `dist/`), served at `/`. None, or a
    # directory that doesn't exist, means API-only.
    web_dir: Path | None = None

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
        web_dir=_env_path("CAELUM_WEB_DIR", str(_default_web_dir())),
    )
