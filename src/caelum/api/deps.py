"""FastAPI dependency accessors — everything lives on `app.state`, wired
once in `main.py`. Type-hinted with `HTTPConnection` (the common base of
`Request` and `WebSocket`) so the same dependency works for both HTTP routes
and the `/ws/stream` websocket route.
"""

from __future__ import annotations

from starlette.requests import HTTPConnection

from caelum.capture.frame_store import FrameStore
from caelum.capture.worker import CaptureWorker
from caelum.capture_runtime.store import ProgramStore
from caelum.config.manager import ConfigManager
from caelum.control.skystate import SkyStateCalculator
from caelum.logging_conf import LogBuffer
from caelum.settings import Settings
from caelum.upload.uploader import UploadWorker


def get_config_manager(conn: HTTPConnection) -> ConfigManager:
    return conn.app.state.config_manager


def get_settings(conn: HTTPConnection) -> Settings:
    return conn.app.state.settings


def get_log_buffer(conn: HTTPConnection) -> LogBuffer:
    return conn.app.state.log_buffer


def get_frame_store(conn: HTTPConnection) -> FrameStore:
    return conn.app.state.frame_store


def get_capture_worker(conn: HTTPConnection) -> CaptureWorker:
    return conn.app.state.capture_worker


def get_program_store(conn: HTTPConnection) -> ProgramStore:
    return conn.app.state.program_store


def get_upload_worker(conn: HTTPConnection) -> UploadWorker:
    return conn.app.state.upload_worker


def get_skystate_calculator(conn: HTTPConnection) -> SkyStateCalculator:
    return conn.app.state.skystate_calculator
