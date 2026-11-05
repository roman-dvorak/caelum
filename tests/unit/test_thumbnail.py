"""Thumbnail downscale ("area" vs "peak") and the WebP tone curve."""

from __future__ import annotations

import numpy as np

from caelum.capture import thumbnail


def _sky_with_star() -> np.ndarray:
    image = np.full((400, 400, 3), 20, np.uint8)
    image[201, 201] = (255, 200, 150)  # a one-pixel star
    return image


def test_area_averages_a_single_pixel_star_away():
    small = thumbnail.resize(_sky_with_star(), 100, "area")
    assert small.shape == (100, 100, 3)
    assert small.max() < 40


def test_peak_keeps_the_star_and_its_hue():
    small = thumbnail.resize(_sky_with_star(), 100, "peak")
    area = thumbnail.resize(_sky_with_star(), 100, "area")
    y, x = np.unravel_index(small.max(axis=2).argmax(), small.shape[:2])
    assert small[y, x].max() > area.max() + 50
    r, g, b = (int(v) for v in small[y, x])
    assert r > g > b


def test_peak_leaves_flat_areas_alone():
    flat = np.full((400, 400, 3), 20, np.uint8)
    assert np.array_equal(thumbnail.resize(flat, 100, "peak"), thumbnail.resize(flat, 100, "area"))


def test_no_upscaling():
    image = _sky_with_star()
    assert thumbnail.resize(image, 1024, "peak") is image


def test_gamma_one_is_identity_and_above_one_lifts_shadows():
    image = np.full((4, 4, 3), 40, np.uint8)
    assert thumbnail.apply_gamma(image, 1.0) is image
    lifted = thumbnail.apply_gamma(image, 2.0)
    assert lifted[0, 0, 0] == round(255 * (40 / 255) ** 0.5)
    assert thumbnail.apply_gamma(np.array([[0, 255]], np.uint8), 2.2).tolist() == [[0, 255]]
