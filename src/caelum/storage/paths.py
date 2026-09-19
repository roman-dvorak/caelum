"""Date-based directory convention shared by the storage writer, retention
sweeper, and uploader: `<data_dir>/<kind>/<YYYY-MM-DD>/<HHMMSS>[...].<ext>`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

MANAGED_SUBDIRS = ("raw", "thumbnails", "derivatives")


def raw_path(data_dir: Path, when: datetime) -> Path:
    return data_dir / "raw" / when.date().isoformat() / f"{when.strftime('%H%M%S')}.fits"


def thumbnail_path(data_dir: Path, when: datetime) -> Path:
    return data_dir / "thumbnails" / when.date().isoformat() / f"{when.strftime('%H%M%S')}.jpg"


def sidecar_path(image_path: Path) -> Path:
    return image_path.with_suffix(".json")


def capture_time_of(path: Path) -> datetime | None:
    """Best-effort reconstruction of a managed file's capture time from its
    `<date>/<HHMMSS...>` location, used by retention to sort/age files
    without needing to open and parse each one."""
    try:
        time_token = path.stem.split("_", 1)[0]
        naive = datetime.strptime(f"{path.parent.name}{time_token}", "%Y-%m-%d%H%M%S")
        return naive.replace(tzinfo=UTC)
    except (ValueError, IndexError):
        return None
