from __future__ import annotations

import asyncio
import time

import httpx

from caelum.api.app import create_app
from caelum.auth import UserStore
from caelum.cameras.mock_backend import MockCameraBackend
from caelum.capture.calibration import DarkLibrary
from caelum.capture.frame_store import FrameStore
from caelum.capture.worker import CaptureWorker
from caelum.config.manager import ConfigManager
from caelum.control.exposure import ExposureController
from caelum.control.skystate import SkyStateCalculator
from caelum.control.storage_policy import StoragePolicy
from caelum.events import EventBus
from caelum.logging_conf import LogBuffer
from caelum.settings import Settings

ADMIN_PASSWORD = "admin-test-password"
VIEWER_PASSWORD = "viewer-test-password"


def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _Harness:
    def __init__(self, app, worker, config_manager, frame_store, data_dir):
        self.app = app
        self.worker = worker
        self.config_manager = config_manager
        self.frame_store = frame_store
        self.data_dir = data_dir

    def client(self) -> httpx.AsyncClient:
        """An un-authenticated client. `httpx` keeps the session cookie for
        the lifetime of the client, so `login()` is all that is needed."""
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")


async def login(client: httpx.AsyncClient, username: str = "admin", password: str = ADMIN_PASSWORD):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


async def _build_harness(tmp_path, redis_url, key_prefix: str) -> _Harness:
    config_manager = ConfigManager(
        disk_path=tmp_path / "config.json", default_path=None, redis_url=redis_url, key_prefix=key_prefix
    )
    await config_manager.start()
    await config_manager.update(
        {"storage_policy": {"day_capture_interval_s": 0.02, "night_capture_interval_s": 0.02}}
    )

    loop = asyncio.get_running_loop()
    event_bus = EventBus()
    frame_store = FrameStore(loop=loop, event_bus=event_bus)
    worker = CaptureWorker(
        camera_factory=lambda _cfg: MockCameraBackend(),
        config_manager=config_manager,
        skystate_calculator=SkyStateCalculator(lat=50.0755, lon=14.4378, elevation_m=200.0),
        exposure_controller=ExposureController(),
        storage_policy=StoragePolicy(),
        dark_library=DarkLibrary(darks_dir=None),
        frame_store=frame_store,
        event_bus=event_bus,
    )

    # Real accounts, real password hashing, real cookies — the API is now
    # authenticated in production, so the tests exercise it that way rather
    # than switching auth off.
    user_store = UserStore(tmp_path / "auth.json")
    user_store.load()
    user_store.set_password("admin", ADMIN_PASSWORD)
    user_store.create_user("viewer1", VIEWER_PASSWORD, "viewer")

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)

    app = create_app(static_dir=None)
    app.state.settings = Settings(
        config_dir=tmp_path,
        data_dir=data_dir,
        http_host="127.0.0.1",
        http_port=0,
        redis_url=redis_url,
        camera_backend_override=None,
        log_level="WARNING",
    )
    app.state.config_manager = config_manager
    app.state.user_store = user_store
    app.state.frame_store = frame_store
    app.state.capture_worker = worker
    app.state.skystate_calculator = SkyStateCalculator(lat=50.0755, lon=14.4378, elevation_m=200.0)
    app.state.log_buffer = LogBuffer()

    return _Harness(app, worker, config_manager, frame_store, data_dir)


async def test_status_and_skystate_endpoints(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "apitest1")
    harness.worker.start()
    try:
        assert _wait_until(lambda: harness.frame_store.get_latest() is not None)
        async with harness.client() as client:
            await login(client)
            status_resp = await client.get("/api/status")
            assert status_resp.status_code == 200
            body = status_resp.json()
            assert body["capturing"] is True
            assert body["camera_backend"] == "MockCameraBackend"

            sky_resp = await client.get("/api/skystate")
            assert sky_resp.status_code == 200
            assert "period" in sky_resp.json()
    finally:
        harness.worker.request_stop()
        harness.worker.join(timeout=2)
        await harness.config_manager.stop()


async def test_config_get_and_patch_roundtrip(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "apitest2")
    try:
        async with harness.client() as client:
            await login(client)
            get_resp = await client.get("/api/config")
            assert get_resp.status_code == 200
            assert get_resp.json()["location"]["lat"] == 50.0755

            patch_resp = await client.put("/api/config", json={"patch": {"location": {"lat": 12.34}}})
            assert patch_resp.status_code == 200
            assert patch_resp.json()["location"]["lat"] == 12.34
            assert harness.config_manager.current.location.lat == 12.34
    finally:
        await harness.config_manager.stop()


async def test_camera_mode_and_exposure_override_endpoints(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "apitest3")
    try:
        async with harness.client() as client:
            await login(client)
            mode_resp = await client.post("/api/camera/mode", json={"stream_mode": True})
            assert mode_resp.status_code == 200
            assert mode_resp.json()["stream_mode"] is True
            assert harness.worker.stream_mode.enabled is True

            override_resp = await client.post(
                "/api/camera/exposure-override", json={"exposure_us": 5000, "analogue_gain": 2.0}
            )
            assert override_resp.status_code == 200
            assert harness.worker.manual_exposure.get().exposure_us == 5000

            clear_resp = await client.post("/api/camera/exposure-override", json={"clear": True})
            assert clear_resp.json() == {"override": None}
            assert harness.worker.manual_exposure.get() is None
    finally:
        await harness.config_manager.stop()


async def test_plugins_endpoints(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "apitest4")
    try:
        async with harness.client() as client:
            await login(client)
            put_resp = await client.put(
                "/api/plugins/watermark", json={"enabled": True, "order": 5, "settings": {"text": "hi"}}
            )
            assert put_resp.status_code == 200
            assert put_resp.json()["order"] == 5

            list_resp = await client.get("/api/plugins")
            assert list_resp.status_code == 200
            assert list_resp.json()["watermark"]["settings"]["text"] == "hi"
    finally:
        await harness.config_manager.stop()


async def test_latest_frame_jpeg_endpoint(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "apitest5")
    harness.worker.start()
    try:
        assert _wait_until(lambda: harness.frame_store.get_latest() is not None)
        async with harness.client() as client:
            await login(client)
            resp = await client.get("/api/frame/latest.jpg")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/jpeg"
            assert resp.content[:2] == b"\xff\xd8"
    finally:
        harness.worker.request_stop()
        harness.worker.join(timeout=2)
        await harness.config_manager.stop()
