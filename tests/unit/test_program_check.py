from __future__ import annotations

from caelum.cameras.base import CameraCapabilities
from caelum.capture_runtime.check import check, static_check
from caelum.capture_runtime.program import builtin_source
from caelum.config.schema import AppConfig

CAPS = CameraCapabilities(max_resolution=(4056, 3040), model="imx477", exposure_us=(110, 1_000_000),
                          analogue_gain=(1.0, 16.0), raw=True, colour_gains=True)


def _levels(report):
    return [(i["level"], i["line"]) for i in report["issues"]]


def test_static_check_finds_structure_errors_without_running():
    assert static_check("a.py", "async def capture(ctx)\n")[0]["line"] == 1
    assert "async def" in static_check("a.py", "def capture(ctx):\n    pass\n")[0]["message"]
    issues = static_check("a.py", "import os\nos.system('touch /tmp/x')\n")
    assert issues[0]["level"] == "error"


def test_default_program_passes():
    report = check("default.py", builtin_source("default.py"), AppConfig(), CAPS)
    assert report["ok"], report["issues"]
    assert len(report["simulation"]["runs"]) == 2


def test_runtime_error_is_reported_with_its_line():
    source = (
        'PROGRAM = {"description": "x"}\n\n'
        "async def capture(ctx):\n"
        "    await ctx.capture(exposure_us=100)\n"
        "    1 / 0\n"
    )
    report = check("bad.py", source, AppConfig(), CAPS)
    assert not report["ok"]
    assert ("error", 5) in _levels(report)


def test_import_error_is_reported():
    report = check("bad.py", "import does_not_exist\nasync def capture(ctx):\n    pass\n", AppConfig(), CAPS)
    assert not report["ok"]
    assert "does_not_exist" in report["issues"][-1]["message"]


def test_camera_limits_are_information_not_errors():
    source = (
        'PROGRAM = {"description": "x"}\n\n'
        "async def capture(ctx):\n"
        "    return await ctx.capture(exposure_us=60_000_000, analogue_gain=40, binning=2)\n"
    )
    report = check("big.py", source, AppConfig(), CAPS)
    assert report["ok"], report["issues"]
    info = [i["message"] for i in report["issues"] if i["level"] == "info"]
    assert any("clamped exposure_us, analogue_gain" in m for m in info)
    assert any("ignored extra.binning" in m for m in info)


def test_printing_program_does_not_break_the_report():
    source = 'PROGRAM = {"description": "x"}\nprint("hello")\nasync def capture(ctx):\n    print("run")\n'
    assert check("p.py", source, AppConfig(), CAPS)["ok"]
