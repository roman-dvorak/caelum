"""HDR bracket around the automatic exposure.

The middle frame is exactly what `default.py` would take (the PI regulator
keeps steering it), and it represents the set everywhere one frame per slot
is shown. Around it, frames at the EV offsets in `ev_steps`; with `adaptive`
the darker ones are only taken when the middle frame has clipped highlights
and the brighter ones only when it is darker than the target — so on an
evenly lit sky the slot costs a single exposure.

Params (`capture.params.hdr`):
    ev_steps    EV offsets from the middle frame (default [-2, 0, 2]; 0 is implied)
    adaptive    skip brackets the middle frame doesn't need (default true)
    clip_adu    p99 level (0-255) counted as clipped highlights (default 250)

The camera clamps exposures it can't do; that is recorded per frame.
Keep the number of frames within `processing.slots` or the set is dropped.
"""

from caelum.capture_programs import default
from caelum.config.schema import FULL_SCALE_ADU

PROGRAM = {"description": "HDR bracket around the automatic exposure", "kind": "hdr", "max_captures": 7}


async def capture(ctx):
    params = ctx.params
    steps = sorted({float(s) for s in params.get("ev_steps", [-2, 0, 2])} | {0.0})
    adaptive = bool(params.get("adaptive", True))
    clip_adu = float(params.get("clip_adu", 250))

    middle = await default.capture(ctx)
    preset = ctx.config.exposure_policy.preset_for(middle.sky.period)
    target_adu = FULL_SCALE_ADU * 2.0**preset.target_ev
    clipped = middle.brightness.p99 >= clip_adu
    dark = middle.brightness.median < target_adu

    frames = []
    for ev in steps:
        if ev == 0:
            frames.append(middle)
            continue
        if adaptive and ((ev < 0 and not clipped) or (ev > 0 and not dark)):
            continue
        frame = await ctx.capture(
            exposure_us=max(1, round(middle.raw.exposure_us * 2.0**ev)), analogue_gain=middle.raw.analogue_gain
        )
        frame.annotations["ev"] = ev
        frames.append(frame)
    middle.annotations["ev"] = 0.0
    if len(frames) == 1:
        return middle
    ctx.log.info("bracket %s EV around %d us", [f.annotations["ev"] for f in frames], middle.raw.exposure_us)
    return ctx.capture_set(frames, kind="hdr", representative=middle, ev_steps=[f.annotations["ev"] for f in frames])
