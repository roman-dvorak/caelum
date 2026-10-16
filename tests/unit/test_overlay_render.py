from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from caelum.capture.metadata import OverlayElement
from caelum.derivatives.overlay_render import composite, composite_bgr, format_exposure, render_layer


def _alpha(layer) -> np.ndarray:
    return np.asarray(layer)[:, :, 3]


def _bbox(layer) -> tuple[int, int, int, int]:
    return layer.getchannel("A").getbbox()


def test_empty_list_gives_a_fully_transparent_layer_of_the_requested_size():
    layer = render_layer([], (320, 240))
    assert layer.mode == "RGBA"
    assert layer.size == (320, 240)
    assert _alpha(layer).max() == 0


@pytest.mark.parametrize(
    ("element", "region"),
    [
        (OverlayElement(type="custom_label", payload={"x": 0.0, "y": 0.0, "text": "Top left", "align": "left",
                                                      "valign": "top", "background": "#000000"}),
         (slice(0, 40), slice(0, 160))),
        (OverlayElement(type="custom_label", payload={"x": 1.0, "y": 1.0, "text": "Bottom right", "align": "right",
                                                      "valign": "bottom"}),
         (slice(200, 240), slice(160, 320))),
        (OverlayElement(type="detection_box", payload={"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2, "label": "meteor"}),
         (slice(80, 160), slice(110, 210))),
        (OverlayElement(type="telescope_marker", payload={"x": 0.5, "y": 0.5, "label": "T"}),
         (slice(110, 140), slice(150, 170))),
    ],
)
def test_every_known_type_draws_where_it_belongs(element, region):
    layer = render_layer([element], (320, 240))
    alpha = _alpha(layer)
    assert alpha[region].max() > 0
    # ...and only there: blank everything in the region out, nothing remains.
    alpha = alpha.copy()
    alpha[region] = 0
    assert alpha.max() == 0


def test_mask_fills_exactly_its_box_with_its_opacity():
    mask = OverlayElement(
        type="mask", payload={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "color": "#ff0000", "opacity": 0.5}
    )
    layer = np.asarray(render_layer([mask], (100, 100)))
    assert tuple(layer[15, 15]) == (255, 0, 0, 128)
    assert layer[5, 5, 3] == 0
    assert layer[35, 35, 3] == 0


def test_label_align_puts_the_anchor_on_the_left_middle_or_right_edge():
    def bbox(align: str) -> tuple[int, int, int, int]:
        label = OverlayElement(type="custom_label", payload={"x": 0.5, "y": 0.5, "text": "Hello", "align": align})
        return _bbox(render_layer([label], (400, 200)))

    left, center, right = bbox("left"), bbox("center"), bbox("right")
    assert abs(left[0] - 200) <= 2
    assert abs(right[2] - 200) <= 2
    assert center[0] < 200 < center[2]


def test_label_valign_puts_the_anchor_on_the_top_middle_or_bottom_edge():
    def bbox(valign: str) -> tuple[int, int, int, int]:
        label = OverlayElement(type="custom_label", payload={"x": 0.5, "y": 0.5, "text": "Hi\nthere", "valign": valign})
        return _bbox(render_layer([label], (400, 200)))

    top, middle, bottom = bbox("top"), bbox("middle"), bbox("bottom")
    assert abs(top[1] - 100) <= 3
    assert abs(bottom[3] - 100) <= 3
    assert middle[1] < 100 < middle[3]


def test_label_background_is_a_box_the_text_sits_inside():
    plain = OverlayElement(type="custom_label", payload={"x": 0.0, "y": 0.0, "text": "Hi", "align": "left",
                                                         "valign": "top"})
    boxed = OverlayElement(type="custom_label", payload={**plain.payload, "background": "#ff0000",
                                                         "background_opacity": 1.0})
    plain_box, boxed_box = _bbox(render_layer([plain], (400, 200))), _bbox(render_layer([boxed], (400, 200)))
    assert boxed_box[0] == 0 and boxed_box[1] == 0  # the box, not the glyphs, sits on the anchor
    assert boxed_box[2] > plain_box[2] and boxed_box[3] > plain_box[3]
    corner = np.asarray(render_layer([boxed], (400, 200)))[2, 4]
    assert tuple(corner) == (255, 0, 0, 255)


def test_builtin_logo_resolves_without_an_upload(tmp_path):
    payload = {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5, "asset": "astrometers-logo.png"}
    layer = render_layer([OverlayElement(type="custom_image", payload=payload)], (200, 200), tmp_path)
    assert _alpha(layer).max() == 255


def test_label_newlines_render_as_lines():
    one = OverlayElement(type="custom_label", payload={"x": 0.5, "y": 0.5, "text": "A"})
    two = OverlayElement(type="custom_label", payload={"x": 0.5, "y": 0.5, "text": "A\nA"})
    h1 = _bbox(render_layer([one], (400, 200)))
    h2 = _bbox(render_layer([two], (400, 200)))
    assert (h2[3] - h2[1]) > 1.8 * (h1[3] - h1[1])


def test_font_size_is_relative_to_the_image_width():
    label = OverlayElement(type="custom_label", payload={"x": 0.5, "y": 0.5, "text": "Hello", "font_size_px": 20})
    small = _bbox(render_layer([label], (1024, 512)))
    large = _bbox(render_layer([label], (2048, 1024)))
    ratio = (large[2] - large[0]) / (small[2] - small[0])
    assert 1.8 < ratio < 2.2


def test_custom_image_is_fitted_into_its_box(tmp_path):
    Image.new("RGBA", (10, 10), (0, 255, 0, 255)).save(tmp_path / "logo.png")
    payload = {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.25, "asset": "logo.png"}
    element = OverlayElement(type="custom_image", payload=payload)
    layer = render_layer([element], (200, 200), tmp_path)
    # A square asset in a 100x50 box: 50x50, centred horizontally.
    assert _bbox(layer) == (25, 0, 75, 50)


def test_missing_asset_unknown_type_and_bad_payload_are_skipped_not_fatal(tmp_path):
    elements = [
        OverlayElement(type="custom_image", payload={"x": 0, "y": 0, "w": 0.5, "h": 0.5, "asset": "nope.png"}),
        OverlayElement(type="some_plugin_thing", payload={"foo": 1}),
        OverlayElement(type="mask", payload={"x": "bad"}),
        OverlayElement(type="mask", payload={"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}),
    ]
    layer = render_layer(elements, (100, 100), tmp_path)
    assert _bbox(layer) == (0, 0, 10, 10)


def test_unknown_type_shaped_like_a_box_is_outlined():
    element = OverlayElement(type="cloud", payload={"x": 0.2, "y": 0.5, "w": 0.2, "h": 0.2})
    assert _alpha(render_layer([element], (100, 100)))[60:70, 20:22].max() > 0


def test_composite_burns_the_layer_in_and_keeps_shape():
    image = np.zeros((50, 100, 3), dtype=np.uint8)
    mask = OverlayElement(type="mask", payload={"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0, "color": "#0000ff"})
    layer = render_layer([mask], (100, 50))
    rgb = composite(image, layer)
    assert rgb.shape == image.shape and rgb.dtype == np.uint8
    assert tuple(rgb[10, 10]) == (0, 0, 255)
    assert tuple(rgb[10, 90]) == (0, 0, 0)
    assert tuple(composite_bgr(image, layer)[10, 10]) == (255, 0, 0)


def test_format_exposure_matches_the_ui():
    assert format_exposure(15_000_000) == "15.00s"
    assert format_exposure(2_500) == "2.5ms"
    assert format_exposure(300) == "300µs"
