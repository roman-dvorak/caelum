import json
import os
import time

from caelum.derivatives.thermal_format import format_thermal
from caelum.telemetry.thermal import ThermalStatusPoller, ThermalStatusSettings

STATUS = {"dome_temp": 29.86, "body_temp": 34.49, "envi_temp": 13.65, "dome_humidity": 36.5,
          "heater_pwm": 17.2, "failsafe_mode": False, "fan_override": None, "unknown_key": 1}


def _poller(path, **kw) -> ThermalStatusPoller:
    poller = ThermalStatusPoller()
    poller.configure(ThermalStatusSettings(path=str(path), **kw))
    return poller


def test_snapshot_filters_to_metadata_fields(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps(STATUS))
    poller = _poller(f, metadata_fields=["dome_temp", "failsafe_mode"])
    poller.poll_once()
    snap = poller.snapshot()
    assert snap is not None
    assert snap["dome_temp"] == 29.86 and snap["failsafe_mode"] is False
    assert "body_temp" not in snap and "age_s" in snap


def test_missing_and_corrupt_file_keep_last_reading(tmp_path):
    f = tmp_path / "s.json"
    poller = _poller(f)
    poller.poll_once()
    assert poller.snapshot() is None
    f.write_text(json.dumps(STATUS))
    poller.poll_once()
    f.write_text("{not json")
    poller.poll_once()
    assert poller.snapshot()["dome_temp"] == 29.86
    f.unlink()
    poller.poll_once()
    assert poller.snapshot() is not None


def test_stale_file_gives_no_snapshot(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps(STATUS))
    old = time.time() - 600
    os.utime(f, (old, old))
    poller = _poller(f, max_age_s=60)
    poller.poll_once()
    assert poller.snapshot() is None


def test_disabled_poller_returns_none(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps(STATUS))
    poller = _poller(f)
    poller.poll_once()
    poller.configure(None)
    assert poller.snapshot() is None


def test_format_missing_value_is_dash():
    text = format_thermal("{dome_temp:.1f} / {body_temp:.1f}", {"dome_temp": 1.25})
    assert text == "1.2 / –"


def test_format_bad_placeholder_returns_template():
    assert format_thermal("{nope}", {}) == "{nope}"


def _frame_with_thermal(thermal):
    from tests.factories import make_processed_frame

    frame = make_processed_frame()
    frame.metadata.annotations = {"thermal": thermal} if thermal else None
    return frame


def test_plugin_draws_label_from_frame_annotations():
    from caelum.derivatives.thermal_status import ThermalStatusWorker

    worker = ThermalStatusWorker({"overlay": {"template": "D {dome_temp:.1f} B {body_temp:.1f}"}})
    (element,) = worker.provide_overlay_elements(_frame_with_thermal({"dome_temp": 29.86}))
    assert element.type == "custom_label"
    assert element.payload["text"] == "D 29.9 B –"


def test_plugin_draws_nothing_without_reading_or_when_overlay_off():
    from caelum.derivatives.thermal_status import ThermalStatusWorker

    assert ThermalStatusWorker({}).provide_overlay_elements(_frame_with_thermal(None)) == []
    off = ThermalStatusWorker({"overlay": {"enabled": False}})
    assert off.provide_overlay_elements(_frame_with_thermal({"dome_temp": 1.0})) == []


def test_overlay_editor_template_can_use_thermal_placeholders():
    from caelum.derivatives.overlay import OverlayWorker

    worker = OverlayWorker({"elements": [{"id": "l", "kind": "label", "x": 0.5, "y": 0.5,
                                          "template": "{dome_temp:.1f}C {body_temp:.1f}C"}]})
    frame = _frame_with_thermal({"dome_temp": 20.0})
    text = next(e for e in worker.provide_overlay_elements(frame) if e.type == "custom_label").payload["text"]
    assert text == "20.0C –C"


def test_thermal_values_land_in_xmp_fields():
    from caelum.processing.pipeline import _thermal_xmp

    assert _thermal_xmp({"thermal": {"dome_temp": 1.5, "age_s": 2.0}}) == {
        "thermal_dome_temp": 1.5, "thermal_age_s": 2.0}
    assert _thermal_xmp(None) == {}
