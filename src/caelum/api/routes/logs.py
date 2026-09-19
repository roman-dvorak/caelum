"""Live application log viewer.

A headless camera has no console — this exposes the same information
`journalctl -u caelum -f` would, from the browser. Admin-only: log lines can
include internal file paths and stack traces, not something a read-only
preview account should see.

`GET /api/logs` is a plain snapshot (curl-friendly, and what the frontend
uses for its first paint); `/ws/logs` streams that same backlog once on
connect, then every new line as it's logged.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from caelum.api.deps import get_log_buffer
from caelum.api.security import Principal, authorize_websocket, require_admin
from caelum.logging_conf import LogBuffer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/logs")
def get_logs(
    _: Principal = Depends(require_admin), log_buffer: LogBuffer = Depends(get_log_buffer)
) -> list[dict[str, str]]:
    return [entry.to_dict() for entry in log_buffer.snapshot()]


@router.websocket("/ws/logs")
async def logs_ws(websocket: WebSocket) -> None:
    if await authorize_websocket(websocket, admin=True) is None:
        return
    await websocket.accept()

    log_buffer = get_log_buffer(websocket)
    loop = asyncio.get_running_loop()
    queue = log_buffer.subscribe(loop)
    try:
        await websocket.send_json({"type": "backlog", "entries": [e.to_dict() for e in log_buffer.snapshot()]})
        while True:
            entry = await queue.get()
            await websocket.send_json({"type": "line", "entry": entry.to_dict()})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Error serving /ws/logs")
    finally:
        log_buffer.unsubscribe(queue)
