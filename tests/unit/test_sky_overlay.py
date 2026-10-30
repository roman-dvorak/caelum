from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np

from caelum.config.schema import AppConfig
from caelum.derivatives import overlay_render
from caelum.derivatives.sky_overlay import SkyOverlayWorker
from caelum.sky import overlay_geometry
from tests.factories import make_image, make_processed_frame

NIGHT = datetime(2026, 10, 30, 21, 0, tzinfo=UTC)


def _worker(**settings) -> SkyOverlayWorker:
    worker = SkyOverlayWorker(settings)
    worker.config_manager = SimpleNamespace(current=AppConfig())
    return worker


def _frame(width=400, height=300):
    return make_processed_frame(captured_at=NIGHT, image=make_image(width=width, height=height, fill=0))


def _expanded(element, aspect=4 / 3):
    build = overlay_geometry.grid_payload if element.type == "sky_grid" else overlay_geometry.map_payload
    return build(element.payload["params"], aspect)


def test_draws_a_grid_with_compass_letters_and_a_star_map():
    elements = {e.type: e for e in _worker().provide_overlay_elements(_frame())}
    assert set(elements) == {"sky_grid", "sky_map"}

    letters = {label["text"] for label in _expanded(elements["sky_grid"])["labels"]}
    assert letters == {"N", "E", "S", "W"}
    assert _expanded(elements["sky_grid"])["lines"]

    stars = _expanded(elements["sky_map"])["stars"]
    assert len(stars) > 100  # roughly 1/4 of the ~330 stars to magnitude 3.5 are below the horizon
    assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y, _ in stars)
    names = {label["text"] for label in _expanded(elements["sky_map"])["labels"]}
    assert "Vega" in names or "Capella" in names  # bright, high at 21:00 UTC in late October from Prague


def test_north_is_towards_the_top_with_no_azimuth_offset_and_follows_the_offset():
    def north_xy(offset):
        worker = _worker()
        worker.config_manager.current.camera.lens.azimuth_offset_deg = offset
        grid = next(e for e in worker.provide_overlay_elements(_frame()) if e.type == "sky_grid")
        n = next(label for label in _expanded(grid)["labels"] if label["north"])
        return n["x"] - 0.5, n["y"] - 0.5

    dx, dy = north_xy(0.0)
    assert abs(dx) < 1e-3 and dy < 0  # straight up
    dx, dy = north_xy(90.0)  # the camera is turned: north is now on the east side of the image
    assert dx > 0 and abs(dy) < 1e-3


def test_stars_can_be_switched_off_and_the_overlay_still_renders():
    worker = _worker(show_stars=False, show_planets=False, show_grid=False, show_compass=False)
    assert worker.provide_overlay_elements(_frame()) == []
    only_planets = _worker(show_stars=False, show_grid=False, show_compass=False).provide_overlay_elements(_frame())
    assert [e.type for e in only_planets] == ["sky_map"] and _expanded(only_planets[0])["stars"] == []
    full = _worker().provide_overlay_elements(_frame())
    layer = overlay_render.render_layer(full, (400, 300))
    alpha = np.asarray(layer)[:, :, 3]
    assert (alpha > 0).sum() > 500  # something was actually drawn


def test_without_a_config_manager_it_contributes_nothing():
    assert SkyOverlayWorker({}).provide_overlay_elements(_frame()) == []


def test_the_sidecar_holds_parameters_not_star_positions():
    elements = _worker().provide_overlay_elements(_frame())
    size = sum(len(e.model_dump_json()) for e in elements)
    assert size < 1500
    assert all("stars" not in e.payload and "lines" not in e.payload for e in elements)
