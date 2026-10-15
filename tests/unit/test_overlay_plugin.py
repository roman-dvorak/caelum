from __future__ import annotations

from datetime import UTC, datetime

from caelum.derivatives.overlay import OverlaySettings, OverlayWorker
from tests.factories import make_processed_frame


def test_mask_and_label_elements_are_built_with_interpolated_text():
    label_template = "Sky: {sky_state.period} / {exposure_us}us"
    worker = OverlayWorker(
        {
            "elements": [
                {"id": "m1", "kind": "mask", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "color": "#112233"},
                {"id": "l1", "kind": "label", "x": 0.5, "y": 0.9, "template": label_template},
            ]
        }
    )
    frame = make_processed_frame()
    elements = worker.provide_overlay_elements(frame)

    mask = next(e for e in elements if e.type == "mask")
    assert mask.payload == {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "color": "#112233", "opacity": 1.0}

    label = next(e for e in elements if e.type == "custom_label")
    assert label.payload["text"] == "Sky: night / 1000000us"


def test_bad_label_template_falls_back_to_raw_template_instead_of_crashing():
    element = {"id": "l1", "kind": "label", "x": 0.5, "y": 0.5, "template": "{no_such_field}"}
    worker = OverlayWorker({"elements": [element]})
    frame = make_processed_frame()

    elements = worker.provide_overlay_elements(frame)

    assert elements[0].payload["text"] == "{no_such_field}"


def test_flat_elements_config_migrates_into_a_default_template():
    settings = OverlaySettings.model_validate(
        {"elements": [{"id": "m1", "kind": "mask", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]}
    )

    assert settings.active_template == "Default"
    assert [t.name for t in settings.templates] == ["Default"]
    assert len(settings.active_elements()) == 1


def test_only_the_active_template_is_rendered():
    worker = OverlayWorker(
        {
            "templates": [
                {"name": "Night", "elements": [{"id": "n1", "kind": "mask", "x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}]},
                {"name": "Day", "elements": [{"id": "d1", "kind": "mask", "x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1}]},
            ],
            "active_template": "Day",
        }
    )
    frame = make_processed_frame()

    elements = worker.provide_overlay_elements(frame)

    assert len(elements) == 1
    assert elements[0].payload["x"] == 0.5


def _render(template: str, **frame_kwargs) -> str:
    worker = OverlayWorker({"elements": [{"id": "l1", "kind": "label", "x": 0.0, "y": 0.0, "template": template}]})
    return worker.provide_overlay_elements(make_processed_frame(**frame_kwargs))[0].payload["text"]


def test_label_exposure_in_seconds_with_configurable_decimals():
    assert _render("{exposure_s:.2f}s") == "1.00s"
    assert _render("{exposure_s}") == "1.0"


def test_label_field_can_be_divided():
    assert _render("{exposure_us/1000:.1f} ms") == "1000.0 ms"
    assert _render("{exposure_us/1e6:.3f}") == "1.000"


def test_label_divide_by_zero_falls_back_to_raw_template():
    assert _render("{exposure_us/0}") == "{exposure_us/0}"


def test_label_datetime_with_strftime_format():
    captured_at = datetime(2026, 10, 3, 21, 5, 9, tzinfo=UTC)
    assert _render("{captured_at:%d.%m.%Y %H:%M:%S %Z}", captured_at=captured_at) == "03.10.2026 21:05:09 UTC"


def test_label_bare_datetime_stays_iso_8601():
    captured_at = datetime(2026, 10, 3, 21, 5, 9, tzinfo=UTC)
    assert _render("{captured_at}", captured_at=captured_at) == "2026-10-03T21:05:09+00:00"


def test_label_align_and_multiline_text_reach_the_payload():
    template = "Exp: {exposure_s:.1f}s\nSky: {sky_state.period}"
    worker = OverlayWorker(
        {"elements": [{"id": "l1", "kind": "label", "x": 0.0, "y": 0.0, "template": template, "align": "left"}]}
    )
    payload = worker.provide_overlay_elements(make_processed_frame())[0].payload
    assert payload["align"] == "left"
    assert payload["text"] == "Exp: 1.0s\nSky: night"


def test_label_align_defaults_to_center():
    payload = (
        OverlayWorker({"elements": [{"id": "l1", "kind": "label", "x": 0.0, "y": 0.0, "template": "x"}]})
        .provide_overlay_elements(make_processed_frame())[0]
        .payload
    )
    assert payload["align"] == "center"
