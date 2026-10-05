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

import asyncio
import hashlib
import logging
import math
import os
import threading
import time
from collections.abc import Callable

from caelum import __version__
from caelum.cameras.base import CameraBackend, CameraStalled, CaptureRequest, RawFrame
from caelum.capture_runtime import (
    CaptureContext,
    CaptureProgramError,
    CaptureSet,
    LoadedProgram,
    builtin_program,
    testrun,
)
from caelum.capture_runtime.context import Overrides
from caelum.capture_runtime.errors import ProgramStopped
from caelum.capture_runtime.runner import DEFAULT_MAX_CAPTURES, run_once, timeout_for
from caelum.capture_runtime.store import ProgramStore
from caelum.config.manager import ConfigManager
from caelum.config.schema import AppConfig, CameraConfig
from caelum.control.exposure import (
    ExposureController,
    ExposureDiagnostics,
    ExposureTarget,
)
from caelum.control.skystate import SkyState, SkyStateCalculator
from caelum.control.storage_policy import StoragePolicy
from caelum.processing.jobs import FrameSink, FrameSubmission, ProcessingSettings
from caelum.storage import paths

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
        program_provider: Callable[[AppConfig], LoadedProgram] | None = None,
        program_store: ProgramStore | None = None,
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
        self._commanded = _INITIAL_EXPOSURE_TARGET
        self._camera_fresh = True
        self._frame_period_s: float | None = None
        # Capture grid, in wall-clock seconds: the next slot, and the
        # interval the grid was laid out with.
        self._next_due: float | None = None
        self._grid_interval_s: float | None = None
        self._start_latency_s = _INITIAL_START_LATENCY_S

        # The capture program (see caelum.capture_runtime) and its state.
        self._program_store = program_store
        if program_provider is None:
            program_provider = program_store.active if program_store is not None else _builtin_default_provider
        self._program_provider = program_provider
        self._program: LoadedProgram | None = None
        self._program_state: dict = {}
        self._program_runs = 0
        self._program_failures = 0
        self._program_last_error: str | None = None
        #: (name, sha256) of the program replaced by default.py after
        #: failing — until a different program is activated.
        self._fallback_for: tuple[str, str] | None = None
        #: The configured program couldn't even be loaded.
        self._load_failed = False
        self._test_lock = threading.Lock()
        self._pending_test: testrun.TestRequest | None = None
        self._running_test: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Per run: the interval of the grid and the slot the run is aimed at.
        self._run_interval_s = 0.0

    @property
    def current_target(self) -> ExposureTarget:
        """What was last commanded for the next frame."""
        return self._commanded

    @property
    def program_status(self) -> dict:
        program = self._program
        return {
            "name": program.name if program else None,
            "sha256": program.sha256 if program else None,
            "origin": program.origin if program else None,
            "runs": self._program_runs,
            "consecutive_failures": self._program_failures,
            "last_error": self._program_last_error,
            "fallback_active": self._fallback_active,
            "fallback_for": list(self._fallback_for) if self._fallback_for else None,
            "pending_test": self._pending_test.run_id if self._pending_test else None,
            "running_test": self._running_test,
        }

    @property
    def _fallback_active(self) -> bool:
        return self._fallback_for is not None or self._load_failed

    @property
    def camera_capabilities(self):
        return self._camera.capabilities if self._camera is not None else None

    def request_program_test(self, request: testrun.TestRequest) -> None:
        """Queue a test run (one at a time); it starts after the next slot."""
        with self._test_lock:
            if self._pending_test is not None or self._running_test is not None:
                raise RuntimeError("a test run is already queued or running")
            self._pending_test = request

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
        self._loop = asyncio.new_event_loop()
        if self._program_store is not None:
            crashed = self._program_store.take_crash_marker()
            if crashed is not None:
                self._fallback_for = crashed
                self._program_last_error = (
                    f"{crashed[0]} ({crashed[1][:12]}) hung and the process was restarted — running default.py"
                )
                logger.error("Capture program %s", self._program_last_error)
        failures = 0
        stalls = 0
        try:
            while not self._stop_event.is_set():
                try:
                    self._run_cycle()
                    self._run_pending_test()
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
            self._loop.close()

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
        self._camera_fresh = True
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

    # ---- capture programs ---------------------------------------------------

    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def capture_for_program(self, req: CaptureRequest, align_to_slot: bool) -> tuple[RawFrame, SkyState]:
        """`ctx.capture()`'s worker side: set the camera up (best effort),
        wait for the slot (first capture of a run only), take the frame
        under the watchdog."""
        camera = self._camera
        assert camera is not None
        record = camera.apply_request(req)
        exposure_s = record["commanded"]["exposure_us"] / 1e6
        due = None
        if align_to_slot:
            due = self._wait_for_slot(self._run_interval_s, exposure_s)
            if self._stop_event.is_set():
                raise ProgramStopped
        # Waiting may have taken a whole interval — describe the sky as it
        # is now, at the capture.
        sky_state = self._refresh_sky_state()
        called_ns = time.monotonic_ns()
        watchdog = threading.Timer(exposure_s + _CAPTURE_WATCHDOG_GRACE_S, self._capture_hung)
        watchdog.daemon = True
        watchdog.start()
        try:
            raw = camera.finish_request(camera.capture_frame(), record)
        finally:
            watchdog.cancel()
        if due is not None:
            self._next_due = due + self._run_interval_s
        if raw.exposure_start_monotonic_ns is not None:
            latency = (raw.exposure_start_monotonic_ns - called_ns) / 1e9
            if 0.0 <= latency < 2.0:
                self._start_latency_s = 0.7 * self._start_latency_s + 0.3 * latency
        return raw, sky_state

    def _current_program(self, cfg: AppConfig) -> LoadedProgram:
        try:
            wanted = self._program_provider(cfg)
        except Exception as exc:  # noqa: BLE001 - a missing/broken program must never stop capture
            message = f"cannot load {cfg.capture.active_program}: {exc}"
            if message != self._program_last_error:
                logger.error("Capture program %s — running default.py", message)
            self._program_last_error = message
            self._load_failed = True
            wanted = None
        else:
            self._load_failed = False
            if self._fallback_for is not None and (wanted.name, wanted.sha256) != self._fallback_for:
                # Another program (or version) was activated since: give it a go.
                self._fallback_for = None
                self._program_failures = 0
        if wanted is None or self._fallback_for is not None:
            program = _builtin_default_provider(cfg)
        else:
            program = wanted
        if self._program is None or program.sha256 != self._program.sha256 or program.name != self._program.name:
            logger.info("Capture program: %s (%s, sha256 %s)", program.name, program.origin, program.sha256[:12])
            self._program_state = {}
            self._program_runs = 0
        self._program = program
        return program

    def _program_failed(self, program: LoadedProgram, exc: CaptureProgramError, cfg: AppConfig) -> None:
        self._program_failures += 1
        self._program_last_error = str(exc)
        logger.error("Capture program %s failed: %s", program.name, exc, exc_info=exc.__cause__ or exc)
        limit = cfg.capture.max_consecutive_failures
        if self._fallback_for is None and program.origin != "builtin" and self._program_failures >= limit:
            logger.error("Capture program %s failed %d times in a row — falling back to default.py", program.name,
                         self._program_failures)
            self._fallback_for = (program.name, program.sha256)

    def _program_hung(self, program: LoadedProgram) -> None:
        logger.critical("Capture program %s is stuck (not yielding) — restarting the process", program.name)
        if self._program_store is not None and program.origin != "builtin":
            self._program_store.mark_crashed(program)
        self._capture_hung()

    def _run_pending_test(self) -> None:
        with self._test_lock:
            request, self._pending_test = self._pending_test, None
            if request is None or self._stop_event.is_set():
                return
            self._running_test = request.run_id
        try:
            cfg = self._config_manager.current
            camera = self._ensure_camera(cfg.camera)
            sky_state = self._refresh_sky_state()
            hard_limit = threading.Timer(
                timeout_for(request.program, self._run_interval_s, 0.0) + 600.0, self._program_hung,
                args=(request.program,),
            )
            hard_limit.daemon = True
            hard_limit.start()
            try:
                testrun.execute(
                    request,
                    driver=_UnalignedDriver(self),
                    config=cfg,
                    sky=sky_state,
                    exposure_controller=self._exposure_controller,
                    commanded=self._commanded,
                    capabilities=camera.capabilities,
                    interval_s=self._run_interval_s or self._interval(cfg, sky_state),
                    loop=self._loop,
                    thumbnail_max_dim=cfg.storage_policy.thumbnail_max_dim,
                )
            finally:
                hard_limit.cancel()
        finally:
            with self._test_lock:
                self._running_test = None

    def _run_cycle(self) -> None:
        cfg = self._config_manager.current
        camera = self._ensure_camera(cfg.camera)

        wb_request = self.white_balance_override.take_pending()
        if wb_request is not None:
            red_gain, blue_gain, auto = wb_request
            camera.set_white_balance(red_gain, blue_gain, auto)

        sky_state = self._refresh_sky_state()
        program = self._current_program(cfg)
        interval_s = self._interval(cfg, sky_state)
        self._run_interval_s = interval_s
        ctx = CaptureContext(
            driver=self,
            config=cfg,
            sky=sky_state,
            program_name=program.name,
            state=self._program_state,
            params=dict(cfg.capture.params.get(program.name.removesuffix(".py"), {})),
            exposure_controller=self._exposure_controller,
            commanded=self._commanded,
            camera_fresh=self._camera_fresh,
            overrides=Overrides(manual_exposure=self.manual_exposure.get()),
            stream_mode=self.stream_mode.enabled,
            interval_s=interval_s,
            slot=self._program_runs,
            max_captures=int(program.meta.get("max_captures", DEFAULT_MAX_CAPTURES)),
            capabilities=camera.capabilities,
        )
        self._camera_fresh = False
        longest = max(p.exposure_us_max for p in cfg.exposure_policy.presets.values()) / 1e6
        timeout_s = timeout_for(program, interval_s, longest)
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        # Last resort for a program stuck without ever awaiting (a CPU loop):
        # the per-capture watchdog never arms in that case.
        hard_limit = threading.Timer(timeout_s + 120.0, self._program_hung, args=(program,))
        hard_limit.daemon = True
        hard_limit.start()
        try:
            capture_set = run_once(self._loop, program, ctx, timeout_s)
        except ProgramStopped:
            return
        except CaptureProgramError as exc:
            self._program_failed(program, exc, cfg)
            capture_set = None
        else:
            self._program_failures = 0
        finally:
            hard_limit.cancel()
            self._program_runs += 1
            self._commanded = ctx.commanded
        if ctx.captures == 0:
            # Nothing captured (or failed before capturing): still use up
            # the slot, so a broken program can't spin.
            self._next_due = self._wait_for_slot(interval_s, 0.0) + interval_s
        self._frame_period(cfg, sky_state, self._commanded)

        if capture_set is not None:
            self._submit(cfg, capture_set, self._provenance(cfg, program, ctx.params, camera))

    def _provenance(self, cfg: AppConfig, program: LoadedProgram, params: dict, camera: CameraBackend) -> dict:
        """What produced a frame — enough to reproduce or audit it."""
        caps = camera.capabilities
        return {
            "capture_program": program.name,
            "capture_program_sha256": program.sha256,
            "capture_program_origin": program.origin,
            "capture_program_fallback": self._fallback_active,
            "params": params,
            "caelum_version": __version__,
            "camera_model": caps.model or None,
            "camera_backend": type(camera).__name__,
            "camera_capabilities": caps.to_dict(),
            "config_sha256": hashlib.sha256(cfg.model_dump_json().encode()).hexdigest(),
        }

    def _submit(self, cfg: AppConfig, capture_set: CaptureSet, provenance: dict) -> None:
        submissions = build_submissions(cfg, capture_set, provenance, self._storage_policy)
        if len(submissions) == 1:
            self._frame_sink.submit(submissions[0])
        else:
            self._frame_sink.submit_set(submissions)


def build_submissions(
    cfg: AppConfig, capture_set: CaptureSet, provenance: dict, storage_policy: StoragePolicy
) -> list[FrameSubmission]:
    """One `FrameSubmission` per frame of the set; with more than one frame
    each carries its `capture_set` record (see `FrameMetadata.capture_set`)."""
    primary = capture_set.primary
    single = len(capture_set.frames) == 1
    set_time = primary.raw.captured_at
    common = {
        "id": capture_set.id,
        "kind": capture_set.kind,
        "count": len(capture_set.frames),
        "representative": capture_set.representative,
        "representative_captured_at": set_time.isoformat(),
    }
    submissions = []
    for position, frame in enumerate(capture_set.frames):
        is_primary = frame is primary
        entry = None
        if not single:
            entry = {**common, "index": position, "role": "representative" if is_primary else "member"}
            if is_primary:
                entry["members"] = [
                    _member_summary(f, i, f is primary, set_time) for i, f in enumerate(capture_set.frames)
                ]
        annotations = dict(frame.annotations)
        if is_primary and capture_set.annotations:
            annotations["set"] = dict(capture_set.annotations)
        decision = storage_policy.decide(frame.sky, cfg.storage_policy)
        submissions.append(
            FrameSubmission(
                raw=frame.raw,
                sky_state=SkyStateModel.from_skystate(frame.sky),
                save_raw=decision.save_raw,
                settings=ProcessingSettings.from_config(cfg, frame.sky.period),
                brightness=frame.brightness,
                exposure_control=frame.exposure_control,
                provenance=provenance,
                capture_set=entry,
                annotations=annotations or None,
            )
        )
    return submissions


def _member_summary(frame, position: int, is_primary: bool, set_time) -> dict:
    if is_primary:
        stem = paths.timestamp_stem(set_time)
    else:
        stem = f"{paths.set_dir_name(set_time)}/{paths.member_stem(set_time, position)}"
    return {
        "index": position,
        "file_stem": stem,
        "captured_at": frame.raw.captured_at.isoformat(),
        "exposure_us": frame.raw.exposure_us,
        "analogue_gain": frame.raw.analogue_gain,
        "brightness_median": frame.brightness.median,
    }


class _UnalignedDriver:
    """A test run captures straight away — never waits for a grid slot."""

    def __init__(self, worker: CaptureWorker) -> None:
        self._worker = worker

    def capture_for_program(self, req: CaptureRequest, align_to_slot: bool) -> tuple[RawFrame, SkyState]:
        return self._worker.capture_for_program(req, align_to_slot=False)

    def stop_requested(self) -> bool:
        return self._worker.stop_requested()


_BUILTIN_DEFAULT: LoadedProgram | None = None


def _builtin_default_provider(_cfg: AppConfig) -> LoadedProgram:
    global _BUILTIN_DEFAULT
    if _BUILTIN_DEFAULT is None:
        _BUILTIN_DEFAULT = builtin_program("default.py")
    return _BUILTIN_DEFAULT
