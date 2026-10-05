"""Caelum's automatic exposure: one frame per slot, the PI regulator in EV
(`caelum.control.exposure`) deciding the next exposure and gain.

Honours the operator's manual exposure override; leaving it, regulation
continues from the manual setting.
"""

from caelum.control.exposure import ExposureTarget, exposure_control_snapshot

PROGRAM = {
    "description": "Automatic exposure (PI regulator in EV)",
    "kind": "single",
}


async def capture(ctx):
    controller = ctx.exposure_controller
    policy = ctx.config.exposure_policy
    manual = ctx.overrides.manual_exposure

    if ctx.camera_fresh:
        # A freshly opened camera knows nothing of our last exposure: start
        # from the manual setting, the middle of the preset's range (very
        # first start), or wherever we were.
        if manual is not None:
            start = manual
        elif controller.diagnostics is None:
            start = controller.initial_target(ctx.sky.period, policy)
        else:
            start = ctx.commanded
        controller.prime(start, ctx.sky.period)
        ctx.commanded = start

    frame = await ctx.capture(exposure_us=ctx.commanded.exposure_us, analogue_gain=ctx.commanded.analogue_gain)
    applied = ExposureTarget(exposure_us=frame.raw.exposure_us, analogue_gain=frame.raw.analogue_gain)

    if manual is not None:
        next_target = manual
        controller.track(manual, frame.brightness, applied, frame.sky.period, policy)
    else:
        if ctx.state.get("was_manual"):
            controller.reset()
        next_target = controller.step(frame.brightness, applied, frame.sky.period, policy)
    ctx.state["was_manual"] = manual is not None

    ctx.commanded = next_target
    frame.exposure_control = exposure_control_snapshot(controller.diagnostics)
    return frame
