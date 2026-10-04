"""Image assets for `custom_image` overlay elements — small uploads (logos,
watermarks, static markers) an admin attaches to overlay elements from the
visual editor. Stored under `data_dir/overlay_assets/`, which — like
`darks/` — is never swept by retention (see `storage/paths.py`'s
`MANAGED_SUBDIRS`, which retention walks instead of the whole data dir) and
is mirrored to the remote archive as a whole directory by the uploader, so
`custom_image` elements resolve the same way on remote-web as they do here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from caelum.api.deps import get_settings
from caelum.api.schemas import OverlayAssetInfo
from caelum.api.security import Principal, require_admin, require_preview
from caelum.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_ASSET_BYTES = 2 * 1024 * 1024
_ALLOWED_CONTENT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _assets_dir(settings: Settings) -> Path:
    directory = settings.data_dir / "overlay_assets"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _resolve_asset(settings: Settings, name: str) -> Path:
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail=f"Invalid asset name: {name!r}")
    path = _assets_dir(settings) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No such overlay asset: {name}")
    return path


@router.get("/overlay/assets", response_model=list[OverlayAssetInfo])
def list_overlay_assets(
    _: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> list[OverlayAssetInfo]:
    directory = _assets_dir(settings)
    return sorted(
        (OverlayAssetInfo(name=p.name, size=p.stat().st_size) for p in directory.iterdir() if p.is_file()),
        key=lambda a: a.name,
    )


@router.get("/overlay/assets/{name}")
def get_overlay_asset(
    name: str,
    _: Principal = Depends(require_preview),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    return FileResponse(_resolve_asset(settings, name))


@router.post("/overlay/assets", response_model=OverlayAssetInfo)
async def upload_overlay_asset(
    file: UploadFile,
    _: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> OverlayAssetInfo:
    extension = _ALLOWED_CONTENT_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(status_code=415, detail=f"Unsupported image type: {file.content_type}")

    body = await file.read(_MAX_ASSET_BYTES + 1)
    if len(body) > _MAX_ASSET_BYTES:
        raise HTTPException(status_code=413, detail=f"Overlay assets are capped at {_MAX_ASSET_BYTES // 1024} KB")

    # The upload's own filename is untrusted — keep only its stem, sanitized,
    # and always pick the extension from the validated content type so a
    # mismatched/missing suffix can't smuggle in something unexpected.
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", (file.filename or "overlay").rsplit(".", 1)[0]).strip("-") or "overlay"
    name = f"{stem}{extension}"
    path = _assets_dir(settings) / name
    path.write_bytes(body)
    logger.info("Overlay asset uploaded: %s (%d bytes)", name, len(body))
    return OverlayAssetInfo(name=name, size=len(body))


@router.delete("/overlay/assets/{name}")
def delete_overlay_asset(
    name: str,
    _: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    path = _resolve_asset(settings, name)
    path.unlink()
    logger.info("Overlay asset deleted: %s", name)
    return {"deleted": name}
