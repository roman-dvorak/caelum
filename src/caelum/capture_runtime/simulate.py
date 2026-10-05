"""Running a program against a simulated camera — for Check, and tests.

The simulated camera is the mock backend with the real camera's
capabilities, so the report shows what the real one would clamp or ignore.
Nothing waits for slots and nothing is stored."""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from datetime import UTC, datetime
from typing import Any

from caelum.cameras.base import CameraCapabilities, CaptureRequest, RawFrame
from caelum.cameras.mock_backend import MockCameraBackend
from caelum.config.schema import AppConfig
from caelum.control.exposure import ExposureController, ExposureTarget
from caelum.control.skystate import SkyState

from .context import CaptureContext, Overrides
from .errors import ProgramStopped
from .program import LoadedProgram
from .runner import DEFAULT_MAX_CAPTURES, run_once


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{record.levelname} {record.getMessage()}")


class SimulatedDriver:
    def __init__(self, camera: MockCameraBackend, sky: SkyState) -> None:
        self.camera = camera
        self.sky = sky

    def capture_for_program(self, req: CaptureRequest, align_to_slot: bool) -> tuple[RawFrame, SkyState]:
        record = self.camera.apply_request(req)
        return self.camera.finish_request(self.camera.capture_frame(), record), self.sky

    def stop_requested(self) -> bool:
        return False


def simulated_sky(period: str = "night") -> SkyState:
    altitude = {"day": 30.0, "civil_twilight": -3.0, "nautical_twilight": -9.0,
                "astronomical_twilight": -15.0}.get(period, -30.0)
    return SkyState(timestamp=datetime.now(UTC), sun_altitude_deg=altitude, sun_azimuth_deg=0.0,
                    moon_altitude_deg=-10.0, moon_azimuth_deg=0.0, moon_illumination=0.0, period=period)


def simulate(
    program: LoadedProgram,
    config: AppConfig,
    capabilities: CameraCapabilities | None = None,
    runs: int = 2,
    period: str = "night",
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Run `program` `runs` times (state carried over, as in production)
    and report every request, what the camera made of it and what was
    returned. Never raises for program errors — they are in the report."""
    camera = MockCameraBackend()
    if capabilities is not None:
        camera.capabilities = capabilities
    camera.open()
    sky = simulated_sky(period)
    driver = SimulatedDriver(camera, sky)
    handler = _ListHandler()
    log = logging.getLogger(f"caelum.capture_program.{program.name.removesuffix('.py')}")
    log.addHandler(handler)
    loop = asyncio.new_event_loop()
    state: dict = {}
    controller = ExposureController()
    commanded = ExposureTarget(exposure_us=10_000, analogue_gain=1.0)
    report: dict[str, Any] = {"ok": True, "period": period, "runs": [], "log": handler.lines}
    try:
        for slot in range(runs):
            ctx = CaptureContext(
                driver=driver, config=config, sky=sky, program_name=program.name, state=state,
                params=dict(config.capture.params.get(program.name.removesuffix(".py"), {})),
                exposure_controller=controller, commanded=commanded, camera_fresh=slot == 0,
                overrides=Overrides(), stream_mode=False, interval_s=60.0, slot=slot,
                max_captures=int(program.meta.get("max_captures", DEFAULT_MAX_CAPTURES)),
                capabilities=camera.capabilities,
            )
            started = time.monotonic()
            entry: dict[str, Any] = {"slot": slot}
            try:
                result = run_once(loop, program, ctx, float(program.meta.get("timeout_s") or timeout_s))
            except ProgramStopped:
                break
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                entry["error"] = describe_error(exc, program)
                report["ok"] = False
                report["runs"].append(entry)
                break
            commanded = ctx.commanded
            entry["captures"] = ctx.captures
            entry["duration_s"] = round(time.monotonic() - started, 3)
            if result is None:
                entry["returned"] = None
            else:
                entry["returned"] = {
                    "kind": result.kind,
                    "count": len(result.frames),
                    "representative": result.representative,
                    "annotations": result.annotations,
                    "frames": [_frame_summary(f) for f in result.frames],
                }
            entry["next_commanded"] = {"exposure_us": commanded.exposure_us, "analogue_gain": commanded.analogue_gain}
            report["runs"].append(entry)
    finally:
        log.removeHandler(handler)
        loop.close()
        camera.close()
    return report


def _frame_summary(frame) -> dict[str, Any]:
    settings = frame.raw.capture_settings or {}
    return {
        "index": frame.index,
        "requested": settings.get("requested"),
        "applied": settings.get("applied"),
        "clamped": settings.get("clamped", []),
        "ignored": settings.get("ignored", []),
        "brightness_median": round(frame.brightness.median, 2),
        "annotations": frame.annotations,
    }


def describe_error(exc: BaseException, program: LoadedProgram) -> dict[str, Any]:
    """The error with the line of the program it came from, if any."""
    filename = f"<capture-program {program.name}>"
    line = None
    cause = exc.__cause__ or exc
    for frame in traceback.extract_tb(cause.__traceback__):
        if frame.filename == filename:
            line = frame.lineno
    return {
        "message": str(exc),
        "type": type(cause).__name__,
        "line": line,
        "traceback": "".join(traceback.format_exception(cause)),
    }
