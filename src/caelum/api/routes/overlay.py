"""Image assets for `custom_image` overlay elements — small uploads (logos,
watermarks, static markers) an admin attaches to overlay elements from the
visual editor. Stored under `data_dir/overlay_assets/`, which — like
`darks/` — is never swept by retention (see `storage/paths.py`'s
`MANAGED_SUBDIRS`, which retention walks instead of the whole data dir). They
are not uploaded: the camera renders them into the overlay image itself
(`derivatives/overlay_render.py`), and that image is what remote-web shows.

Plus the editor's preview: the exact overlay the camera would render for a
draft template, on the latest frame.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from caelum.api.deps import get_config_manager, get_frame_store, get_settings
from caelum.api.schemas import OverlayAssetInfo
from caelum.api.security import Principal, require_admin, require_preview
from caelum.capture import thumbnail
from caelum.capture.frame_store import FrameStore
from caelum.config.manager import ConfigManager
from caelum.derivatives import overlay_render
from caelum.derivatives.overlay import OverlayElementDef, OverlayTemplate, build_elements, default_template
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


def _resolve_asset(settings: Settings, name: str, *, uploaded_only: bool = False) -> Path:
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail=f"Invalid asset name: {name!r}")
    for directory in (_assets_dir(settings), None if uploaded_only else overlay_render.BUILTIN_ASSETS_DIR):
        if directory is not None and (directory / name).is_file():
            return directory / name
    raise HTTPException(status_code=404, detail=f"No such overlay asset: {name}")


@router.get("/overlay/assets", response_model=list[OverlayAssetInfo])
def list_overlay_assets(
    _: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> list[OverlayAssetInfo]:
    assets = {
        p.name: OverlayAssetInfo(name=p.name, size=p.stat().st_size, builtin=True)
        for p in overlay_render.BUILTIN_ASSETS_DIR.iterdir()
        if p.is_file()
    }
    assets.update(
        (p.name, OverlayAssetInfo(name=p.name, size=p.stat().st_size))
        for p in _assets_dir(settings).iterdir()
        if p.is_file()
    )
    return sorted(assets.values(), key=lambda a: a.name)


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
    path = _resolve_asset(settings, name, uploaded_only=True)
    path.unlink()
    logger.info("Overlay asset deleted: %s", name)
    return {"deleted": name}


@router.get("/overlay/default-template", response_model=OverlayTemplate)
def get_default_template(_: Principal = Depends(require_admin)) -> OverlayTemplate:
    """The overlay a new camera starts with — for the editor's "add the
    default template" action."""
    return default_template()


@router.post("/overlay/preview.png")
def preview_overlay(
    elements: list[OverlayElementDef],
    _: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    frame_store: FrameStore = Depends(get_frame_store),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> Response:
    """Renders `elements` (the editor's unsaved template) the way the camera
    would for the latest frame — its labels filled from that frame's
    metadata, together with the system readouts and every other plugin's
    elements — as a transparent PNG at the thumbnail's size."""
    latest = frame_store.get_latest()
    if latest is None:
        raise HTTPException(status_code=404, detail="no frame captured yet")
    others = [e for e in latest.metadata.overlay_elements if e.source != "overlay"]
    rendered = others + build_elements(elements, latest.metadata)
    max_dim = config_manager.current.storage_policy.thumbnail_max_dim
    height, width = thumbnail.resize(latest.image, max_dim).shape[:2]
    layer = overlay_render.render_layer(rendered, (width, height), _assets_dir(settings))
    return Response(
        content=overlay_render.encode_png(layer), media_type="image/png", headers={"Cache-Control": "no-store"}
    )
