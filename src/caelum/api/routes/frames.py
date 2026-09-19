"""Recording manager — the capture archive viewed by date and capture time.

`/api/files` can already reach all of this as raw directories; this router
exists because the archive is not really a tree, it is a time series that
happens to be stored as one. A single capture is up to three files in three
different directories (`thumbnails/<date>/HHMMSS.jpg`, its `.json` sidecar,
and `raw/<date>/HHMMSS.fits`), and an operator wants to see and delete them
as one thing, not as three.

Listings are built from directory entries alone — no sidecar is opened. A
busy night is a few thousand frames, and the UI fetches the metadata it
needs per visible tile, exactly as the remote gallery does.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from caelum.api.deps import get_settings
from caelum.api.schemas import (
    DeleteFramesRequest,
    FileEntry,
    FrameDateSummary,
    FrameEntry,
    FrameListResponse,
)
from caelum.api.security import Principal, require_admin, require_preview
from caelum.settings import Settings
from caelum.storage import browse

logger = logging.getLogger(__name__)

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(date: str) -> str:
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail=f"Invalid date {date!r}, expected YYYY-MM-DD")
    return date


def _date_dirs(data_dir: Path, subdir: str) -> list[Path]:
    root = data_dir / subdir
    if not root.is_dir():
        return []
    return [child for child in root.iterdir() if child.is_dir() and _DATE_RE.match(child.name)]


def _count_and_size(directory: Path, suffixes: tuple[str, ...]) -> tuple[int, int]:
    if not directory.is_dir():
        return 0, 0
    count = 0
    total = 0
    for child in directory.rglob("*"):
        if not child.is_file():
            continue
        total += child.stat().st_size
        if child.suffix.lower() in suffixes:
            count += 1
    return count, total


@router.get("/frames/dates", response_model=list[FrameDateSummary])
def list_dates(
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
) -> list[FrameDateSummary]:
    data_dir = settings.data_dir
    dates = {d.name for subdir in ("thumbnails", "raw", "derivatives") for d in _date_dirs(data_dir, subdir)}

    summaries = []
    for date in dates:
        thumbnails, thumb_bytes = _count_and_size(data_dir / "thumbnails" / date, (".jpg", ".jpeg"))
        raws, raw_bytes = _count_and_size(data_dir / "raw" / date, (".fits",))
        derivatives, derivative_bytes = _count_and_size(
            data_dir / "derivatives" / date, (".png", ".jpg", ".jpeg")
        )
        summaries.append(
            FrameDateSummary(
                date=date,
                thumbnails=thumbnails,
                raws=raws,
                derivatives=derivatives,
                total_bytes=thumb_bytes + raw_bytes + derivative_bytes,
            )
        )
    summaries.sort(key=lambda s: s.date, reverse=True)
    return summaries


@router.get("/frames", response_model=FrameListResponse)
def list_frames(
    date: str = Query(..., description="Capture date, YYYY-MM-DD"),
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
) -> FrameListResponse:
    _validate_date(date)
    data_dir = settings.data_dir

    # Keyed by capture time so the thumbnail, its sidecar and the raw frame
    # collapse back into the single capture they came from.
    by_time: dict[str, dict] = {}

    def slot(time_token: str) -> dict:
        return by_time.setdefault(
            time_token,
            {"time": time_token, "thumbnail": None, "raw": None, "metadata": None, "total_bytes": 0},
        )

    thumbnails_dir = data_dir / "thumbnails" / date
    if thumbnails_dir.is_dir():
        for child in thumbnails_dir.iterdir():
            if not child.is_file():
                continue
            entry = slot(child.stem)
            entry["total_bytes"] += child.stat().st_size
            key = "metadata" if child.suffix.lower() == ".json" else "thumbnail"
            entry[key] = browse.relative_to(data_dir, child)

    raw_dir = data_dir / "raw" / date
    if raw_dir.is_dir():
        for child in raw_dir.iterdir():
            if child.is_file() and child.suffix.lower() == ".fits":
                entry = slot(child.stem)
                entry["total_bytes"] += child.stat().st_size
                entry["raw"] = browse.relative_to(data_dir, child)

    frames = [
        FrameEntry(captured_at=_captured_at(date, entry["time"]), **entry)
        for entry in sorted(by_time.values(), key=lambda e: e["time"])
    ]

    derivatives_dir = data_dir / "derivatives" / date
    derivatives = (
        [
            FileEntry(**browse.describe(data_dir, child))
            for child in sorted(derivatives_dir.rglob("*"))
            if child.is_file()
        ]
        if derivatives_dir.is_dir()
        else []
    )

    return FrameListResponse(date=date, frames=frames, derivatives=derivatives)


def _captured_at(date: str, time_token: str) -> str:
    try:
        naive = datetime.strptime(f"{date}{time_token[:6]}", "%Y-%m-%d%H%M%S")
    except ValueError:
        return f"{date}T00:00:00+00:00"
    return naive.replace(tzinfo=UTC).isoformat()


@router.delete("/frames")
def delete_frames(
    body: DeleteFramesRequest,
    _: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Delete whole capture dates, or individual captures within one.

    An empty `times` means the entire date — that is the bulk case the UI
    uses to reclaim a night's worth of raw frames in one action.
    """
    _validate_date(body.date)
    data_dir = settings.data_dir
    removed = 0

    for kind in body.kinds:
        directory = data_dir / kind / body.date
        if not directory.is_dir():
            continue

        if not body.times:
            removed += sum(1 for child in directory.rglob("*") if child.is_file())
            shutil.rmtree(directory)
            continue

        for time_token in body.times:
            # Only ever matches inside `directory`, and glob never escapes it;
            # a time token containing separators simply matches nothing.
            for child in directory.glob(f"{time_token}.*"):
                if child.is_file():
                    child.unlink()
                    removed += 1

    logger.info("Deleted %d file(s) for %s via the recordings manager", removed, body.date)
    return {"date": body.date, "files_removed": removed}
