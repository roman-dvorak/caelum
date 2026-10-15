"""Headless entrypoint: wires config, camera, capture loop, derivatives,
storage, and the FastAPI app together, then serves until interrupted.
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from caelum import __version__
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
from caelum.derivatives.overlay import OverlayWorker
from caelum.derivatives.pool import DerivativePool
from caelum.derivatives.telescope_position import TelescopePositionWorker
from caelum.derivatives.timelapse import TimelapseWorker
from caelum.events import EventBus
from caelum.logging_conf import configure_logging
from caelum.plugins.loader import PluginLoader
from caelum.scheduling.interval_scheduler import IntervalScheduler
from caelum.settings import Settings, load_settings
from caelum.storage.retention import RetentionSweeper
from caelum.storage.writer import StorageWriter
from caelum.update import releases as update_releases
from caelum.update.job import Updater
from caelum.upload.uploader import UploadWorker

logger = logging.getLogger(__name__)

# How long a freshly updated release has to stay up before the boot guard
# (scripts/caelum-launch) stops counting its starts towards a rollback.
_UPDATE_HEALTHY_AFTER_S = 60

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

    def resolve_camera_config(camera_cfg: CameraConfig) -> CameraConfig:
        """The env override still wins when it is set — it exists precisely
        to pin a dev/CI machine to the mock backend regardless of config.
        Shared by `camera_factory` (what actually gets built) and
        `CaptureWorker` (what it records as genuinely open), so the two can
        never disagree about which backend is really running."""
        if settings.camera_backend_override:
            return camera_cfg.model_copy(update={"backend": settings.camera_backend_override})
        return camera_cfg

    def camera_factory(camera_cfg: CameraConfig) -> CameraBackend:
        """Built fresh each time the camera config changes, so switching
        backend or device from the web UI takes effect without a restart."""
        return create_camera_backend(resolve_camera_config(camera_cfg))

    dark_library = DarkLibrary(darks_dir=settings.data_dir / "darks")

    capture_worker = CaptureWorker(
        camera_factory=camera_factory,
        config_manager=config_manager,
        resolve_camera_config=resolve_camera_config,
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
    interval_scheduler = IntervalScheduler()
    interval_scheduler.register(retention_sweeper)

    derivative_pool = DerivativePool(event_bus, frame_store, settings.data_dir, config_manager=config_manager)

    # The two built-in workers go through the loader like anything else, so
    # `enabled`, `order` and `settings` in AppConfig.plugins govern them —
    # they are the proof that the extension point works, not exceptions to it.
    plugin_loader = PluginLoader(
        [KeogramWorker, MeteorDetectionWorker, OverlayWorker, TelescopePositionWorker, TimelapseWorker]
    )

    def reload_plugins(new_config: AppConfig) -> None:
        loaded = plugin_loader.load(new_config)
        derivative_pool.replace_all(lp.plugin for lp in loaded)
        logger.info("Plugins loaded: %s", ", ".join(lp.id for lp in loaded) or "none")

    reload_plugins(cfg)
    config_manager.on_change(reload_plugins)

    web_dir = settings.web_dir if settings.web_dir and settings.web_dir.is_dir() else None
    app = create_app(static_dir=web_dir)
    app.state.settings = settings
    app.state.config_manager = config_manager
    app.state.user_store = user_store
    app.state.log_buffer = log_buffer
    app.state.frame_store = frame_store
    app.state.capture_worker = capture_worker
    app.state.skystate_calculator = skystate_calculator
    app.state.plugin_loader = plugin_loader

    capture_worker.start()
    interval_scheduler.start()
    upload_worker.start()
    logger.info(
        "caelum %s starting: camera=%s http=%s:%d local-web=%s auth=%s",
        __version__,
        settings.camera_backend_override or cfg.camera.backend,
        settings.http_host,
        settings.http_port,
        web_dir or "not built",
        "on" if cfg.auth.enabled else "OFF",
    )

    server = uvicorn.Server(
        uvicorn.Config(
            app, host=settings.http_host, port=settings.http_port, log_level=settings.log_level.lower()
        )
    )

    # Self-update only exists in a managed install; the restart after an
    # update is a plain clean exit that systemd (Restart=always) turns into
    # a start of the newly linked release.
    layout = update_releases.managed_layout()
    if layout is not None:

        def request_restart() -> None:
            server.should_exit = True

        app.state.updater = Updater(layout, request_restart)

        async def confirm_update_when_healthy() -> None:
            await asyncio.sleep(_UPDATE_HEALTHY_AFTER_S)
            if capture_worker.is_alive() and update_releases.confirm_healthy(layout):
                logger.info("Update to %s confirmed healthy", __version__)

        health_task = asyncio.create_task(confirm_update_when_healthy(), name="update-health")
    try:
        await server.serve()
    finally:
        logger.info("caelum shutting down")
        if layout is not None:
            health_task.cancel()
        capture_worker.request_stop()
        interval_scheduler.request_stop()
        upload_worker.request_stop()
        capture_worker.join(timeout=5)
        interval_scheduler.join(timeout=5)
        upload_worker.join(timeout=5)
        storage_writer.shutdown()
        derivative_pool.shutdown()
        await config_manager.stop()


def run() -> None:
    asyncio.run(_async_main(load_settings()))


if __name__ == "__main__":
    run()
