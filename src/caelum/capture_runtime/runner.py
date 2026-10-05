"""Running one program call per capture slot."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

from .context import CaptureContext, CapturedFrame
from .errors import CaptureProgramError, ProgramStopped, ProgramTimeout
from .program import LoadedProgram

logger = logging.getLogger(__name__)

DEFAULT_MAX_CAPTURES = 16


def timeout_for(program: LoadedProgram, interval_s: float, longest_exposure_s: float) -> float:
    """The program's own `timeout_s`, else a generous automatic budget."""
    explicit = program.meta.get("timeout_s")
    if explicit:
        return float(explicit)
    return max(4 * interval_s, 2 * longest_exposure_s + 30.0, 30.0)


def collect_frames(result: Any, ctx: CaptureContext) -> list[CapturedFrame]:
    """What a program returned, as frames to keep: a frame, a list of
    frames, or None (= keep nothing). Anything else is a program error."""
    if result is None:
        return []
    if isinstance(result, CapturedFrame):
        return [result]
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes, dict)):
        frames = list(result)
        if all(isinstance(f, CapturedFrame) for f in frames):
            return frames
    raise CaptureProgramError(f"capture() returned {type(result).__name__}; expected frame(s) or None")


def run_once(loop: asyncio.AbstractEventLoop, program: LoadedProgram, ctx: CaptureContext, timeout_s: float):
    """Run `program.capture(ctx)` to completion on `loop` and return the
    frames to keep. Raises `ProgramStopped` on shutdown, the camera's own
    exception if the camera failed (even if the program caught it), or a
    `CaptureProgramError` (incl. any program exception) otherwise."""

    async def guarded() -> Any:
        return await asyncio.wait_for(program.capture(ctx), timeout=timeout_s)

    try:
        result = loop.run_until_complete(guarded())
    except ProgramStopped:
        raise
    except TimeoutError as exc:
        if ctx.camera_error is not None:
            raise ctx.camera_error from exc
        raise ProgramTimeout(f"{program.name} took longer than {timeout_s:.0f}s") from exc
    except CaptureProgramError:
        if ctx.camera_error is not None:
            raise ctx.camera_error from None
        raise
    except BaseException as exc:
        if ctx.camera_error is not None:
            raise ctx.camera_error from None
        raise CaptureProgramError(f"{program.name} raised {exc!r}") from exc
    if ctx.camera_error is not None:
        raise ctx.camera_error
    return collect_frames(result, ctx)
