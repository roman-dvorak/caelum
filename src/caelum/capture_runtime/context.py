"""What a capture program sees: the `ctx` passed to `capture(ctx)`."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from caelum.cameras.base import CameraCapabilities, CaptureRequest, RawFrame
from caelum.capture.brightness import BrightnessSample, measure
from caelum.config.schema import AppConfig
from caelum.control.exposure import ExposureController, ExposureTarget
from caelum.control.skystate import SkyState

from .errors import ProgramStopped, TooManyCaptures


@dataclass
class CapturedFrame:
    """One frame a program took: the camera's frame plus what Caelum
    measured on it. Return it (or a list of them) from `capture()` to keep
    it; frames not returned are discarded."""

    raw: RawFrame
    brightness: BrightnessSample
    #: Sky state at the moment of the capture.
    sky: SkyState
    #: What the program asked for (what the camera really did is in
    #: `raw.capture_settings`).
    requested: CaptureRequest
    #: Index of this frame within the program's run (0, 1, ...).
    index: int
    #: The exposure regulator's record for this frame, if the program ran it
    #: (the default program does) — stored in the frame's metadata.
    exposure_control: dict | None = None
    #: Free-form notes from the program, stored in the frame's metadata.
    annotations: dict = field(default_factory=dict)


class CaptureDriver(Protocol):
    """The worker side of `ctx.capture()` — owns the camera and the grid."""

    def capture_for_program(self, req: CaptureRequest, align_to_slot: bool) -> tuple[RawFrame, SkyState]: ...

    def stop_requested(self) -> bool: ...


@dataclass
class Overrides:
    """Operator overrides a program may honour (the default program does)."""

    manual_exposure: ExposureTarget | None = None


class CaptureContext:
    def __init__(
        self,
        *,
        driver: CaptureDriver,
        config: AppConfig,
        sky: SkyState,
        program_name: str,
        state: dict,
        params: dict,
        exposure_controller: ExposureController,
        commanded: ExposureTarget,
        camera_fresh: bool,
        overrides: Overrides,
        stream_mode: bool,
        interval_s: float,
        slot: int,
        max_captures: int,
        capabilities: CameraCapabilities | None = None,
    ) -> None:
        self._driver = driver
        #: Snapshot of the app config for this run.
        self.config = config
        #: Sky state when the run started (each frame has its own `sky`).
        self.sky = sky
        #: Survives across runs of the same program (reset when it changes).
        self.state = state
        #: `capture.params[<program>]` from the config.
        self.params = params
        self.exposure_controller = exposure_controller
        #: The exposure/gain to use next — read it, and set it for the next
        #: run; the worker reports it as the current target.
        self.commanded = commanded
        #: True on the first run after the camera was (re)opened.
        self.camera_fresh = camera_fresh
        self.overrides = overrides
        self.stream_mode = stream_mode
        self.interval_s = interval_s
        #: How many runs this program has had since it was loaded.
        self.slot = slot
        #: What the camera can do. Requests beyond it aren't refused — they
        #: are clamped/ignored and recorded with the frame.
        self.capabilities = capabilities
        self.log = logging.getLogger(f"caelum.capture_program.{program_name.removesuffix('.py')}")
        self._max_captures = max_captures
        self._captures = 0
        #: A camera failure inside `capture()` — re-raised by the worker even
        #: if the program swallowed it, so camera recovery still happens.
        self.camera_error: BaseException | None = None

    @property
    def captures(self) -> int:
        return self._captures

    async def capture(
        self,
        exposure_us: int,
        analogue_gain: float = 1.0,
        *,
        colour_gains: tuple[float, float] | None = None,
        raw: bool = True,
        **extra: Any,
    ) -> CapturedFrame:
        """Take one frame. The first capture of a run is aligned to the
        capture grid (the middle of its exposure on the slot); later ones
        are taken straight away.

        The camera does as much of the request as it can: values beyond its
        ranges are clamped, options it doesn't have (incl. any `extra`
        keyword) are ignored — `frame.raw.capture_settings` says which."""
        if self._driver.stop_requested():
            raise ProgramStopped
        if self._captures >= self._max_captures:
            raise TooManyCaptures(f"more than {self._max_captures} captures in one run")
        req = CaptureRequest(
            exposure_us=int(exposure_us),
            analogue_gain=float(analogue_gain),
            colour_gains=tuple(colour_gains) if colour_gains is not None else None,
            raw=raw,
            extra=extra,
        )
        index = self._captures
        self._captures += 1
        try:
            frame_raw, sky = self._driver.capture_for_program(req, align_to_slot=index == 0)
        except ProgramStopped:
            raise
        except BaseException as exc:
            self.camera_error = exc
            raise
        sample = measure(frame_raw.image, self.config.exposure_policy.brightness_roi_diameter_frac)
        return CapturedFrame(raw=frame_raw, brightness=sample, sky=sky, requested=req, index=index)

    def capture_set(
        self,
        frames: list[CapturedFrame],
        kind: str = "series",
        representative: CapturedFrame | int | None = None,
        **annotations: Any,
    ):
        """Group frames into one capture set — return it from `capture()`.
        `representative` (a frame or its position in `frames`, default the
        first) stands for the set wherever one frame per slot is shown."""
        from .capture_set import CaptureSet

        frames = list(frames)
        if isinstance(representative, CapturedFrame):
            index = next((i for i, f in enumerate(frames) if f is representative), None)
            if index is None:
                raise ValueError("representative is not one of the frames")
        else:
            index = representative or 0
        return CaptureSet(frames=frames, kind=kind, representative=index, annotations=annotations)

    async def sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while (remaining := deadline - time.monotonic()) > 0:
            if self._driver.stop_requested():
                raise ProgramStopped
            await asyncio.sleep(min(remaining, 0.5))
