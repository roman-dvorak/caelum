"""Live view for `local-web`: a plain JPEG for the "current frame" case, and
a WebSocket that pushes `{metadata}` + JPEG bytes as two frames per update —
metadata first so the client can size/prepare before the image lands.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from caelum.api.deps import get_frame_store, get_settings
from caelum.api.security import Principal, authorize_websocket, require_preview
from caelum.capture.frame_store import FrameStore
from caelum.settings import Settings
from caelum.storage import paths

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/frame/latest.jpg")
def get_latest_thumbnail(
    _: Principal = Depends(require_preview), frame_store: FrameStore = Depends(get_frame_store)
) -> Response:
    latest = frame_store.get_latest()
    if latest is None:
        raise HTTPException(status_code=404, detail="no frame captured yet")
    return Response(content=latest.thumbnail_jpeg, media_type="image/jpeg")


@router.get("/api/frame/raw")
def get_frame_raw(
    captured_at: datetime | None = Query(
        None, description="`metadata.captured_at` of the frame; the latest frame if omitted"
    ),
    _: Principal = Depends(require_preview),
    frame_store: FrameStore = Depends(get_frame_store),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """The raw file (DNG, or FITS for older captures) of a live-view frame,
    as a download. Raw is only kept during `storage_policy.raw_periods`, and
    is written a moment after the frame first shows up — hence 404 rather
    than an error when there is none (yet)."""
    if captured_at is None:
        latest = frame_store.get_latest()
        if latest is None:
            raise HTTPException(status_code=404, detail="no frame captured yet")
        captured_at = latest.metadata.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    base = paths.raw_path(settings.data_dir, captured_at.astimezone(UTC))
    for suffix in paths.RAW_SUFFIXES:
        candidate = base.with_suffix(suffix)
        if candidate.is_file():
            media_type = "image/x-adobe-dng" if suffix == ".dng" else "application/fits"
            return FileResponse(candidate, media_type=media_type, filename=candidate.name)
    raise HTTPException(status_code=404, detail="no raw file for this frame (not a raw period, or not written yet)")


@router.websocket("/ws/stream")
async def stream_ws(websocket: WebSocket, frame_store: FrameStore = Depends(get_frame_store)) -> None:
    if await authorize_websocket(websocket, admin=False) is None:
        return
    await websocket.accept()
    queue = frame_store.subscribe()
    try:
        latest = frame_store.get_latest()
        if latest is not None:
            await websocket.send_text(latest.metadata.model_dump_json())
            await websocket.send_bytes(latest.thumbnail_jpeg)
        while True:
            frame = await queue.get()
            await websocket.send_text(frame.metadata.model_dump_json())
            await websocket.send_bytes(frame.thumbnail_jpeg)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Error serving /ws/stream")
    finally:
        frame_store.unsubscribe(queue)
