"""Dark frames: a series at one exposure, for calibration — cover the lens
before activating (the program can't tell).

Params (`capture.params.darks`):
    count           frames per slot (default 3; at most `processing.slots`)
    exposure_us     exposure (default: the current one)
    analogue_gain   gain (default: the current one)

On a camera without raw output the frames are still taken; `raw` then shows
up among the ignored request options in their metadata.
"""

PROGRAM = {"description": "Dark-frame series for calibration (cover the lens)", "kind": "dark", "max_captures": 16}


async def capture(ctx):
    params = ctx.params
    count = max(1, int(params.get("count", 3)))
    exposure_us = int(params.get("exposure_us", ctx.commanded.exposure_us))
    gain = float(params.get("analogue_gain", ctx.commanded.analogue_gain))
    frames = []
    for i in range(count):
        frame = await ctx.capture(exposure_us=exposure_us, analogue_gain=gain, raw=True)
        frame.annotations["dark_index"] = i
        frames.append(frame)
    return ctx.capture_set(frames, kind="dark", exposure_us=exposure_us, analogue_gain=gain)
