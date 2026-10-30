"""Lens calibration on synthetic frames rendered from a known lens."""

from __future__ import annotations

from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

from caelum.derivatives.projection import altaz_to_fraction
from caelum.sky.lens_fit import Lens, detect_image_circle, detect_stars, fit_lens_from_stars, project_to_pixels
from caelum.sky.positions import star_positions

WHEN = datetime(2026, 10, 30, 21, 0, tzinfo=UTC)
LAT, LON = 50.0755, 14.4378
SIZE = (1600, 1200)  # 4:3


def _sky_frame(lens: Lens, noise: float = 2.0, seed: int = 0) -> np.ndarray:
    width, height = SIZE
    rng = np.random.default_rng(seed)
    frame = np.zeros((height, width), np.float32)
    cx, cy, r = lens.center_x * width, lens.center_y * height, lens.radius * min(SIZE)
    cv2.circle(frame, (round(cx), round(cy)), round(r), 12.0, -1)  # sky glow inside the disc
    stars = star_positions(WHEN, LAT, LON, max_mag=5.0)
    keep = stars.alt_deg > 3
    xy = project_to_pixels(stars.alt_deg[keep], stars.az_deg[keep], lens, SIZE)
    for (x, y), mag in zip(xy, stars.mag[keep], strict=True):
        if np.isnan(x):
            continue
        amp = 220.0 * 10 ** (-0.4 * (mag - 1.0))
        yy, xx = np.mgrid[int(y) - 4 : int(y) + 5, int(x) - 4 : int(x) + 5]
        ok = (yy >= 0) & (yy < height) & (xx >= 0) & (xx < width)
        frame[yy[ok], xx[ok]] += (amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.3**2)))[ok]
    frame += rng.normal(0, noise, frame.shape)
    return np.clip(frame, 0, 255).astype(np.uint8)


def test_numpy_projection_matches_the_scalar_one():
    lens = Lens(0.48, 0.52, 0.45, fov_deg=190.0, azimuth_offset_deg=33.0, mirror=True, projection="equisolid_fisheye")
    for alt, az in [(80.0, 10.0), (45.0, 123.0), (5.0, 300.0)]:
        expected = altaz_to_fraction(
            alt, az, center_x=lens.center_x, center_y=lens.center_y, radius=lens.radius,
            azimuth_offset_deg=lens.azimuth_offset_deg, mirror=lens.mirror, aspect=SIZE[0] / SIZE[1],
            fov_deg=lens.fov_deg, projection=lens.projection,
        )
        got = project_to_pixels(np.array([alt]), np.array([az]), lens, SIZE)[0]
        assert got[0] == pytest.approx(expected.x * SIZE[0])
        assert got[1] == pytest.approx(expected.y * SIZE[1])


def test_circle_detection_finds_a_complete_disc():
    frame = np.zeros((SIZE[1], SIZE[0]), np.uint8)
    cv2.circle(frame, (830, 590), 520, 40, -1)
    fit = detect_image_circle(frame)
    assert fit is not None and not fit.cropped
    assert fit.center_x * SIZE[0] == pytest.approx(830, abs=3)
    assert fit.center_y * SIZE[1] == pytest.approx(590, abs=3)
    assert fit.radius_px == pytest.approx(520, abs=3)
    assert fit.radius == pytest.approx(520 / SIZE[1], abs=0.003)


def test_circle_detection_handles_a_disc_cut_off_by_the_frame():
    frame = np.zeros((SIZE[1], SIZE[0]), np.uint8)
    cv2.circle(frame, (800, 600), 700, 40, -1)  # taller than the sensor
    fit = detect_image_circle(frame)
    assert fit is not None and fit.cropped
    assert fit.radius_px == pytest.approx(700, abs=6)


def test_circle_detection_gives_up_on_a_blank_frame():
    assert detect_image_circle(np.zeros((SIZE[1], SIZE[0]), np.uint8)) is None


def test_star_detection_finds_the_bright_stars():
    truth = Lens(0.5, 0.5, 0.48)
    frame = _sky_frame(truth)
    stars = detect_stars(frame, circle=(0.5 * SIZE[0], 0.5 * SIZE[1], 0.48 * SIZE[1]))
    assert len(stars) >= 30
    # Sirius-class stars are the brightest; every detection should be a real
    # blob, i.e. close to some predicted catalog position.
    catalog = star_positions(WHEN, LAT, LON, max_mag=5.0)
    predicted = project_to_pixels(catalog.alt_deg, catalog.az_deg, truth, SIZE)
    predicted = predicted[~np.isnan(predicted[:, 0])]
    nearest = np.hypot(stars[:, None, 0] - predicted[None, :, 0], stars[:, None, 1] - predicted[None, :, 1]).min(axis=1)
    assert np.median(nearest) < 1.5


@pytest.mark.parametrize("mirror", [False, True])
def test_fit_recovers_north_offset_centre_and_fov_from_stars(mirror):
    truth = Lens(0.503, 0.488, 0.47, fov_deg=186.0, azimuth_offset_deg=137.0, mirror=mirror,
                 projection="equidistant_fisheye")
    frame = _sky_frame(truth)
    circle = detect_image_circle(frame)
    assert circle is not None

    # What the UI starts from: the detected disc, nothing about north or the lens.
    initial = Lens(circle.center_x, circle.center_y, circle.radius)
    stars = detect_stars(frame, circle=(circle.center_x * SIZE[0], circle.center_y * SIZE[1], circle.radius_px))
    fit = fit_lens_from_stars(stars, SIZE, WHEN, LAT, LON, initial)

    assert fit is not None
    assert fit.matched >= 15
    assert fit.rms_px < 1.5
    assert fit.lens.mirror == mirror
    assert fit.lens.projection == "equidistant_fisheye"
    assert fit.lens.azimuth_offset_deg == pytest.approx(137.0, abs=0.6)
    assert fit.lens.center_x == pytest.approx(0.503, abs=0.001)
    assert fit.lens.center_y == pytest.approx(0.488, abs=0.001)
    assert fit.lens.fov_deg == pytest.approx(186.0, abs=1.5)
    assert fit.confidence > 0.5


def test_fit_distinguishes_the_projection():
    truth = Lens(0.5, 0.5, 0.47, fov_deg=180.0, azimuth_offset_deg=20.0, projection="equisolid_fisheye")
    frame = _sky_frame(truth)
    circle = detect_image_circle(frame)
    stars = detect_stars(frame, circle=(circle.center_x * SIZE[0], circle.center_y * SIZE[1], circle.radius_px))
    fit = fit_lens_from_stars(stars, SIZE, WHEN, LAT, LON, Lens(circle.center_x, circle.center_y, circle.radius))
    assert fit is not None
    assert fit.lens.projection == "equisolid_fisheye"


def test_fit_gives_up_when_the_frame_has_no_stars():
    noise = np.random.default_rng(3).normal(10, 2, (SIZE[1], SIZE[0])).clip(0, 255).astype(np.uint8)
    stars = detect_stars(noise)
    assert fit_lens_from_stars(stars, SIZE, WHEN, LAT, LON, Lens(0.5, 0.5, 0.48)) is None
