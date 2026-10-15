"""Date-based directory convention shared by the storage writer, retention
sweeper, derivative pool, uploader, and the recordings API:

    <data_dir>/<kind>/<YYYY>/<MM>/<DD>/<YYYYMMDD-HHMMSS>[_extra].<ext>

Both the directory nesting and the filename carry the same UTC timestamp —
deliberately redundant. A file's own name is enough to know exactly when it
was captured (`capture_time_of` only ever reads the filename), which is what
makes a derivative's decorated name (`<YYYYMMDD-HHMMSS>_<worker>_<kind>.ext`)
just as parseable as a plain capture; the nested directories exist so a
`thumbnails/2026/09/` listing is a normal "browse by month" without opening
anything. Every timestamp here is UTC, always — there is no local-time
variant of this convention anywhere in the app.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

MANAGED_SUBDIRS = ("raw", "thumbnails", "derivatives")

#: What new captures are written as (first entry) plus the legacy formats
#: older captures on disk may still be in — every reader filters with these
#: so a mixed directory keeps working.
THUMBNAIL_SUFFIXES = (".webp", ".jpg", ".jpeg")
RAW_SUFFIXES = (".dng", ".fits")


def date_parts(when: datetime) -> tuple[str, str, str]:
    return when.strftime("%Y"), when.strftime("%m"), when.strftime("%d")


def timestamp_stem(when: datetime) -> str:
    """`YYYYMMDD-HHMMSS`, UTC — the self-sufficient identifier embedded in
    every managed file's name, so a bare filename (no parent directory
    needed) is enough to reconstruct its exact capture time."""
    return when.strftime("%Y%m%d-%H%M%S")


def date_dir(data_dir: Path, subdir: str, when: datetime) -> Path:
    year, month, day = date_parts(when)
    return data_dir / subdir / year / month / day


def date_dir_for_iso(data_dir: Path, subdir: str, iso_date: str) -> Path:
    """Same as `date_dir`, from an already-known `YYYY-MM-DD` string (the
    API's date/night identifiers) rather than a `datetime` — avoids a
    round-trip through `strptime` just to split on dashes."""
    year, month, day = iso_date.split("-")
    return data_dir / subdir / year / month / day


def raw_path(data_dir: Path, when: datetime) -> Path:
    return date_dir(data_dir, "raw", when) / f"{timestamp_stem(when)}{RAW_SUFFIXES[0]}"


def thumbnail_path(data_dir: Path, when: datetime) -> Path:
    return date_dir(data_dir, "thumbnails", when) / f"{timestamp_stem(when)}{THUMBNAIL_SUFFIXES[0]}"


def member_stem(when: datetime, index: int) -> str:
    """A capture-set member's stem: the representative's stem plus `_mNN`
    (so `capture_time_of` still reads the set's time from it)."""
    return f"{timestamp_stem(when)}_m{index:02d}"


def set_dir_name(when: datetime) -> str:
    """Members of a capture set other than its representative live in this
    subdirectory of the day directory — out of sight of everything that
    lists one capture per file, still found by recursive walks (retention)."""
    return f"{timestamp_stem(when)}_set"


def member_path(data_dir: Path, subdir: str, when: datetime, index: int, suffix: str) -> Path:
    """`<data_dir>/<subdir>/YYYY/MM/DD/<stem>_set/<stem>_mNN<suffix>`, `when`
    being the representative's capture time."""
    return date_dir(data_dir, subdir, when) / set_dir_name(when) / f"{member_stem(when, index)}{suffix}"


def sidecar_path(image_path: Path) -> Path:
    return image_path.with_suffix(".json")


def capture_time_of(path: Path) -> datetime | None:
    """Best-effort reconstruction of a managed file's capture time from its
    own `<YYYYMMDD-HHMMSS>[_extra]` name — independent of how deep it's
    nested, so retention/the recordings API never need to also inspect
    which directory a file happens to be sitting in."""
    try:
        token = path.stem.split("_", 1)[0]
        naive = datetime.strptime(token, "%Y%m%d-%H%M%S")
        return naive.replace(tzinfo=UTC)
    except (ValueError, IndexError):
        return None
