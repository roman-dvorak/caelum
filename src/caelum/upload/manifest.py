"""Builds the JSON manifests the read-only remote-web app consumes off the
Apache static root — purely static files, so the remote host needs no
backend at all. Per-camera `manifest.json` and each date's `index.json` are
written locally (they ride along with the next rsync push like any other
file); the shared top-level `cameras.json` needs cross-camera coordination
and is handled separately in uploader.py.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_YEAR_RE = re.compile(r"^\d{4}$")
_MONTH_DAY_RE = re.compile(r"^\d{2}$")


def _dated_files(data_dir: Path, subdir: str) -> dict[str, list[Path]]:
    """Walks `<subdir>/YYYY/MM/DD/` (see storage/paths.py) and returns each
    date's files keyed by its `YYYY-MM-DD` label — the manifest's public,
    on-disk-layout-independent identifier."""
    base = data_dir / subdir
    by_date: dict[str, list[Path]] = {}
    if not base.exists():
        return by_date
    for year_dir in sorted(base.iterdir()):
        if not (year_dir.is_dir() and _YEAR_RE.match(year_dir.name)):
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not (month_dir.is_dir() and _MONTH_DAY_RE.match(month_dir.name)):
                continue
            for day_dir in sorted(month_dir.iterdir()):
                if not (day_dir.is_dir() and _MONTH_DAY_RE.match(day_dir.name)):
                    continue
                files = sorted(
                    p for p in day_dir.glob("*")
                    # Hidden files are in-progress atomic writes (`.<name>.tmp`).
                    if p.is_file() and p.suffix != ".json" and not p.name.startswith(".")
                )
                if files:
                    by_date[f"{year_dir.name}-{month_dir.name}-{day_dir.name}"] = files
    return by_date


def write_local_manifests(
    data_dir: Path, camera_slug: str, camera_name: str, location: dict[str, Any]
) -> dict[str, Any]:
    """Regenerate `<data_dir>/manifest.json` and every date's
    `thumbnails/<YYYY>/<MM>/<DD>/index.json`. Returns the built camera
    manifest dict.

    `date` (the dict key from `_dated_files`) is the public `YYYY-MM-DD`
    identifier used in the JSON; `date_path` is that same date translated to
    the actual nested on-disk/URL layout — every path written into the
    manifest or to disk uses `date_path`, never `date` directly.
    """
    thumbs_by_date = _dated_files(data_dir, "thumbnails")
    raws_by_date = _dated_files(data_dir, "raw")

    dates = []
    for date, thumb_files in sorted(thumbs_by_date.items()):
        date_path = date.replace("-", "/")
        raw_files = raws_by_date.get(date, [])
        dates.append(
            {
                "date": date,
                "thumbnail_count": len(thumb_files),
                "has_raw": bool(raw_files),
                "raw_count": len(raw_files),
                "latest_thumbnail": f"thumbnails/{date_path}/{thumb_files[-1].name}",
            }
        )
        index = {
            "date": date,
            "images": [
                {
                    "time": path.stem,
                    "thumbnail": f"thumbnails/{date_path}/{path.name}",
                    "metadata": f"thumbnails/{date_path}/{path.stem}.json",
                }
                for path in thumb_files
            ],
        }
        (data_dir / "thumbnails" / date_path / "index.json").write_text(json.dumps(index, indent=2))

    camera_manifest = {
        "version": 1,
        "slug": camera_slug,
        "name": camera_name,
        "location": location,
        "dates": dates,
    }
    (data_dir / "manifest.json").write_text(json.dumps(camera_manifest, indent=2))
    return camera_manifest


def merge_cameras_index(
    existing: dict[str, Any] | None,
    camera_slug: str,
    camera_name: str,
    camera_manifest: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Fetch-merge-push pattern: only this camera's own entry is touched, so
    concurrently-uploading cameras sharing the same remote host don't
    clobber each other's entries (each camera re-asserts its own entry every
    cycle, so a lost race self-heals on the next one)."""
    cameras = {c["slug"]: c for c in (existing or {}).get("cameras", [])}
    latest_thumbnail = camera_manifest["dates"][-1]["latest_thumbnail"] if camera_manifest["dates"] else None
    cameras[camera_slug] = {
        "slug": camera_slug,
        "name": camera_name,
        "manifest": f"{camera_slug}/manifest.json",
        "latest_thumbnail": f"{camera_slug}/{latest_thumbnail}" if latest_thumbnail else None,
    }
    return {
        "version": 1,
        "updated_at": now.isoformat(),
        "cameras": sorted(cameras.values(), key=lambda c: c["slug"]),
    }
