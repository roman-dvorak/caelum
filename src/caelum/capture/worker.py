"""CaptureWorker — the sole owner of a CameraBackend for the process's
lifetime. Runs on its own thread with one deliberately narrow, fast job:
capture -> calibrate -> stats -> thumbnail -> publish. Nothing slow (disk
writes, derivative processing, uploads) happens here — those subscribe to
the `frame_captured` event and run off-thread instead, so capture cadence
never depends on how busy the rest of the system is.
"""

from __future__ import annotations

import logging
import threading
import time

from caelum.cameras.base import CameraBackend
from caelum.config.manager import ConfigManager
from caelum.control.exposure import ExposureController, ExposureTarget
from caelum.control.skystate import SkyState, SkyStateCalculator
from caelum.control.storage_policy import StoragePolicy
from caelum.events import FRAME_CAPTURED, EventBus

from . import stats as stats_module
from . import thumbnail as thumbnail_module
from .calibration import DarkLibrary
from .frame_store import FrameStore, ProcessedFrame
from .metadata import FrameMetadata, SkyStateModel, default_overlay_elements

logger = logging.getLogger(__name__)

_INITIAL_EXPOSURE_TARGET = ExposureTarget(exposure_us=10_000, analogue_gain=1.0)
_ERROR_BACKOFF_S = 1.0


class StreamModeController:
    """Thread-safe on/off toggle the local web uses to request a faster
    capture cadence for live viewing (e.g. daytime framing) — see
    `POST /api/camera/mode`. Only ever speeds capture up relative to
    whatever StoragePolicy would otherwise pick, never slows it down."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self, enabled: bool) -> None:
        self._event.set() if enabled else self._event.clear()

    @property
    def enabled(self) -> bool:
        return self._event.is_set()


class ManualExposureOverride:
    """Thread-safe manual exposure/gain override — when set, CaptureWorker
    uses these values directly instead of the closed-loop controller. See
    `POST /api/camera/exposure-override`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._target: ExposureTarget | None = None

    def set(self, target: ExposureTarget | None) -> None:
        with self._lock:
            self._target = target

    def get(self) -> ExposureTarget | None:
        with self._lock:
            return self._target


class CaptureWorker(threading.Thread):
    def __init__(
        self,
        camera: CameraBackend,
        config_manager: ConfigManager,
        skystate_calculator: SkyStateCalculator,
        exposure_controller: ExposureController,
        storage_policy: StoragePolicy,
        dark_library: DarkLibrary,
        frame_store: FrameStore,
        event_bus: EventBus,
        sky_state_refresh_interval_s: float = 30.0,
        stream_mode: StreamModeController | None = None,
        manual_exposure: ManualExposureOverride | None = None,
    ) -> None:
        super().__init__(name="CaptureWorker", daemon=True)
        self._camera = camera
        self._config_manager = config_manager
        self._skystate_calculator = skystate_calculator
        self._exposure_controller = exposure_controller
        self._storage_policy = storage_policy
        self._dark_library = dark_library
        self._frame_store = frame_store
        self._event_bus = event_bus
        self._sky_state_refresh_interval_s = sky_state_refresh_interval_s
        self.stream_mode = stream_mode or StreamModeController()
        self.manual_exposure = manual_exposure or ManualExposureOverride()

        self._stop_event = threading.Event()
        self._sky_state: SkyState | None = None
        self._sky_state_computed_at: float = 0.0
        self._current_target = _INITIAL_EXPOSURE_TARGET

    @property
    def current_target(self) -> ExposureTarget:
        return self._current_target

    @property
    def camera_backend_name(self) -> str:
        return type(self._camera).__name__

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self._camera.open()
        try:
            while not self._stop_event.is_set():
                try:
                    self._run_cycle()
                except Exception:
                    logger.exception("Capture cycle failed — retrying after a short backoff")
                    self._stop_event.wait(_ERROR_BACKOFF_S)
        finally:
            self._camera.close()

    def _refresh_sky_state(self) -> SkyState:
        now = time.monotonic()
        stale = (now - self._sky_state_computed_at) >= self._sky_state_refresh_interval_s
        if self._sky_state is None or stale:
            self._sky_state = self._skystate_calculator.compute()
            self._sky_state_computed_at = now
        return self._sky_state

    def _run_cycle(self) -> None:
        cfg = self._config_manager.current
        sky_state = self._refresh_sky_state()
        preset = cfg.exposure_policy.preset_for(sky_state.period)

        manual_target = self.manual_exposure.get()
        if manual_target is not None:
            target = manual_target
        else:
            prev_stats = self._frame_store.get_latest_stats()
            target = self._exposure_controller.compute_target(
                sky_state, prev_stats, self._current_target, cfg.exposure_policy
            )
        self._current_target = target
        self._camera.set_controls(target.exposure_us, target.analogue_gain)

        raw = self._camera.capture_frame()
        image = self._dark_library.apply_dark(raw.image, raw.exposure_us, raw.analogue_gain)

        frame_stats = stats_module.extract(image, saturation_value=preset.saturation_threshold)
        thumbnail_jpeg = thumbnail_module.encode(
            image, cfg.storage_policy.thumbnail_max_dim, cfg.storage_policy.jpeg_quality
        )

        metadata = FrameMetadata(
            captured_at=raw.captured_at,
            exposure_us=raw.exposure_us,
            analogue_gain=raw.analogue_gain,
            sky_state=SkyStateModel.from_skystate(sky_state),
            focus_score=frame_stats.focus_score,
        )
        metadata = metadata.model_copy(update={"overlay_elements": default_overlay_elements(metadata)})

        decision = self._storage_policy.decide(sky_state, cfg.storage_policy)
        processed = ProcessedFrame(
            image=image,
            thumbnail_jpeg=thumbnail_jpeg,
            stats=frame_stats,
            metadata=metadata,
            save_raw=decision.save_raw,
        )

        self._frame_store.update(processed)
        self._event_bus.publish(FRAME_CAPTURED, processed)

        capture_interval_s = decision.capture_interval_s
        if self.stream_mode.enabled and cfg.storage_policy.realtime_stream_fps > 0:
            capture_interval_s = min(capture_interval_s, 1.0 / cfg.storage_policy.realtime_stream_fps)
        self._stop_event.wait(capture_interval_s)
