"""Browsing, previewing and pruning everything under the data directory.

Every path in this module goes through `browse.resolve_within()` before it
touches the filesystem — there is no other way in, and no route is allowed
to build a `Path` from user input on its own.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse

from caelum.api.deps import get_settings
from caelum.api.schemas import DirectoryListing, UsageResponse
from caelum.api.security import Principal, require_admin, require_preview
from caelum.settings import Settings
from caelum.storage import browse
from caelum.storage.paths import MANAGED_SUBDIRS

logger = logging.getLogger(__name__)

router = APIRouter()

_PREVIEWABLE = {"image", "fits"}
_INLINE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}


def _resolve(settings: Settings, path: str) -> Path:
    try:
        return browse.resolve_within(settings.data_dir, path)
    except browse.PathOutsideRoot as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolve_existing_file(settings: Settings, path: str) -> Path:
    target = _resolve(settings, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"No such file: {path}")
    return target


@router.get("/files", response_model=DirectoryListing)
def list_files(
    path: str = Query("", description="Directory path relative to the data directory"),
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
) -> DirectoryListing:
    target = _resolve(settings, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"No such directory: {path}")
    try:
        return DirectoryListing(**browse.list_directory(settings.data_dir, path))
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/files/usage", response_model=UsageResponse)
def get_usage(
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
) -> UsageResponse:
    """Per-category byte totals plus free space — walks the tree, so it is
    the one listing endpoint that is deliberately not called per navigation."""
    return UsageResponse(**browse.usage(settings.data_dir, (*MANAGED_SUBDIRS, "darks")))


@router.get("/files/content")
def get_file_content(
    path: str = Query(...),
    download: bool = Query(False, description="Send as an attachment rather than inline"),
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    target = _resolve_existing_file(settings, path)
    media_type = _INLINE_MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(
        target,
        media_type=media_type,
        filename=target.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/files/preview")
def get_file_preview(
    path: str = Query(...),
    max_dim: int = Query(1024, ge=64, le=4096),
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Downscaled PNG for any renderable file — including FITS, which no
    browser can display, so raw frames stay inspectable from the UI."""
    target = _resolve_existing_file(settings, path)
    if browse.classify(target) not in _PREVIEWABLE:
        raise HTTPException(status_code=415, detail=f"No preview available for {target.name}")
    try:
        png = browse.render_preview(target, max_dim=max_dim)
    except Exception as exc:
        logger.warning("Preview failed for %s: %s", target, exc)
        raise HTTPException(status_code=422, detail=f"Could not render preview: {exc}") from exc
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.delete("/files")
def delete_path(
    path: str = Query(..., description="File or directory to delete, relative to the data directory"),
    _: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    target = _resolve(settings, path)
    if target == settings.data_dir.resolve():
        raise HTTPException(status_code=400, detail="Refusing to delete the data directory itself")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"No such path: {path}")

    if target.is_dir():
        removed = sum(1 for child in target.rglob("*") if child.is_file())
        shutil.rmtree(target)
    else:
        removed = 1
        target.unlink()
    logger.info("Deleted %s (%d file(s)) via the file browser", path, removed)
    return {"deleted": path, "files_removed": removed}
