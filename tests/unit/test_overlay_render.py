from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from caelum.capture.metadata import FrameMetadata, SkyStateModel
from caelum.derivatives.overlay import OverlayElementDef
from caelum.derivatives.overlay_render import rasterize


def _metadata() -> FrameMetadata:
    return FrameMetadata(
        captured_at=datetime(2026, 9, 20, tzinfo=UTC),
        exposure_us=1_000_000,
        analogue_gain=1.0,
        sky_state=SkyStateModel(
            sun_altitude_deg=-30.0,
            sun_azimuth_deg=180.0,
            moon_altitude_deg=10.0,
            moon_azimuth_deg=90.0,
            moon_illumination=0.5,
            period="night",
        ),
        focus_score=0.0,
    )


def _blank_image(width: int = 100, height: int = 100) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def test_rasterize_preserves_shape_and_dtype(tmp_path):
    image = _blank_image()
    mask = OverlayElementDef(id="m1", kind="mask", x=0.1, y=0.1, w=0.2, h=0.2, color="#ff0000", opacity=1.0)
    out = rasterize(image, [mask], _metadata(), tmp_path)
    assert out.shape == image.shape
    assert out.dtype == image.dtype


def test_mask_changes_only_pixels_inside_its_box(tmp_path):
    image = _blank_image()
    mask = OverlayElementDef(id="m1", kind="mask", x=0.1, y=0.1, w=0.2, h=0.2, color="#ff0000", opacity=1.0)
    out = rasterize(image, [mask], _metadata(), tmp_path)

    # Inside the mask box (fully opaque red) -> changed from black.
    inside = out[15, 15]
    assert not np.array_equal(inside, [0, 0, 0])

    # Outside the mask box -> untouched.
    outside = out[90, 90]
    assert np.array_equal(outside, [0, 0, 0])


def test_label_element_does_not_raise_and_renders_something(tmp_path):
    image = _blank_image()
    label = OverlayElementDef(
        id="l1", kind="label", x=0.1, y=0.1, color="#00ff00", template="Exp: {exposure_us}us"
    )
    out = rasterize(image, [label], _metadata(), tmp_path)
    # Some pixel near the label's anchor should no longer be pure black.
    region = out[8:20, 8:80]
    assert region.max() > 0


def test_bad_element_is_skipped_not_fatal(tmp_path):
    image = _blank_image()
    # kind="image" with a missing asset file — must be skipped cleanly.
    broken = OverlayElementDef(id="i1", kind="image", x=0.0, y=0.0, w=0.5, h=0.5, asset="does-not-exist.png")
    out = rasterize(image, [broken], _metadata(), tmp_path)
    assert out.shape == image.shape
