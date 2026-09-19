"""Headless entrypoint: wires config, camera, capture loop, derivatives,
storage, and the FastAPI app together, then serves until interrupted.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import uvicorn

from caelum.api.app import create_app
from caelum.cameras.registry import create_camera_backend
from caelum.capture.calibration import DarkLibrary
from caelum.capture.frame_store import FrameStore
from caelum.capture.worker import CaptureWorker
from caelum.config.manager import ConfigManager
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
    configure_logging(settings.log_level)

    config_manager = ConfigManager(
        disk_path=settings.config_file,
        default_path=settings.default_config_file,
        redis_url=settings.redis_url,
        key_prefix="caelum",
    )
    await config_manager.start()
    cfg = config_manager.current

    location = cfg.location
    skystate_calculator = SkyStateCalculator(lat=location.lat, lon=location.lon, elevation_m=location.elevation_m)

    loop = asyncio.get_running_loop()
    event_bus = EventBus()
    frame_store = FrameStore(loop=loop, event_bus=event_bus)

    backend_name = settings.camera_backend_override or cfg.camera.backend
    camera = create_camera_backend(cfg.camera.model_copy(update={"backend": backend_name}))
    dark_library = DarkLibrary(darks_dir=settings.data_dir / "darks")

    capture_worker = CaptureWorker(
        camera=camera,
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
    derivative_pool.register(KeogramWorker())
    derivative_pool.register(MeteorDetectionWorker(process_pool=derivative_pool.process_pool))

    plugin_loader = PluginLoader()  # no third-party plugins registered yet — see plugins/loader.py
    derivative_pool.register_all(loaded.plugin for loaded in plugin_loader.load(config_manager.current))

    app = create_app(static_dir=_LOCAL_WEB_DIST if _LOCAL_WEB_DIST.exists() else None)
    app.state.config_manager = config_manager
    app.state.frame_store = frame_store
    app.state.capture_worker = capture_worker
    app.state.skystate_calculator = skystate_calculator
    app.state.plugin_loader = plugin_loader

    capture_worker.start()
    retention_sweeper.start()
    upload_worker.start()
    logger.info(
        "caelum starting: camera=%s http=%s:%d local-web=%s",
        backend_name,
        settings.http_host,
        settings.http_port,
        "bundled" if _LOCAL_WEB_DIST.exists() else "not built",
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
