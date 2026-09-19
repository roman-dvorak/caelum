"""Read-only inspection of the data directory, for the web file browser.

Kept out of the API layer so the path-confinement rule — the one thing here
that must not be got wrong — is a plain function that tests can hammer
directly rather than something only reachable through HTTP.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

MediaKind = Literal["image", "fits", "json", "text", "other"]

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_FITS_SUFFIXES = {".fits", ".fit", ".fts"}
_TEXT_SUFFIXES = {".txt", ".log", ".md", ".csv", ".yaml", ".yml", ".ini", ".conf"}


class PathOutsideRoot(ValueError):
    """The requested path escaped the data directory."""


def resolve_within(root: Path, relative: str) -> Path:
    """Resolve `relative` under `root`, refusing anything that escapes it.

    `Path.resolve()` collapses `..` *and* follows symlinks before the
    containment check, so neither a traversal string nor a symlink planted
    inside the data directory can reach the rest of the filesystem.
    """
    root = root.resolve()
    candidate = (root / relative.lstrip("/")).resolve() if relative else root
    if candidate != root and not candidate.is_relative_to(root):
        raise PathOutsideRoot(f"Path {relative!r} is outside the data directory")
    return candidate


def relative_to(root: Path, path: Path) -> str:
    rel = path.resolve().relative_to(root.resolve())
    return "" if str(rel) == "." else str(rel)


def classify(path: Path) -> MediaKind:
    suffix = path.suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _FITS_SUFFIXES:
        return "fits"
    if suffix == ".json":
        return "json"
    if suffix in _TEXT_SUFFIXES:
        return "text"
    return "other"


def _modified_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")


def describe(root: Path, path: Path) -> dict:
    is_dir = path.is_dir()
    return {
        "name": path.name,
        "path": relative_to(root, path),
        "kind": "dir" if is_dir else "file",
        # Directory sizes are not recursed here: a month of captures is tens
        # of thousands of files and every listing would stat all of them.
        # `/api/files/usage` does the expensive walk, on demand.
        "size": 0 if is_dir else path.stat().st_size,
        "modified_at": _modified_at(path),
        "media": "other" if is_dir else classify(path),
    }


def list_directory(root: Path, relative: str) -> dict:
    target = resolve_within(root, relative)
    if not target.is_dir():
        raise NotADirectoryError(f"{relative!r} is not a directory")

    entries = [describe(root, child) for child in target.iterdir()]
    # Directories first, then newest-first — date directories and capture
    # files are both named so that this puts the most recent work on top.
    entries.sort(key=lambda e: (e["kind"] != "dir", e["name"]), reverse=False)
    entries.sort(key=lambda e: e["kind"] != "dir")

    rel = relative_to(root, target)
    parent = None if target == root.resolve() else relative_to(root, target.parent)
    return {
        "path": rel,
        "parent": parent,
        "entries": entries,
        "total_bytes": sum(e["size"] for e in entries),
    }


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def usage(root: Path, subdirs: tuple[str, ...]) -> dict:
    by_subdir = {name: directory_size(root / name) for name in subdirs}
    disk = shutil.disk_usage(root)
    return {
        "by_subdir": by_subdir,
        "total_bytes": sum(by_subdir.values()),
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
    }


# ---- previews ------------------------------------------------------------


def _autostretch(data: np.ndarray) -> np.ndarray:
    """Percentile stretch to 8-bit.

    Raw night frames are mostly near-black with a few bright stars, so a
    linear min/max scaling renders them as an empty rectangle. Clipping at
    the 1st/99.5th percentile is what makes them actually look like a sky.
    """
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros(data.shape, dtype=np.uint8)
    low, high = np.percentile(finite, (1.0, 99.5))
    if high <= low:
        high = low + 1.0
    scaled = (np.clip(data, low, high) - low) / (high - low)
    return (scaled * 255.0).astype(np.uint8)


def _fits_to_bgr(path: Path) -> np.ndarray:
    from astropy.io import fits  # imported lazily: slow, and rarely needed

    with fits.open(path) as hdul:
        data = next((hdu.data for hdu in hdul if hdu.data is not None), None)
    if data is None:
        raise ValueError("FITS file contains no image data")

    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 3:
        # raw_writer stores colour as (channels, height, width) — see that
        # module. Move it back to the (height, width, channels) OpenCV wants.
        if data.shape[0] in (3, 4):
            data = np.moveaxis(data, 0, -1)
        data = data[..., :3]
    elif data.ndim != 2:
        raise ValueError(f"Unsupported FITS shape {data.shape}")

    stretched = _autostretch(data)
    if stretched.ndim == 2:
        return cv2.cvtColor(stretched, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(stretched, cv2.COLOR_RGB2BGR)


def render_preview(path: Path, max_dim: int = 1024) -> bytes:
    """Render any supported image file as a downscaled PNG.

    The point is the FITS case — browsers cannot display those at all, so a
    raw frame would otherwise be a download-only blob in the file browser.
    """
    media = classify(path)
    if media == "fits":
        image = _fits_to_bgr(path)
    elif media == "image":
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not decode image {path.name}")
    else:
        raise ValueError(f"No preview available for {path.name}")

    height, width = image.shape[:2]
    scale = min(1.0, max_dim / max(height, width))
    if scale < 1.0:
        image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)

    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("PNG encoding failed")
    return encoded.tobytes()
