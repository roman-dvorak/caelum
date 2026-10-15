"""Fixed exposure: the same exposure and gain every slot.

Params (`capture.params.fixed`):
    exposure_us     exposure time in microseconds (default: the current one)
    analogue_gain   analogue gain (default: the current one)
    colour_gains    optional [red, blue] white-balance gains
"""

from caelum.control.exposure import ExposureTarget

PROGRAM = {"description": "Fixed exposure and gain from params", "kind": "single"}


async def capture(ctx):
    params = ctx.params
    exposure_us = int(params.get("exposure_us", ctx.commanded.exposure_us))
    gain = float(params.get("analogue_gain", ctx.commanded.analogue_gain))
    frame = await ctx.capture(exposure_us=exposure_us, analogue_gain=gain, colour_gains=params.get("colour_gains"))
    ctx.commanded = ExposureTarget(exposure_us=exposure_us, analogue_gain=gain)
    return frame
