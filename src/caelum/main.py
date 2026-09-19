"""Headless entrypoint: wires config, camera, capture loop, derivatives,
storage, and the FastAPI app together, then serves until interrupted.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import uvicorn

from caelum.api.app import create_app
from caelum.auth import UserStore
from caelum.cameras.base import CameraBackend
from caelum.cameras.registry import create_camera_backend
from caelum.capture.calibration import DarkLibrary
from caelum.capture.frame_store import FrameStore
from caelum.capture.worker import CaptureWorker
from caelum.config.manager import ConfigManager
from caelum.config.schema import AppConfig, CameraConfig
from caelum.control.exposure import ExposureController
from caelum.control.skystate import SkyStateCalculator
from caelum.control.storage_policy import StoragePolicy
from caelum.derivatives.keogram import KeogramWorker
from caelum.derivatives.meteor_detection import MeteorDetectionWorker
from caelum.derivatives.pool import DerivativePool
from caelum.events import EventBus
from caelum.logging_conf import configure_logging
from caelum.plugins.loader import PluginLoader
from caelum.settings import Settings, load_settings
from caelum.storage.retention import RetentionSweeper
from caelum.storage.writer import StorageWriter
from caelum.upload.uploader import UploadWorker

logger = logging.getLogger(__name__)

# apps/local-web/dist, if it's been built — see caelum-web.
_LOCAL_WEB_DIST = Path(__file__).resolve().parents[3] / "caelum-web" / "apps" / "local-web" / "dist"


async def _async_main(settings: Settings) -> None:
    log_buffer = configure_logging(settings.log_level)

    config_manager = ConfigManager(
        disk_path=settings.config_file,
        default_path=settings.default_config_file,
        redis_url=settings.redis_url,
        key_prefix="caelum",
    )
    await config_manager.start()
    cfg = config_manager.current

    # Accounts live beside config.json but never inside it — see auth/store.py.
    user_store = UserStore(settings.config_dir / "auth.json")
    user_store.load()

    location = cfg.location
    skystate_calculator = SkyStateCalculator(lat=location.lat, lon=location.lon, elevation_m=location.elevation_m)

    loop = asyncio.get_running_loop()
    event_bus = EventBus()
    frame_store = FrameStore(loop=loop, event_bus=event_bus)

    def camera_factory(camera_cfg: CameraConfig) -> CameraBackend:
        """Built fresh each time the camera config changes, so switching
        backend or device from the web UI takes effect without a restart.
        The env override still wins when it is set — it exists precisely to
        pin a dev/CI machine to the mock backend regardless of config."""
        if settings.camera_backend_override:
            camera_cfg = camera_cfg.model_copy(update={"backend": settings.camera_backend_override})
        return create_camera_backend(camera_cfg)

    dark_library = DarkLibrary(darks_dir=settings.data_dir / "darks")

    capture_worker = CaptureWorker(
        camera_factory=camera_factory,
        config_manager=config_manager,
        skystate_calculator=skystate_calculator,
        exposure_controller=ExposureController(),
        storage_policy=StoragePolicy(),
        dark_library=dark_library,
        frame_store=frame_store,
        event_bus=event_bus,
    )

    storage_writer = StorageWriter(event_bus, settings.data_dir)
    upload_worker = UploadWorker(config_manager, event_bus, settings.data_dir)
    retention_sweeper = RetentionSweeper(
        config_manager, settings.data_dir, get_uploaded_before=upload_worker.uploaded_before
    )

    derivative_pool = DerivativePool(event_bus, frame_store, settings.data_dir)

    # The two built-in workers go through the loader like anything else, so
    # `enabled`, `order` and `settings` in AppConfig.plugins govern them —
    # they are the proof that the extension point works, not exceptions to it.
    plugin_loader = PluginLoader([KeogramWorker, MeteorDetectionWorker])

    def reload_plugins(new_config: AppConfig) -> None:
        loaded = plugin_loader.load(new_config)
        derivative_pool.replace_all(lp.plugin for lp in loaded)
        logger.info("Plugins loaded: %s", ", ".join(lp.id for lp in loaded) or "none")

    reload_plugins(cfg)
    config_manager.on_change(reload_plugins)

    app = create_app(static_dir=_LOCAL_WEB_DIST if _LOCAL_WEB_DIST.exists() else None)
    app.state.settings = settings
    app.state.config_manager = config_manager
    app.state.user_store = user_store
    app.state.log_buffer = log_buffer
    app.state.frame_store = frame_store
    app.state.capture_worker = capture_worker
    app.state.skystate_calculator = skystate_calculator
    app.state.plugin_loader = plugin_loader

    capture_worker.start()
    retention_sweeper.start()
    upload_worker.start()
    logger.info(
        "caelum starting: camera=%s http=%s:%d local-web=%s auth=%s",
        settings.camera_backend_override or cfg.camera.backend,
        settings.http_host,
        settings.http_port,
        "bundled" if _LOCAL_WEB_DIST.exists() else "not built",
        "on" if cfg.auth.enabled else "OFF",
    )

    server = uvicorn.Server(
        uvicorn.Config(
            app, host=settings.http_host, port=settings.http_port, log_level=settings.log_level.lower()
        )
    )
    try:
        await server.serve()
    finally:
        logger.info("caelum shutting down")
        capture_worker.request_stop()
        retention_sweeper.request_stop()
        upload_worker.request_stop()
        capture_worker.join(timeout=5)
        retention_sweeper.join(timeout=5)
        upload_worker.join(timeout=5)
        storage_writer.shutdown()
        derivative_pool.shutdown()
        await config_manager.stop()


def run() -> None:
    asyncio.run(_async_main(load_settings()))


if __name__ == "__main__":
    run()
