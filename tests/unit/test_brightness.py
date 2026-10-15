from __future__ import annotations

import numpy as np
import pytest

from caelum.capture.brightness import circle_mask, measure


@pytest.mark.parametrize("height,width", [(300, 400), (400, 300), (240, 240)])
def test_circle_diameter_is_the_fraction_of_the_shorter_side(height, width):
    mask = circle_mask(height, width, 0.8)
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    expected = 0.8 * min(height, width)
    assert rows.size == pytest.approx(expected, abs=2)
    assert cols.size == pytest.approx(expected, abs=2)
    # Centred.
    assert (rows[0] + rows[-1]) / 2 == pytest.approx((height - 1) / 2, abs=1)
    assert (cols[0] + cols[-1]) / 2 == pytest.approx((width - 1) / 2, abs=1)


def test_corners_and_border_do_not_affect_the_median():
    h, w = 480, 640
    image = np.full((h, w, 3), 255, dtype=np.uint8)  # blown-out border and corners
    yy, xx = np.ogrid[0:h, 0:w]
    inside = (yy - (h - 1) / 2) ** 2 + (xx - (w - 1) / 2) ** 2 <= (0.8 * h / 2 - 4) ** 2
    image[inside] = 50
    sample = measure(image, diameter_frac=0.8)
    assert sample.median == pytest.approx(50.0)


def test_median_ignores_a_few_bright_stars():
    image = np.full((400, 400, 3), 30, dtype=np.uint8)
    rng = np.random.default_rng(1)
    for _ in range(200):
        y, x = rng.integers(100, 300, size=2)
        image[y : y + 2, x : x + 2] = 255
    sample = measure(image)
    assert sample.median == pytest.approx(30.0)
    assert sample.p99 >= 30.0


def test_works_on_grayscale_and_tiny_frames():
    assert measure(np.full((20, 30), 77, dtype=np.uint8)).median == pytest.approx(77.0)
    assert measure(np.full((2, 2, 3), 9, dtype=np.uint8)).median == pytest.approx(9.0)
