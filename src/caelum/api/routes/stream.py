"""Live view for `local-web`: a plain JPEG for the "current frame" case, and
a WebSocket that pushes `{metadata}` + JPEG bytes as two frames per update —
metadata first so the client can size/prepare before the image lands.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect

from caelum.api.deps import get_frame_store
from caelum.capture.frame_store import FrameStore

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/frame/latest.jpg")
def get_latest_thumbnail(frame_store: FrameStore = Depends(get_frame_store)) -> Response:
    latest = frame_store.get_latest()
    if latest is None:
        raise HTTPException(status_code=404, detail="no frame captured yet")
    return Response(content=latest.thumbnail_jpeg, media_type="image/jpeg")


@router.websocket("/ws/stream")
async def stream_ws(websocket: WebSocket, frame_store: FrameStore = Depends(get_frame_store)) -> None:
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
