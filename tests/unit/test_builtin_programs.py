"""Every built-in program passes Check and runs on the (mock) camera."""

from __future__ import annotations

import pytest

from caelum.cameras.base import CameraCapabilities
from caelum.capture_runtime.check import check
from caelum.capture_runtime.program import builtin_names, builtin_program, builtin_source
from caelum.capture_runtime.simulate import simulate
from caelum.config.schema import AppConfig

IMX477 = CameraCapabilities(max_resolution=(4056, 3040), model="imx477", exposure_us=(110, 694_422_939),
                            analogue_gain=(1.0, 22.26), raw=True, colour_gains=True)


def _config(**params) -> AppConfig:
    cfg = AppConfig()
    return cfg.model_copy(update={"capture": cfg.capture.model_copy(update={"params": params})})


def test_builtins_are_present():
    assert {"default.py", "fixed.py", "hdr.py", "darks.py"} <= set(builtin_names())


@pytest.mark.parametrize("name", ["default.py", "fixed.py", "hdr.py", "darks.py"])
def test_builtin_passes_check(name):
    report = check(name, builtin_source(name), AppConfig(), IMX477)
    assert report["ok"], report["issues"]
    assert not [i for i in report["issues"] if i["level"] == "warning"]


def test_fixed_uses_params_and_clamps_to_the_camera():
    report = simulate(builtin_program("fixed.py"), _config(fixed={"exposure_us": 2_000_000_000, "analogue_gain": 2}),
                      IMX477)
    frame = report["runs"][0]["returned"]["frames"][0]
    assert frame["requested"]["exposure_us"] == 2_000_000_000
    assert frame["applied"]["exposure_us"] == 694_422_939
    assert frame["clamped"] == ["exposure_us"]
    assert report["runs"][1]["next_commanded"] == {"exposure_us": 2_000_000_000, "analogue_gain": 2.0}


def test_hdr_brackets_around_the_automatic_exposure():
    report = simulate(builtin_program("hdr.py"), _config(hdr={"adaptive": False}), IMX477)
    returned = report["runs"][0]["returned"]
    assert returned["kind"] == "hdr" and returned["count"] == 3 and returned["representative"] == 1
    exposures = [f["applied"]["exposure_us"] for f in returned["frames"]]
    assert exposures[0] < exposures[1] < exposures[2]
    assert exposures[2] == pytest.approx(4 * exposures[1], rel=0.01)
    assert [f["annotations"]["ev"] for f in returned["frames"]] == [-2.0, 0.0, 2.0]


def test_adaptive_hdr_skips_brackets_it_does_not_need():
    # The mock night scene starts out clipped at the initial exposure: only
    # the darker bracket is worth taking, never the brighter one.
    report = simulate(builtin_program("hdr.py"), _config(), IMX477, runs=2)
    for run in report["runs"]:
        returned = run["returned"]
        assert [f["annotations"]["ev"] for f in returned["frames"]] == [-2.0, 0.0]
        assert returned["representative"] == 1
        assert returned["frames"][1]["brightness_median"] >= 250


def test_darks_without_raw_output_record_raw_as_ignored():
    report = simulate(builtin_program("darks.py"), _config(darks={"count": 2, "exposure_us": 5000}), None)
    returned = report["runs"][0]["returned"]
    assert returned["kind"] == "dark" and returned["count"] == 2
    assert all(f["ignored"] == ["raw"] for f in returned["frames"])
    assert returned["annotations"] == {"exposure_us": 5000, "analogue_gain": 1.0}


def test_too_many_darks_for_the_slots_is_a_check_warning():
    report = check("darks.py", builtin_source("darks.py"), _config(darks={"count": 5}), IMX477)
    assert report["ok"]
    assert any("slots" in i["message"] for i in report["issues"] if i["level"] == "warning")
