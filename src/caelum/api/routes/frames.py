"""Recording manager — the capture archive viewed by date and capture time.

`/api/files` can already reach all of this as raw directories; this router
exists because the archive is not really a tree, it is a time series that
happens to be stored as one. A single capture is up to three files under
`<kind>/<YYYY>/<MM>/<DD>/<YYYYMMDD-HHMMSS>.<ext>` (thumbnail, its `.json`
sidecar, raw FITS — see storage/paths.py for the convention), and an
operator wants to see and delete them as one thing, not as three.

Listings are built from directory entries alone — no sidecar is opened. A
busy night is a few thousand frames, and the UI fetches the metadata it
needs per visible tile, exactly as the remote gallery does.

Two ways to group frames into a "day", both available side by side:

- **date** (`?date=`) — the UTC calendar date a file is filed under (every
  timestamp in this app, including every filename, is UTC — see
  storage/paths.py). Matches the on-disk layout and what the remote
  gallery/uploader use, but a real observing session almost always crosses
  UTC midnight partway through the night, so it silently splits one night's
  data across two "dates".
- **night** (`?night=`) — an *observation night*, sunrise to sunrise, using
  `SkyStateCalculator.next_sunrise`. A session that runs from dusk through
  dawn stays one entry, labelled by the *local* calendar date (site
  timezone) the preceding sunrise fell on — the date a human would actually
  call "last night". This is the one worth defaulting the UI to.

Both modes take and return "YYYY-MM-DD" strings — a stable, human-facing
identifier independent of the nested `YYYY/MM/DD` disk layout underneath
(`storage/paths.date_dir_for_iso` is the only place that translates between
the two). Every `captured_at`/timestamp in every response is UTC.
"""

from __future__ import annotations

import bisect
import logging
import re
import shutil
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query

from caelum.api.deps import get_config_manager, get_settings, get_skystate_calculator
from caelum.api.schemas import (
    DeleteFramesRequest,
    DerivativeEntry,
    DerivativeKindSummary,
    DerivativeListResponse,
    FrameDateSummary,
    FrameEntry,
    FrameListResponse,
    ObservationNightSummary,
)
from caelum.api.security import Principal, require_admin, require_preview
from caelum.config.manager import ConfigManager
from caelum.control.skystate import SkyStateCalculator
from caelum.derivatives.pool import thumbnail_path_for
from caelum.settings import Settings
from caelum.storage import browse, paths

logger = logging.getLogger(__name__)

router = APIRouter()

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DEFAULT_PAGE_SIZE = 60
_MAX_PAGE_SIZE = 500


def _validate_iso_date(value: str) -> str:
    if not _ISO_DATE_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid date {value!r}, expected YYYY-MM-DD")
    return value


def _site_timezone(config_manager: ConfigManager) -> ZoneInfo:
    name = config_manager.current.location.timezone
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Configured location.timezone {name!r} is invalid") from exc


def _existing_dates(data_dir: Path, subdir: str) -> set[str]:
    """Every `YYYY-MM-DD` that has at least one file under
    `<data_dir>/<subdir>/YYYY/MM/DD/` — walks the three nesting levels
    directly rather than globbing, since a bare `*/*/*.` glob can't tell a
    real date directory from someone's stray folder."""
    root = data_dir / subdir
    if not root.is_dir():
        return set()
    found = set()
    for year_dir in root.iterdir():
        if not (year_dir.is_dir() and re.fullmatch(r"\d{4}", year_dir.name)):
            continue
        for month_dir in year_dir.iterdir():
            if not (month_dir.is_dir() and re.fullmatch(r"\d{2}", month_dir.name)):
                continue
            for day_dir in month_dir.iterdir():
                if day_dir.is_dir() and re.fullmatch(r"\d{2}", day_dir.name) and any(day_dir.iterdir()):
                    found.add(f"{year_dir.name}-{month_dir.name}-{day_dir.name}")
    return found


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
    dates = _existing_dates(data_dir, "thumbnails") | _existing_dates(data_dir, "raw") | _existing_dates(
        data_dir, "derivatives"
    )

    summaries = []
    for iso_date in dates:
        thumbnails, thumb_bytes = _count_and_size(
            paths.date_dir_for_iso(data_dir, "thumbnails", iso_date), paths.THUMBNAIL_SUFFIXES
        )
        raws, raw_bytes = _count_and_size(paths.date_dir_for_iso(data_dir, "raw", iso_date), paths.RAW_SUFFIXES)
        derivatives, derivative_bytes = _count_and_size(
            paths.date_dir_for_iso(data_dir, "derivatives", iso_date), (".png", ".jpg", ".jpeg", ".webp")
        )
        summaries.append(
            FrameDateSummary(
                date=iso_date,
                thumbnails=thumbnails,
                raws=raws,
                derivatives=derivatives,
                total_bytes=thumb_bytes + raw_bytes + derivative_bytes,
            )
        )
    summaries.sort(key=lambda s: s.date, reverse=True)
    return summaries


@router.get("/frames/nights", response_model=list[ObservationNightSummary])
def list_nights(
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
    config_manager: ConfigManager = Depends(get_config_manager),
    calculator: SkyStateCalculator = Depends(get_skystate_calculator),
) -> list[ObservationNightSummary]:
    data_dir = settings.data_dir
    tz = _site_timezone(config_manager)

    utc_dates = sorted(
        _existing_dates(data_dir, "thumbnails") | _existing_dates(data_dir, "raw") | _existing_dates(
            data_dir, "derivatives"
        )
    )
    if not utc_dates:
        return []

    sunrises = _sunrise_series(calculator, utc_dates)
    buckets: dict[str, dict[str, int]] = {}

    for subdir, suffixes, key in (
        ("thumbnails", paths.THUMBNAIL_SUFFIXES, "thumbnails"),
        ("raw", paths.RAW_SUFFIXES, "raws"),
        ("derivatives", None, "derivatives"),  # every file in here counts
    ):
        for iso_date in utc_dates:
            directory = paths.date_dir_for_iso(data_dir, subdir, iso_date)
            if not directory.is_dir():
                continue
            for child in directory.rglob("*"):
                if not child.is_file():
                    continue
                captured = paths.capture_time_of(child) or _mtime(child)
                night_label = _night_label(sunrises, captured, tz)
                bucket = buckets.setdefault(
                    night_label, {"thumbnails": 0, "raws": 0, "derivatives": 0, "total_bytes": 0}
                )
                bucket["total_bytes"] += child.stat().st_size
                if suffixes is None:
                    bucket["derivatives"] += 1
                elif child.suffix.lower() in suffixes:
                    bucket[key] += 1

    summaries = [ObservationNightSummary(date=label, **counts) for label, counts in buckets.items()]
    summaries.sort(key=lambda s: s.date, reverse=True)
    return summaries


def _mtime(path: Path) -> datetime:
    """Fallback for a file whose name doesn't parse as a capture timestamp
    — good enough for sorting into a night bucket, which only needs to be
    right to the minute, not the second."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _sunrise_series(calculator: SkyStateCalculator, utc_dates: Iterable[str]) -> list[datetime]:
    """One sunrise per calendar day spanning the dataset, with a day of
    margin either side so files near the first/last UTC date still land in
    a correctly-bounded bucket."""
    sorted_dates = sorted(utc_dates)
    start = date.fromisoformat(sorted_dates[0]) - timedelta(days=1)
    stop = date.fromisoformat(sorted_dates[-1]) + timedelta(days=2)

    sunrises: list[datetime] = []
    cursor = datetime(start.year, start.month, start.day, tzinfo=UTC)
    stop_at = datetime(stop.year, stop.month, stop.day, tzinfo=UTC)
    while cursor < stop_at:
        sunrise = calculator.next_sunrise(cursor)
        sunrises.append(sunrise)
        cursor = sunrise + timedelta(minutes=1)
    return sunrises


def _night_label(sunrises: list[datetime], when: datetime, tz: ZoneInfo) -> str:
    """Local calendar date of the most recent sunrise at or before `when` —
    the "night of" label a human would use."""
    idx = max(bisect.bisect_right(sunrises, when) - 1, 0)
    return sunrises[idx].astimezone(tz).date().isoformat()


def _night_window(calculator: SkyStateCalculator, local_date: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    year, month, day_ = (int(part) for part in local_date.split("-"))
    local_midnight_utc = datetime(year, month, day_, tzinfo=tz).astimezone(UTC)
    start = calculator.next_sunrise(local_midnight_utc)
    end = calculator.next_sunrise(start + timedelta(minutes=1))
    return start, end


def _utc_dates_between(start: datetime, end: datetime) -> list[str]:
    d = start.date()
    dates = []
    while d <= end.date():
        dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


def _resolve_period(
    date: str | None,
    night: str | None,
    config_manager: ConfigManager,
    calculator: SkyStateCalculator,
) -> tuple[list[str], tuple[datetime, datetime] | None, str]:
    """Shared by every endpoint that takes `?date=` xor `?night=`: resolves
    either into the same `(utc_dates, window, label)` shape `list_frames`
    has always used, so the derivative endpoints below group frames into a
    "day" exactly the same way the capture listing does."""
    if (date is None) == (night is None):
        raise HTTPException(status_code=400, detail="Pass exactly one of `date` or `night`")
    if date is not None:
        _validate_iso_date(date)
        return [date], None, date
    _validate_iso_date(night)
    tz = _site_timezone(config_manager)
    window = _night_window(calculator, night, tz)
    return _utc_dates_between(*window), window, night


def _gather_frames(data_dir: Path, utc_dates: list[str], window: tuple[datetime, datetime] | None) -> list[dict]:
    """Collects capture entries from the given UTC date directories,
    optionally restricted to a `[start, end)` UTC window (night mode) —
    date mode passes `window=None` and gets everything under that one date.
    Keyed by the full `YYYYMMDD-HHMMSS` stem, which is self-sufficient (see
    module docstring), not by date + a bare time token."""
    by_stem: dict[str, dict] = {}

    for iso_date in utc_dates:
        thumbnails_dir = paths.date_dir_for_iso(data_dir, "thumbnails", iso_date)
        if thumbnails_dir.is_dir():
            for child in thumbnails_dir.iterdir():
                if not child.is_file():
                    continue
                captured = paths.capture_time_of(child)
                if captured is None or (window and not (window[0] <= captured < window[1])):
                    continue
                entry = by_stem.setdefault(
                    child.stem,
                    {"time": child.stem, "captured_at": captured, "thumbnail": None, "raw": None,
                     "metadata": None, "total_bytes": 0},
                )
                entry["total_bytes"] += child.stat().st_size
                key = "metadata" if child.suffix.lower() == ".json" else "thumbnail"
                entry[key] = browse.relative_to(data_dir, child)

        raw_dir = paths.date_dir_for_iso(data_dir, "raw", iso_date)
        if raw_dir.is_dir():
            for child in raw_dir.iterdir():
                if not (child.is_file() and child.suffix.lower() in paths.RAW_SUFFIXES):
                    continue
                captured = paths.capture_time_of(child)
                if captured is None or (window and not (window[0] <= captured < window[1])):
                    continue
                entry = by_stem.setdefault(
                    child.stem,
                    {"time": child.stem, "captured_at": captured, "thumbnail": None, "raw": None,
                     "metadata": None, "total_bytes": 0},
                )
                entry["total_bytes"] += child.stat().st_size
                entry["raw"] = browse.relative_to(data_dir, child)

    return sorted(by_stem.values(), key=lambda e: e["captured_at"])


@router.get("/frames", response_model=FrameListResponse)
def list_frames(
    date: str | None = Query(None, description="UTC calendar date, YYYY-MM-DD"),
    night: str | None = Query(None, description="Observation night (local date the night started), YYYY-MM-DD"),
    limit: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
    config_manager: ConfigManager = Depends(get_config_manager),
    calculator: SkyStateCalculator = Depends(get_skystate_calculator),
) -> FrameListResponse:
    utc_dates, window, label = _resolve_period(date, night, config_manager, calculator)
    data_dir = settings.data_dir

    entries = _gather_frames(data_dir, utc_dates, window)
    total = len(entries)
    page = entries[offset : offset + limit]

    frames = [
        FrameEntry(
            time=e["time"],
            captured_at=e["captured_at"].isoformat(),
            thumbnail=e["thumbnail"],
            raw=e["raw"],
            metadata=e["metadata"],
            total_bytes=e["total_bytes"],
        )
        for e in page
    ]

    return FrameListResponse(
        date=label,
        frames=frames,
        total_frames=total,
        limit=limit,
        offset=offset,
        utc_dates=utc_dates,
    )


@router.get("/frames/derivative-kinds", response_model=list[DerivativeKindSummary])
def list_derivative_kinds(
    date: str | None = Query(None, description="UTC calendar date, YYYY-MM-DD"),
    night: str | None = Query(None, description="Observation night (local date the night started), YYYY-MM-DD"),
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
    config_manager: ConfigManager = Depends(get_config_manager),
    calculator: SkyStateCalculator = Depends(get_skystate_calculator),
) -> list[DerivativeKindSummary]:
    """What derivative kinds (keogram, keogram_live, meteor_crop, ...) exist
    for this period, and how many of each — drives the sub-tab bar in the
    Recordings UI's Derivatives view. Each kind is its own subdirectory
    (see `derivatives/pool.py::_derivative_dir`), so this is a cheap
    top-level directory listing, not a walk of every file."""
    utc_dates, window, _label = _resolve_period(date, night, config_manager, calculator)
    data_dir = settings.data_dir

    counts: dict[str, int] = {}
    for iso_date in utc_dates:
        derivatives_dir = paths.date_dir_for_iso(data_dir, "derivatives", iso_date)
        if not derivatives_dir.is_dir():
            continue
        for kind_dir in derivatives_dir.iterdir():
            if not kind_dir.is_dir():
                continue
            count = sum(
                1
                for child in kind_dir.iterdir()
                if child.is_file()
                and not child.stem.endswith("_thumb")
                and _within_window(paths.capture_time_of(child), window)
            )
            if count:
                counts[kind_dir.name] = counts.get(kind_dir.name, 0) + count

    return [DerivativeKindSummary(kind=kind, count=count) for kind, count in sorted(counts.items())]


def _within_window(captured: datetime | None, window: tuple[datetime, datetime] | None) -> bool:
    if captured is None:
        return False
    return window is None or (window[0] <= captured < window[1])


@router.get("/frames/derivatives", response_model=DerivativeListResponse)
def list_derivatives(
    kind: str = Query(..., description="Derivative kind, e.g. 'keogram' or 'meteor_crop'"),
    date: str | None = Query(None, description="UTC calendar date, YYYY-MM-DD"),
    night: str | None = Query(None, description="Observation night (local date the night started), YYYY-MM-DD"),
    limit: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
    config_manager: ConfigManager = Depends(get_config_manager),
    calculator: SkyStateCalculator = Depends(get_skystate_calculator),
) -> DerivativeListResponse:
    """Paginated, one kind at a time — a busy meteor-detection night can
    produce hundreds of crops, which is exactly the case `GET /api/frames`
    used to embed unpaginated (and slowly) before this endpoint existed."""
    utc_dates, window, _label = _resolve_period(date, night, config_manager, calculator)
    data_dir = settings.data_dir

    found: list[dict] = []
    for iso_date in utc_dates:
        kind_dir = paths.date_dir_for_iso(data_dir, "derivatives", iso_date) / kind
        if not kind_dir.is_dir():
            continue
        for child in kind_dir.iterdir():
            if not child.is_file() or child.stem.endswith("_thumb"):
                continue
            captured = paths.capture_time_of(child)
            if not _within_window(captured, window):
                continue
            thumb = thumbnail_path_for(child)
            found.append(
                {
                    "stem": child.stem,
                    "captured_at": captured,
                    "full": browse.relative_to(data_dir, child),
                    "thumbnail": browse.relative_to(data_dir, thumb) if thumb.is_file() else None,
                    "size": child.stat().st_size,
                }
            )

    found.sort(key=lambda e: e["captured_at"])
    total = len(found)
    page = found[offset : offset + limit]

    entries = [
        DerivativeEntry(
            stem=e["stem"],
            captured_at=e["captured_at"].isoformat(),
            thumbnail=e["thumbnail"],
            full=e["full"],
            size=e["size"],
        )
        for e in page
    ]
    return DerivativeListResponse(kind=kind, entries=entries, total=total, limit=limit, offset=offset)


def _stem_to_iso_date(stem: str) -> str | None:
    when = paths.capture_time_of(Path(stem))
    return when.date().isoformat() if when else None


@router.delete("/frames")
def delete_frames(
    body: DeleteFramesRequest,
    _: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Delete a whole UTC date (`times` empty, `date` required), or
    individual captures by their full `YYYYMMDD-HHMMSS` stem — each stem
    carries its own date, so a selection spanning two UTC dates (a night
    crossing midnight) deletes correctly in one call with no `date` needed.
    """
    data_dir = settings.data_dir
    removed = 0

    if not body.times:
        if body.date is None:
            raise HTTPException(status_code=400, detail="`date` is required when `times` is empty")
        _validate_iso_date(body.date)
        for kind in body.kinds:
            directory = paths.date_dir_for_iso(data_dir, kind, body.date)
            if not directory.is_dir():
                continue
            removed += sum(1 for child in directory.rglob("*") if child.is_file())
            shutil.rmtree(directory)
        logger.info("Deleted %d file(s) for %s via the recordings manager", removed, body.date)
        return {"date": body.date, "files_removed": removed}

    for stem in body.times:
        iso_date = _stem_to_iso_date(stem)
        if iso_date is None:
            continue
        for kind in body.kinds:
            directory = paths.date_dir_for_iso(data_dir, kind, iso_date)
            if not directory.is_dir():
                continue
            # `glob` never escapes `directory`; a stem containing separators
            # simply matches nothing.
            for child in directory.glob(f"{stem}.*"):
                if child.is_file():
                    child.unlink()
                    removed += 1
            # A capture set's other members (see paths.set_dir_name).
            members = directory / f"{stem}_set"
            if re.fullmatch(r"\d{8}-\d{6}", stem) and members.is_dir() and not members.is_symlink():
                removed += sum(1 for child in members.rglob("*") if child.is_file())
                shutil.rmtree(members)

    logger.info("Deleted %d file(s) (%d selected) via the recordings manager", removed, len(body.times))
    return {"date": body.date, "files_removed": removed}
