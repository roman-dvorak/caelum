"""Capture programs: the capture logic as a swappable Python program.

A program is a module with one coroutine, `async def capture(ctx)`, run once
per capture slot by `CaptureWorker`. It takes frames through `ctx.capture()`
— as many as it likes, adapting to what it gets back — and returns what
should be kept. Caelum's own automatic exposure is just the built-in
`default` program (`caelum.capture_programs.default`); others (fixed
exposure, HDR, calibration sequences, experiments) plug in the same way.

The worker keeps owning the camera, the capture grid, stall recovery and the
frame pipeline; a program only decides *what* to capture.
"""

from .capture_set import CaptureSet
from .context import CaptureContext, CapturedFrame
from .errors import CaptureProgramError, ProgramLoadError, ProgramTimeout, TooManyCaptures
from .program import LoadedProgram, builtin_program, load_program

__all__ = [
    "CaptureContext",
    "CaptureProgramError",
    "CaptureSet",
    "CapturedFrame",
    "LoadedProgram",
    "ProgramLoadError",
    "ProgramTimeout",
    "TooManyCaptures",
    "builtin_program",
    "load_program",
]
