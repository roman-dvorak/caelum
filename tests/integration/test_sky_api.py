from __future__ import annotations

import cv2
import numpy as np

from tests.factories import make_processed_frame

from .test_api_endpoints import _build_harness, login


def _disc_frame():
    image = np.zeros((300, 400, 3), np.uint8)
    cv2.circle(image, (210, 150), 140, (40, 40, 40), -1)
    return make_processed_frame(image=image)


async def test_sky_objects_are_projected_for_the_latest_frame(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "sky1")
    try:
        async with harness.client() as client:
            await login(client)
            body = (await client.get("/api/sky/objects", params={"max_mag": 2.0})).json()
            assert body["aspect"] > 0
            names = {o["name"] for o in body["objects"]}
            assert names & {"Sun", "Moon", "Saturn", "Sirius", "Vega", "Capella", "Arcturus", "Rigel"}
            assert all(0 <= o["x"] <= 1 and 0 <= o["y"] <= 1 for o in body["objects"])
    finally:
        await harness.config_manager.stop()


async def test_projecting_with_a_lens_from_the_request_moves_the_objects(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "sky2")
    try:
        async with harness.client() as client:
            await login(client)
            lens = (await client.get("/api/sky/objects")).json()["lens"]

            async def project(body_lens):
                response = await client.post("/api/sky/objects", json={"lens": body_lens, "max_mag": 1.0})
                return {o["name"]: o for o in response.json()["objects"]}

            base = await project(lens)
            turned = await project({**lens, "azimuth_offset_deg": 180.0})
            shared = [n for n in base if n in turned and base[n]["alt_deg"] > 20]
            assert shared
            name = shared[0]
            assert abs(base[name]["x"] - 0.5) > 0.01 or abs(base[name]["y"] - 0.5) > 0.01
            # rotating by 180 degrees mirrors the position through the centre
            assert abs((base[name]["x"] - 0.5) + (turned[name]["x"] - 0.5)) < 0.01
    finally:
        await harness.config_manager.stop()


async def test_lens_tools_need_a_frame_and_an_admin(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "sky3")
    try:
        async with harness.client() as anonymous:
            assert (await anonymous.post("/api/camera/lens/detect-circle")).status_code in (401, 403)
        async with harness.client() as client:
            await login(client)
            assert (await client.post("/api/camera/lens/detect-circle")).status_code == 409  # nothing captured yet

            harness.frame_store.update(_disc_frame())
            circle = (await client.post("/api/camera/lens/detect-circle")).json()
            assert abs(circle["center_x"] * 400 - 210) < 4
            assert abs(circle["radius_px"] - 140) < 5

            # A disc without stars: the fit explains why it cannot.
            fit = await client.post("/api/camera/lens/fit-stars", json={})
            assert fit.status_code == 422 and "stars" in fit.json()["detail"]
    finally:
        await harness.config_manager.stop()


async def test_sky_setup_gives_the_browser_the_lens_and_the_observers_position(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "sky_setup")
    try:
        async with harness.client() as client:
            await login(client)
            body = (await client.get("/api/sky/setup")).json()
            config = harness.config_manager.current
            assert body["lens"] == config.camera.lens.model_dump()
            assert (body["lat"], body["lon"]) == (config.location.lat, config.location.lon)
    finally:
        await harness.config_manager.stop()
