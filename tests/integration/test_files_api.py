"""File browser and recordings manager, including the containment rule."""

from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from caelum.storage import browse

from .test_api_endpoints import VIEWER_PASSWORD, _build_harness, login


def _seed(data_dir, date: str = "2026-03-14") -> None:
    """A day of output shaped exactly like the capture pipeline writes it."""
    thumbnails = data_dir / "thumbnails" / date
    raws = data_dir / "raw" / date
    derivatives = data_dir / "derivatives" / date
    for directory in (thumbnails, raws, derivatives):
        directory.mkdir(parents=True, exist_ok=True)

    for time_token in ("201500", "203000"):
        (thumbnails / f"{time_token}.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 64)
        (thumbnails / f"{time_token}.json").write_text('{"exposure_us": 1000}')
    (raws / "203000.fits").write_bytes(b"SIMPLE  =" + b" " * 100)
    (derivatives / "keogram.png").write_bytes(b"\x89PNG" + b"0" * 32)


async def test_directory_listing_and_usage(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "filestest1")
    _seed(harness.data_dir)
    try:
        async with harness.client() as client:
            await login(client)

            root = (await client.get("/api/files")).json()
            assert {e["name"] for e in root["entries"]} == {"thumbnails", "raw", "derivatives"}
            assert root["parent"] is None
            assert all(e["kind"] == "dir" for e in root["entries"])

            day = (await client.get("/api/files", params={"path": "thumbnails/2026-03-14"})).json()
            assert day["parent"] == "thumbnails"
            names = {e["name"]: e for e in day["entries"]}
            assert names["201500.jpg"]["media"] == "image"
            assert names["201500.json"]["media"] == "json"

            usage = (await client.get("/api/files/usage")).json()
            assert usage["by_subdir"]["thumbnails"] > 0
            assert usage["disk_total_bytes"] > 0
    finally:
        await harness.config_manager.stop()


@pytest.mark.parametrize(
    "path",
    ["../../etc", "/etc/passwd", "thumbnails/../../..", "thumbnails/../../etc/passwd"],
)
async def test_path_traversal_is_refused(tmp_path, redis_url, path):
    harness = await _build_harness(tmp_path, redis_url, f"filestest2{abs(hash(path)) % 1000}")
    try:
        async with harness.client() as client:
            await login(client)
            resp = await client.get("/api/files", params={"path": path})
            assert resp.status_code in (400, 404)
            # An error detail may echo the path back; what must never appear
            # is a listing of anything outside the data directory.
            assert "entries" not in resp.text
            assert "root:" not in resp.text
    finally:
        await harness.config_manager.stop()


def test_resolve_within_rejects_escaping_symlinks(tmp_path):
    """`resolve()` follows links before the containment check, so a symlink
    planted inside the data directory cannot be used to read outside it."""
    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    (root / "escape").symlink_to(outside)

    with pytest.raises(browse.PathOutsideRoot):
        browse.resolve_within(root, "escape")


async def test_download_and_delete(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "filestest3")
    _seed(harness.data_dir)
    try:
        async with harness.client() as client:
            await login(client)

            content = await client.get(
                "/api/files/content", params={"path": "thumbnails/2026-03-14/201500.json"}
            )
            assert content.status_code == 200
            assert content.json() == {"exposure_us": 1000}

            deleted = await client.delete("/api/files", params={"path": "thumbnails/2026-03-14/201500.jpg"})
            assert deleted.status_code == 200
            assert not (harness.data_dir / "thumbnails/2026-03-14/201500.jpg").exists()

            # The data directory itself is not deletable.
            assert (await client.delete("/api/files", params={"path": ""})).status_code == 400
    finally:
        await harness.config_manager.stop()


async def test_fits_preview_renders_png(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "filestest4")
    raw_dir = harness.data_dir / "raw" / "2026-03-14"
    raw_dir.mkdir(parents=True)
    # (channels, height, width), matching storage/raw_writer.py.
    data = np.random.default_rng(0).integers(0, 4096, size=(3, 64, 96), dtype=np.uint16)
    fits.PrimaryHDU(data=data).writeto(raw_dir / "203000.fits")

    try:
        async with harness.client() as client:
            await login(client)
            resp = await client.get(
                "/api/files/preview", params={"path": "raw/2026-03-14/203000.fits", "max_dim": 64}
            )
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/png"
            assert resp.content[:4] == b"\x89PNG"

            # Not every file is renderable, and that is a 415 not a crash.
            (harness.data_dir / "notes.txt").write_text("hello")
            assert (await client.get("/api/files/preview", params={"path": "notes.txt"})).status_code == 415
    finally:
        await harness.config_manager.stop()


async def test_frames_manager_groups_and_deletes_captures(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "filestest5")
    _seed(harness.data_dir)
    try:
        async with harness.client() as client:
            await login(client)

            dates = (await client.get("/api/frames/dates")).json()
            assert len(dates) == 1
            assert dates[0]["date"] == "2026-03-14"
            assert (dates[0]["thumbnails"], dates[0]["raws"], dates[0]["derivatives"]) == (2, 1, 1)

            listing = (await client.get("/api/frames", params={"date": "2026-03-14"})).json()
            frames = {f["time"]: f for f in listing["frames"]}
            # One capture is three files in three directories; the manager
            # presents it as a single row.
            assert frames["203000"]["thumbnail"] == "thumbnails/2026-03-14/203000.jpg"
            assert frames["203000"]["raw"] == "raw/2026-03-14/203000.fits"
            assert frames["203000"]["metadata"] == "thumbnails/2026-03-14/203000.json"
            assert frames["201500"]["raw"] is None
            assert frames["203000"]["captured_at"].startswith("2026-03-14T20:30:00")
            assert [d["name"] for d in listing["derivatives"]] == ["keogram.png"]

            single = await client.request(
                "DELETE", "/api/frames", json={"date": "2026-03-14", "times": ["201500"]}
            )
            assert single.json()["files_removed"] == 2  # jpg + json sidecar
            assert not (harness.data_dir / "thumbnails/2026-03-14/201500.jpg").exists()
            assert (harness.data_dir / "thumbnails/2026-03-14/203000.jpg").exists()

            whole_day = await client.request("DELETE", "/api/frames", json={"date": "2026-03-14"})
            assert whole_day.json()["files_removed"] == 4
            assert (await client.get("/api/frames/dates")).json() == []

            assert (
                await client.request("DELETE", "/api/frames", json={"date": "not-a-date"})
            ).status_code == 400
    finally:
        await harness.config_manager.stop()


async def test_viewers_can_read_but_not_delete(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "filestest6")
    _seed(harness.data_dir)
    try:
        async with harness.client() as client:
            await login(client, "viewer1", VIEWER_PASSWORD)
            assert (await client.get("/api/frames", params={"date": "2026-03-14"})).status_code == 200
            resp = await client.request("DELETE", "/api/frames", json={"date": "2026-03-14"})
            assert resp.status_code == 403
            assert (harness.data_dir / "thumbnails/2026-03-14/201500.jpg").exists()
    finally:
        await harness.config_manager.stop()
