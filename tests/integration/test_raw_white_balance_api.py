"""White balance edited against a stored RAW frame."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from tests.factories import make_raw_bayer, make_raw_config

from .test_api_endpoints import VIEWER_PASSWORD, _build_harness, login

pytest.importorskip("pidng")

from caelum.storage import dng_reader, dng_writer  # noqa: E402


def _seed_dng(data_dir, stem: str, seed: int = 0):
    when = datetime.strptime(stem, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    data = dng_writer.build_dng(
        make_raw_bayer(seed),
        make_raw_config(),
        {"ExposureTime": 1_000_000, "AnalogueGain": 2.0, "ColourGains": [1.8, 1.6]},
        captured_at=when,
        exposure_us=1_000_000,
        analogue_gain=2.0,
        xmp_fields={"colour_gains": "1.8000,1.6000"},
    )
    path = data_dir / "raw" / when.strftime("%Y/%m/%d") / f"{stem}.dng"
    dng_writer.write(path, data)
    return path


async def test_latest_raw_frame_is_loaded_and_retagged(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "rawwb1")
    _seed_dng(harness.data_dir, "20260313-230000")
    latest = _seed_dng(harness.data_dir, "20260314-013000", seed=1)
    original = latest.read_bytes()
    try:
        async with harness.client() as client:
            await login(client)

            info = (await client.get("/api/raw/white-balance")).json()
            assert info["path"] == "raw/2026/03/14/20260314-013000.dng"
            assert info["red_gain"] == pytest.approx(1.8, abs=1e-3)
            assert info["blue_gain"] == pytest.approx(1.6, abs=1e-3)
            assert info["captured_red_gain"] == pytest.approx(1.8)

            pixels = await client.get("/api/raw/white-balance/pixels", params={"path": info["path"]})
            assert pixels.status_code == 200
            width, height = int(pixels.headers["x-width"]), int(pixels.headers["x-height"])
            assert (width, height) == (info["width"], info["height"])
            assert len(pixels.content) == width * height * 3 * 2

            saved = await client.put(
                "/api/raw/white-balance", json={"path": info["path"], "red_gain": 2.2, "blue_gain": 1.4}
            )
            assert saved.status_code == 200
            assert saved.json()["red_gain"] == pytest.approx(2.2, abs=1e-4)
            assert saved.json()["as_shot_neutral"] == pytest.approx([1 / 2.2, 1.0, 1 / 1.4], abs=1e-5)

            patched = latest.read_bytes()
            before, after = dng_reader.parse(original), dng_reader.parse(patched)
            np.testing.assert_array_equal(dng_reader.bayer(patched, after), dng_reader.bayer(original, before))
    finally:
        await harness.config_manager.stop()


async def test_paths_are_confined_and_must_be_dngs(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "rawwb2")
    try:
        async with harness.client() as client:
            await login(client)
            assert (await client.get("/api/raw/white-balance")).status_code == 404  # nothing stored yet
            outside = await client.get("/api/raw/white-balance", params={"path": "../../etc/passwd"})
            assert outside.status_code == 400
            (harness.data_dir / "notes.txt").write_text("hi")
            assert (await client.get("/api/raw/white-balance", params={"path": "notes.txt"})).status_code == 404
    finally:
        await harness.config_manager.stop()


async def test_viewers_cannot_use_it(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "rawwb3")
    path = _seed_dng(harness.data_dir, "20260314-013000")
    try:
        async with harness.client() as client:
            await login(client, "viewer1", VIEWER_PASSWORD)
            assert (await client.get("/api/raw/white-balance")).status_code == 403
            denied = await client.put(
                "/api/raw/white-balance",
                json={"path": "raw/2026/03/14/20260314-013000.dng", "red_gain": 2.0, "blue_gain": 2.0},
            )
            assert denied.status_code == 403
            assert dng_reader.read_info(path).gains == pytest.approx((1.8, 1.6), abs=1e-3)
    finally:
        await harness.config_manager.stop()
