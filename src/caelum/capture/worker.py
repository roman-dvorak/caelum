"""CaptureWorker — the sole owner of a CameraBackend for the process's
lifetime. Runs on its own thread with one deliberately narrow, fast job:

    capture -> measure brightness -> exposure regulator -> set controls
            -> hand the frame to the FrameSink

Everything else — dark calibration, statistics, thumbnail encoding, writing
WebP/DNG — happens behind the sink, by default in a separate process (see
`caelum.processing`), and derivatives/uploads hang off the `frame_captured`
event that the sink publishes. Capture cadence therefore never depends on
how busy the rest of the system is.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections.abc import Callable

from caelum.cameras.base import CameraBackend, CameraStalled
from caelum.config.manager import ConfigManager
from caelum.config.schema import AppConfig, CameraConfig
from caelum.control.exposure import (
    ExposureController,
    ExposureDiagnostics,
    ExposureTarget,
    exposure_control_snapshot,
)
from caelum.control.skystate import SkyState, SkyStateCalculator
from caelum.control.storage_policy import StoragePolicy
from caelum.processing.jobs import FrameSink, FrameSubmission, ProcessingSettings

from . import brightness as brightness_module
from .metadata import SkyStateModel

logger = logging.getLogger(__name__)

_INITIAL_EXPOSURE_TARGET = ExposureTarget(exposure_us=10_000, analogue_gain=1.0)

# Time per capture beyond the exposure itself (camera start, readout).
_READOUT_MARGIN_S = 0.2
# Last resort if a capture hangs inside the camera stack despite the
# backend's own timeouts: after the exposure plus this, the process exits so
# systemd starts it again with a fresh camera stack.
_CAPTURE_WATCHDOG_GRACE_S = 60.0
# Stalls in a row (with the camera reopened in between) before giving up on
# this process: right after boot, libcamera in the first process can stay
# unable to deliver frames however often it is reopened, while a fresh
# process works.
_MAX_STALLS_IN_PROCESS = 2
_WATCHDOG_EXIT_CODE = 70
# First guess for how long after `capture_frame()` is called the exposure
# actually starts; refined from every frame that reports it.
_INITIAL_START_LATENCY_S = 0.1

# Retry delay after a failed cycle doubles per consecutive failure, up to
# the max — a camera held by another process must not be hammered once a
# second (each failed open used to leak file descriptors; see
# picamera2_backend._cleanup_failed_init).
_ERROR_BACKOFF_S = 1.0
_MAX_ERROR_BACKOFF_S = 60.0
# Full tracebacks for the first few consecutive failures, then only every
# Nth — one line per retry otherwise.
_FULL_TRACEBACK_FAILURES = 3
_TRACEBACK_EVERY = 20


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


class WhiteBalanceOverride:
    """Thread-safe one-shot white-balance request — like `ManualExposureOverride`,
    but applied once (white balance gains stick on the sensor until changed,
    unlike exposure/gain which the closed-loop controller may want to revisit
    every cycle) rather than re-read every cycle. See
    `POST /api/camera/white-balance`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: tuple[float, float, bool] | None = None

    def request(self, red_gain: float, blue_gain: float, auto: bool = False) -> None:
        with self._lock:
            self._pending = (red_gain, blue_gain, auto)

    def take_pending(self) -> tuple[float, float, bool] | None:
        with self._lock:
            pending = self._pending
            self._pending = None
            return pending


class CaptureWorker(threading.Thread):
    """Owns the camera outright. Nothing else in the process may open, close
    or reconfigure it — including a config change, which is why switching
    cameras is handled here (see `_ensure_camera`) rather than by whoever
    happened to write the config."""

    def __init__(
        self,
        camera_factory: Callable[[CameraConfig], CameraBackend],
        config_manager: ConfigManager,
        skystate_calculator: SkyStateCalculator,
        exposure_controller: ExposureController,
        storage_policy: StoragePolicy,
        frame_sink: FrameSink,
        resolve_camera_config: Callable[[CameraConfig], CameraConfig] | None = None,
        sky_state_refresh_interval_s: float = 30.0,
        stream_mode: StreamModeController | None = None,
        manual_exposure: ManualExposureOverride | None = None,
        white_balance_override: WhiteBalanceOverride | None = None,
    ) -> None:
        super().__init__(name="CaptureWorker", daemon=True)
        self._camera_factory = camera_factory
        self._resolve_camera_config = resolve_camera_config or (lambda cfg: cfg)
        self._camera: CameraBackend | None = None
        self._camera_config: CameraConfig | None = None
        self._config_manager = config_manager
        self._skystate_calculator = skystate_calculator
        self._exposure_controller = exposure_controller
        self._storage_policy = storage_policy
        self._frame_sink = frame_sink
        self._sky_state_refresh_interval_s = sky_state_refresh_interval_s
        self.stream_mode = stream_mode or StreamModeController()
        self.manual_exposure = manual_exposure or ManualExposureOverride()
        self.white_balance_override = white_balance_override or WhiteBalanceOverride()

        self._stop_event = threading.Event()
        self._sky_state: SkyState | None = None
        self._sky_state_computed_at: float = 0.0
        self._current_target = _INITIAL_EXPOSURE_TARGET
        self._needs_initial_controls = True
        self._was_manual = False
        self._frame_period_s: float | None = None
        # Capture grid, in wall-clock seconds: the next slot, and the
        # interval the grid was laid out with.
        self._next_due: float | None = None
        self._grid_interval_s: float | None = None
        self._start_latency_s = _INITIAL_START_LATENCY_S

    @property
    def current_target(self) -> ExposureTarget:
        """What was last commanded for the next frame."""
        return self._current_target

    @property
    def exposure_diagnostics(self) -> ExposureDiagnostics | None:
        return self._exposure_controller.diagnostics

    @property
    def frame_period_s(self) -> float | None:
        """The current spacing between captures."""
        return self._frame_period_s

    @property
    def frame_sink(self) -> FrameSink:
        return self._frame_sink

    @property
    def camera_backend_name(self) -> str:
        return type(self._camera).__name__ if self._camera is not None else "none"

    @property
    def camera_config(self) -> CameraConfig | None:
        """The config the *currently open* camera was built from, which can
        lag `config.camera` by up to one capture cycle after a change."""
        return self._camera_config

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        failures = 0
        stalls = 0
        try:
            while not self._stop_event.is_set():
                try:
                    self._run_cycle()
                    if failures:
                        logger.info("Capture recovered after %d failed cycle(s)", failures)
                    failures = 0
                    stalls = 0
                except Exception as exc:
                    failures += 1
                    if isinstance(exc, CameraStalled):
                        stalls += 1
                        if stalls >= _MAX_STALLS_IN_PROCESS:
                            self._capture_hung()
                    # Start over with a freshly opened camera next time — a
                    # failed capture may have left it in a bad state.
                    self._close_camera()
                    delay = min(_ERROR_BACKOFF_S * 2 ** (failures - 1), _MAX_ERROR_BACKOFF_S)
                    if failures <= _FULL_TRACEBACK_FAILURES or failures % _TRACEBACK_EVERY == 0:
                        logger.exception(
                            "Capture cycle failed (%d in a row) — retrying in %.0fs", failures, delay
                        )
                    else:
                        logger.warning(
                            "Capture cycle failed (%d in a row): %s — retrying in %.0fs", failures, exc, delay
                        )
                    self._stop_event.wait(delay)
        finally:
            self._close_camera()

    def _ensure_camera(self, camera_cfg: CameraConfig) -> CameraBackend:
        """Open the camera, reopening it if the configuration changed.

        Checked once per cycle instead of reacting to a config-change event:
        a hardware open/close must happen on this thread (it is the only one
        allowed to touch the device), and doing it between captures means a
        switch can never land in the middle of an exposure.

        `resolve_camera_config` lets a deployment-level override (e.g.
        `CAELUM_CAMERA_BACKEND`) rewrite what actually gets built — see
        `main.py`'s `camera_factory`. Comparing and recording the *resolved*
        config here (not the raw requested one) is what keeps `camera_config`
        — and therefore `GET /api/camera/options`' `active`/`applied` fields —
        honest about which backend is genuinely open, instead of echoing back
        a selection the override silently replaced.
        """
        resolved_cfg = self._resolve_camera_config(camera_cfg)
        if self._camera is not None and self._camera_config == resolved_cfg:
            return self._camera

        if self._camera is not None:
            logger.info(
                "Camera configuration changed (%s -> %s) — reopening",
                self._camera_config, resolved_cfg,
            )
            self._close_camera()

        camera = self._camera_factory(camera_cfg)
        camera.open()
        # Only recorded after a successful open, so a bad configuration is
        # retried on the next cycle rather than latched as "current" and
        # silently leaving the camera closed.
        self._camera = camera
        self._camera_config = resolved_cfg
        # A fresh camera knows nothing of our last exposure — set it before
        # the first capture, and restart the regulator from whatever that
        # first frame then actually reports.
        self._needs_initial_controls = True
        self._exposure_controller.reset()
        self._next_due = None
        logger.info("Camera opened: %s (%s)", type(camera).__name__, resolved_cfg.sensor_id)
        return camera

    def _close_camera(self) -> None:
        if self._camera is None:
            return
        try:
            self._camera.close()
        except Exception:
            logger.exception("Error closing camera — continuing")
        self._camera = None
        self._camera_config = None

    def _refresh_sky_state(self) -> SkyState:
        now = time.monotonic()
        stale = (now - self._sky_state_computed_at) >= self._sky_state_refresh_interval_s
        if self._sky_state is None or stale:
            self._sky_state = self._skystate_calculator.compute()
            self._sky_state_computed_at = now
        return self._sky_state

    def _interval(self, cfg: AppConfig, sky_state: SkyState) -> float:
        base = self._storage_policy.decide(sky_state, cfg.storage_policy).capture_interval_s
        if self.stream_mode.enabled and cfg.storage_policy.realtime_stream_fps > 0:
            base = min(base, 1.0 / cfg.storage_policy.realtime_stream_fps)
        return base

    def _frame_period(self, cfg: AppConfig, sky_state: SkyState, target: ExposureTarget) -> float:
        """Effective spacing between captures: `capture_interval_s`, or —
        while the exposure (plus start/readout overhead) doesn't fit in one
        interval — the smallest whole multiple of it, since captures always
        land on the same grid and just skip the slots they can't make."""
        base = self._interval(cfg, sky_state)
        needed = target.exposure_us / 1e6 + self._start_latency_s + _READOUT_MARGIN_S
        period = base if needed <= base else base * math.ceil(needed / base)
        if period != self._frame_period_s:
            if period > base:
                logger.info(
                    "Capture period %.3gs (interval %.3gs; exposure %.3gs doesn't fit in one)",
                    period, base, target.exposure_us / 1e6,
                )
            else:
                logger.info("Capture period %.3gs", period)
        self._frame_period_s = period
        return period

    def _apply(self, camera: CameraBackend, target: ExposureTarget) -> None:
        camera.set_controls(target.exposure_us, target.analogue_gain)
        self._current_target = target

    @staticmethod
    def _capture_hung() -> None:
        logger.critical(
            "Capture has hung inside the camera stack — exiting so the service restarts with a fresh one"
        )
        logging.shutdown()
        os._exit(_WATCHDOG_EXIT_CODE)

    def _wait_for_slot(self, interval_s: float, exposure_s: float) -> float:
        """Wait for the moment to start the next capture, and return the
        grid slot (wall-clock seconds) it is aimed at.

        The grid is laid out on the wall clock — slots at whole multiples of
        the interval (every minute on the minute, say) — and the *middle of
        the exposure* is what lands on a slot, so captures are evenly spaced
        however much the exposure changes. The start is brought forward by
        half the exposure plus the measured start latency. A slot that can't
        be made any more is skipped; the grid itself never moves."""
        now = time.time()
        if self._next_due is None or self._grid_interval_s != interval_s:
            self._grid_interval_s = interval_s
            self._next_due = math.ceil(now / interval_s) * interval_s
        lead = exposure_s / 2 + self._start_latency_s
        if self._next_due - lead < now:
            self._next_due += math.ceil((now - (self._next_due - lead)) / interval_s) * interval_s
        self._stop_event.wait(self._next_due - lead - now)
        return self._next_due

    def _run_cycle(self) -> None:
        cfg = self._config_manager.current
        camera = self._ensure_camera(cfg.camera)

        wb_request = self.white_balance_override.take_pending()
        if wb_request is not None:
            red_gain, blue_gain, auto = wb_request
            camera.set_white_balance(red_gain, blue_gain, auto)

        sky_state = self._refresh_sky_state()
        policy = cfg.exposure_policy
        manual_target = self.manual_exposure.get()

        if self._needs_initial_controls:
            if manual_target is not None:
                start = manual_target
            elif self._exposure_controller.diagnostics is None:
                start = self._exposure_controller.initial_target(sky_state.period, policy)
            else:
                start = self._current_target
            self._apply(camera, start)
            self._exposure_controller.prime(start, sky_state.period)
            self._needs_initial_controls = False

        interval_s = self._interval(cfg, sky_state)
        due = self._wait_for_slot(interval_s, self._current_target.exposure_us / 1e6)
        if self._stop_event.is_set():
            return
        # Waiting may have taken a whole interval — describe the sky as it
        # is now, at the capture.
        sky_state = self._refresh_sky_state()
        called_ns = time.monotonic_ns()
        watchdog = threading.Timer(
            self._current_target.exposure_us / 1e6 + _CAPTURE_WATCHDOG_GRACE_S, self._capture_hung
        )
        watchdog.daemon = True
        watchdog.start()
        try:
            raw = camera.capture_frame()
        finally:
            watchdog.cancel()
        self._next_due = due + interval_s
        if raw.exposure_start_monotonic_ns is not None:
            latency = (raw.exposure_start_monotonic_ns - called_ns) / 1e9
            if 0.0 <= latency < 2.0:
                self._start_latency_s = 0.7 * self._start_latency_s + 0.3 * latency

        applied = ExposureTarget(exposure_us=raw.exposure_us, analogue_gain=raw.analogue_gain)
        sample = brightness_module.measure(raw.image, policy.brightness_roi_diameter_frac)

        # Every frame is taken with exactly the settings requested for it
        # (see Picamera2Backend), so the next one can be decided right here.
        if manual_target is not None:
            next_target = manual_target
            self._exposure_controller.track(manual_target, sample, applied, sky_state.period, policy)
        else:
            if self._was_manual:
                # Leaving manual: continue from the manual setting.
                self._exposure_controller.reset()
            next_target = self._exposure_controller.step(sample, applied, sky_state.period, policy)
        self._was_manual = manual_target is not None
        self._apply(camera, next_target)
        self._frame_period(cfg, sky_state, next_target)

        decision = self._storage_policy.decide(sky_state, cfg.storage_policy)
        self._frame_sink.submit(
            FrameSubmission(
                raw=raw,
                sky_state=SkyStateModel.from_skystate(sky_state),
                save_raw=decision.save_raw,
                settings=ProcessingSettings.from_config(cfg, sky_state.period),
                brightness=sample,
                exposure_control=exposure_control_snapshot(self._exposure_controller.diagnostics),
            )
        )
