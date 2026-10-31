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


async def test_fit_pairs_solves_the_lens_from_marked_stars(tmp_path, redis_url):
    import math

    from caelum.sky.lens_fit import Lens, project_to_pixels

    truth = Lens(
        0.5, 0.5, 0.45, fov_deg=182.0, azimuth_offset_deg=-30.0, mirror=True, tilt_deg=4.0, tilt_azimuth_deg=100.0
    )
    size = (1600, 1200)
    rng = np.random.default_rng(3)
    alt, az = rng.uniform(15, 85, 10), rng.uniform(0, 360, 10)
    xy = project_to_pixels(alt, az, truth, size)
    pairs = [{"alt_deg": float(a), "az_deg": float(z), "x": float(x / size[0]), "y": float(y / size[1])}
             for a, z, (x, y) in zip(alt, az, xy, strict=True)]

    harness = await _build_harness(tmp_path, redis_url, "sky4")
    try:
        async with harness.client() as client:
            await login(client)
            start = (await client.get("/api/sky/setup")).json()["lens"]
            body = {
                "lens": {**start, "center_x": 0.5, "center_y": 0.5, "radius": 0.45, "mirror": True},
                "pairs": pairs,
                "free": ["roll", "tilt", "fov"],
                "image_width": size[0],
                "image_height": size[1],
            }
            response = await client.post("/api/camera/lens/fit-pairs", json=body)
            assert response.status_code == 200, response.text
            fit = response.json()
            assert fit["rms_px"] < 0.5 and len(fit["errors_px"]) == 10
            assert math.isclose(fit["lens"]["tilt_deg"], 4.0, abs_tol=0.1)
            assert math.isclose(fit["lens"]["fov_deg"], 182.0, abs_tol=0.2)

            too_few = await client.post("/api/camera/lens/fit-pairs", json={**body, "pairs": pairs[:2]})
            assert too_few.status_code == 422 and "too few" in too_few.json()["detail"]
    finally:
        await harness.config_manager.stop()


def _minimal_dng(xmp: bytes, width: int = 16, height: int = 12) -> bytes:
    """The smallest DNG `dng_reader` accepts: uncompressed 16-bit CFA, one strip, an XMP packet."""
    import struct

    pixels = (np.random.default_rng(0).integers(300, 2000, (height, width))).astype("<u2").tobytes()
    entries = 11
    xmp_at = 8 + 2 + entries * 12 + 4
    strip_at = xmp_at + len(xmp) + (len(xmp) & 1)
    short, long_, byte = 3, 4, 1
    rows = [
        (256, long_, 1, width), (257, long_, 1, height), (258, short, 1, 16), (259, short, 1, 1),
        (273, long_, 1, strip_at), (279, long_, 1, len(pixels)), (700, byte, len(xmp), xmp_at),
        (33421, short, 2, 2 | (2 << 16)), (33422, byte, 4, 2 | (1 << 8) | (1 << 16) | (0 << 24)),
        (50714, short, 1, 256), (50717, short, 1, 4095),
    ]
    ifd = struct.pack("<H", len(rows)) + b"".join(struct.pack("<HHLL", *row) for row in rows) + struct.pack("<L", 0)
    return b"II*\x00" + struct.pack("<L", 8) + ifd + xmp + (b"\0" if len(xmp) & 1 else b"") + pixels


async def test_stored_frame_gives_time_and_place_and_refuses_what_is_not_a_dng(tmp_path, redis_url):
    xmp = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
           b'<rdf:Description xmlns:caelum="https://caelum.astrometers.eu/ns/1.0/" '
           b'caelum:captured_at="2026-10-30T00:48:40+00:00" caelum:latitude_deg="49.9736" '
           b'caelum:longitude_deg="14.4378" caelum:elevation_m="200.0"/></rdf:RDF></x:xmpmeta>')
    harness = await _build_harness(tmp_path, redis_url, "sky5")
    try:
        directory = tmp_path / "data" / "raw" / "2026" / "10" / "30"
        directory.mkdir(parents=True)
        (directory / "frame.dng").write_bytes(_minimal_dng(xmp))
        (directory / "no-metadata.dng").write_bytes(_minimal_dng(b"<x:xmpmeta/>"))
        (directory / "notes.txt").write_text("hello")
        async with harness.client() as client:
            await login(client)
            ok = await client.get("/api/camera/lens/stored-frame", params={"path": "raw/2026/10/30/frame.dng"})
            assert ok.status_code == 200, ok.text
            info = ok.json()
            assert info["captured_at"].startswith("2026-10-30T00:48:40")
            assert (info["lat"], info["lon"], info["elevation_m"]) == (49.9736, 14.4378, 200.0)
            assert (info["width"], info["height"]) == (16, 12)
            image = await client.get(
                "/api/camera/lens/stored-frame/image", params={"path": "raw/2026/10/30/frame.dng"}
            )
            assert image.status_code == 200 and image.headers["content-type"] == "image/png"

            async def status(path: str, who=client) -> int:
                return (await who.get("/api/camera/lens/stored-frame", params={"path": path})).status_code

            nothing = await client.get(
                "/api/camera/lens/stored-frame", params={"path": "raw/2026/10/30/no-metadata.dng"}
            )
            assert nothing.status_code == 422 and "time and position" in nothing.json()["detail"]
            assert await status("raw/none.dng") == 404
            assert await status("raw/2026/10/30/notes.txt") == 415
            assert await status("../../etc/passwd") == 400
        async with harness.client() as anonymous:
            assert await status("x.dng", anonymous) in (401, 403)
    finally:
        await harness.config_manager.stop()


async def test_remote_frame_is_fetched_once_then_served_like_a_stored_one(tmp_path, redis_url, monkeypatch):
    from caelum.api.routes import sky

    xmp = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
           b'<rdf:Description xmlns:caelum="https://caelum.astrometers.eu/ns/1.0/" '
           b'caelum:captured_at="2026-10-30T00:48:40+00:00" caelum:latitude_deg="49.9" '
           b'caelum:longitude_deg="14.4"/></rdf:RDF></x:xmpmeta>')
    downloads: list[str] = []

    def fake_download(url, target):
        downloads.append(url)
        target.write_bytes(b"not a dng" if url.endswith("bad.dng") else _minimal_dng(xmp))

    monkeypatch.setattr(sky, "_download", fake_download)
    harness = await _build_harness(tmp_path, redis_url, "sky6")
    try:
        async with harness.client() as client:
            await login(client)
            link = "https://archive.example.org/raw/2026/10/30/frame.dng"
            first = await client.post("/api/camera/lens/remote-frame", json={"url": link})
            assert first.status_code == 200, first.text
            info = first.json()
            assert info["captured_at"].startswith("2026-10-30T00:48:40") and info["path"].startswith("lens-frames/")
            again = await client.post("/api/camera/lens/remote-frame", json={"url": link})
            assert again.json()["path"] == info["path"] and downloads == [link]
            image = await client.get("/api/camera/lens/stored-frame/image", params={"path": info["path"]})
            assert image.status_code == 200

            plain = await client.post("/api/camera/lens/remote-frame", json={"url": "http://example.org/a.dng"})
            assert plain.status_code == 422
            bad = await client.post("/api/camera/lens/remote-frame", json={"url": "https://example.org/bad.dng"})
            assert bad.status_code == 422
            kept = list((tmp_path / "data" / "lens-frames").glob("*.dng"))
            assert len(kept) == 1  # the rejected file was not kept
    finally:
        await harness.config_manager.stop()
