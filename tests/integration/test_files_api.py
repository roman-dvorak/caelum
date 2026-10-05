"""File browser and recordings manager, including the containment rule."""

from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from caelum.storage import browse

from .test_api_endpoints import VIEWER_PASSWORD, _build_harness, login


def _seed(data_dir, date: str = "2026-03-14") -> None:
    """A day of output shaped exactly like the capture pipeline writes it —
    nested YYYY/MM/DD directories, YYYYMMDD-HHMMSS (UTC) filenames."""
    date_path = date.replace("-", "/")
    stem_date = date.replace("-", "")
    thumbnails = data_dir / "thumbnails" / date_path
    raws = data_dir / "raw" / date_path
    derivatives = data_dir / "derivatives" / date_path
    for directory in (thumbnails, raws, derivatives):
        directory.mkdir(parents=True, exist_ok=True)

    for time_token in ("201500", "203000"):
        stem = f"{stem_date}-{time_token}"
        (thumbnails / f"{stem}.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 64)
        (thumbnails / f"{stem}.json").write_text('{"exposure_us": 1000}')
    (raws / f"{stem_date}-203000.fits").write_bytes(b"SIMPLE  =" + b" " * 100)
    keogram_dir = derivatives / "keogram"
    keogram_dir.mkdir(parents=True, exist_ok=True)
    keogram_stem = f"{stem_date}-235959_keogram_keogram"
    (keogram_dir / f"{keogram_stem}.png").write_bytes(b"\x89PNG" + b"0" * 32)
    (keogram_dir / f"{keogram_stem}_thumb.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 16)


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

            day = (await client.get("/api/files", params={"path": "thumbnails/2026/03/14"})).json()
            assert day["parent"] == "thumbnails/2026/03"
            names = {e["name"]: e for e in day["entries"]}
            assert names["20260314-201500.jpg"]["media"] == "image"
            assert names["20260314-201500.json"]["media"] == "json"

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
                "/api/files/content", params={"path": "thumbnails/2026/03/14/20260314-201500.json"}
            )
            assert content.status_code == 200
            assert content.json() == {"exposure_us": 1000}

            deleted = await client.delete(
                "/api/files", params={"path": "thumbnails/2026/03/14/20260314-201500.jpg"}
            )
            assert deleted.status_code == 200
            assert not (harness.data_dir / "thumbnails/2026/03/14/20260314-201500.jpg").exists()

            # The data directory itself is not deletable.
            assert (await client.delete("/api/files", params={"path": ""})).status_code == 400
    finally:
        await harness.config_manager.stop()


async def test_fits_preview_renders_png(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "filestest4")
    raw_dir = harness.data_dir / "raw" / "2026" / "03" / "14"
    raw_dir.mkdir(parents=True)
    # (channels, height, width), matching storage/raw_writer.py.
    data = np.random.default_rng(0).integers(0, 4096, size=(3, 64, 96), dtype=np.uint16)
    fits.PrimaryHDU(data=data).writeto(raw_dir / "20260314-203000.fits")

    try:
        async with harness.client() as client:
            await login(client)
            resp = await client.get(
                "/api/files/preview",
                params={"path": "raw/2026/03/14/20260314-203000.fits", "max_dim": 64},
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
            # 2: the full keogram plus its companion thumbnail — both count
            # as derivative files for this summary.
            assert (dates[0]["thumbnails"], dates[0]["raws"], dates[0]["derivatives"]) == (2, 1, 2)

            listing = (await client.get("/api/frames", params={"date": "2026-03-14"})).json()
            frames = {f["time"]: f for f in listing["frames"]}
            # One capture is three files in three directories; the manager
            # presents it as a single row, keyed by its full UTC stem.
            assert frames["20260314-203000"]["thumbnail"] == "thumbnails/2026/03/14/20260314-203000.jpg"
            assert frames["20260314-203000"]["raw"] == "raw/2026/03/14/20260314-203000.fits"
            assert frames["20260314-203000"]["metadata"] == "thumbnails/2026/03/14/20260314-203000.json"
            assert frames["20260314-201500"]["raw"] is None
            assert frames["20260314-203000"]["captured_at"].startswith("2026-03-14T20:30:00")

            kinds = (await client.get("/api/frames/derivative-kinds", params={"date": "2026-03-14"})).json()
            assert kinds == [{"kind": "keogram", "count": 1}]

            derivatives = (
                await client.get("/api/frames/derivatives", params={"date": "2026-03-14", "kind": "keogram"})
            ).json()
            assert derivatives["total"] == 1
            entry = derivatives["entries"][0]
            assert entry["full"] == "derivatives/2026/03/14/keogram/20260314-235959_keogram_keogram.png"
            assert entry["thumbnail"] == "derivatives/2026/03/14/keogram/20260314-235959_keogram_keogram_thumb.jpg"

            single = await client.request(
                "DELETE", "/api/frames", json={"times": ["20260314-201500"]}
            )
            assert single.json()["files_removed"] == 2  # jpg + json sidecar
            assert not (harness.data_dir / "thumbnails/2026/03/14/20260314-201500.jpg").exists()
            assert (harness.data_dir / "thumbnails/2026/03/14/20260314-203000.jpg").exists()

            whole_day = await client.request("DELETE", "/api/frames", json={"date": "2026-03-14"})
            assert whole_day.json()["files_removed"] == 5
            assert (await client.get("/api/frames/dates")).json() == []

            assert (
                await client.request("DELETE", "/api/frames", json={"date": "not-a-date"})
            ).status_code == 400
            assert (await client.request("DELETE", "/api/frames", json={})).status_code == 400
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
            assert (harness.data_dir / "thumbnails/2026/03/14/20260314-201500.jpg").exists()
    finally:
        await harness.config_manager.stop()


async def test_frames_pagination(tmp_path, redis_url):
    """limit/offset slice the (time-sorted) frame list and total_frames
    reflects the unpaginated count."""
    harness = await _build_harness(tmp_path, redis_url, "filestest7")
    thumbs = harness.data_dir / "thumbnails" / "2026" / "03" / "14"
    thumbs.mkdir(parents=True)
    for hour in range(5):
        (thumbs / f"20260314-{hour:02d}0000.jpg").write_bytes(b"\xff\xd8\xff")
    try:
        async with harness.client() as client:
            await login(client)
            page1 = (
                await client.get("/api/frames", params={"date": "2026-03-14", "limit": 2, "offset": 0})
            ).json()
            page2 = (
                await client.get("/api/frames", params={"date": "2026-03-14", "limit": 2, "offset": 2})
            ).json()
            assert page1["total_frames"] == 5
            assert [f["time"] for f in page1["frames"]] == ["20260314-000000", "20260314-010000"]
            assert [f["time"] for f in page2["frames"]] == ["20260314-020000", "20260314-030000"]
    finally:
        await harness.config_manager.stop()


async def test_observation_night_spans_utc_midnight(tmp_path, redis_url):
    """A session running late on one UTC date and into the next (the normal
    case anywhere east of Greenwich) must show up as one observation night,
    not split across two — the whole point of night-mode grouping. Also
    proves a night-mode selection deletes correctly with no `date` field,
    since each capture's own stem carries its date."""
    harness = await _build_harness(tmp_path, redis_url, "filestest8")
    # Prague in December: night runs roughly 15:00 UTC to 07:00 UTC, so
    # these two timestamps are both deep night regardless of the exact
    # sunrise second, on either side of the UTC date boundary between them.
    evening = harness.data_dir / "thumbnails" / "2026" / "12" / "20"
    early_morning = harness.data_dir / "thumbnails" / "2026" / "12" / "21"
    evening.mkdir(parents=True)
    early_morning.mkdir(parents=True)
    (evening / "20261220-230000.jpg").write_bytes(b"\xff\xd8\xff")
    (early_morning / "20261221-030000.jpg").write_bytes(b"\xff\xd8\xff")
    try:
        async with harness.client() as client:
            await login(client)
            nights = (await client.get("/api/frames/nights")).json()
            matching = [n for n in nights if n["thumbnails"] == 2]
            assert len(matching) == 1, f"expected one night with both frames, got {nights}"
            night_label = matching[0]["date"]

            listing = (await client.get("/api/frames", params={"night": night_label})).json()
            stems = {f["time"] for f in listing["frames"]}
            assert stems == {"20261220-230000", "20261221-030000"}

            deleted = await client.request("DELETE", "/api/frames", json={"times": list(stems)})
            assert deleted.json()["files_removed"] == 2
            assert not evening.joinpath("20261220-230000.jpg").exists()
            assert not early_morning.joinpath("20261221-030000.jpg").exists()
    finally:
        await harness.config_manager.stop()


async def test_webp_thumbnails_and_dng_raws_are_recognised(tmp_path, redis_url):
    """New captures are .webp + .dng; older .jpg/.fits ones keep working
    side by side (see test_frames_manager_groups_and_deletes_captures)."""
    import cv2

    harness = await _build_harness(tmp_path, redis_url, "filestest6")
    day = "2026/10/03"
    thumbnails = harness.data_dir / "thumbnails" / day
    raws = harness.data_dir / "raw" / day
    thumbnails.mkdir(parents=True)
    raws.mkdir(parents=True)
    ok, webp = cv2.imencode(".webp", np.full((48, 64, 3), 128, dtype=np.uint8))
    assert ok
    (thumbnails / "20261003-010203.webp").write_bytes(webp.tobytes())
    (thumbnails / "20261003-010203.json").write_text('{"exposure_us": 1000}')
    (raws / "20261003-010203.dng").write_bytes(b"II*\x00" + b"0" * 64)
    try:
        async with harness.client() as client:
            await login(client)

            dates = (await client.get("/api/frames/dates")).json()
            assert (dates[0]["thumbnails"], dates[0]["raws"]) == (1, 1)

            frames = (await client.get("/api/frames", params={"date": "2026-10-03"})).json()["frames"]
            assert frames[0]["thumbnail"] == "thumbnails/2026/10/03/20261003-010203.webp"
            assert frames[0]["raw"] == "raw/2026/10/03/20261003-010203.dng"

            listing = (await client.get("/api/files", params={"path": "raw/2026/10/03"})).json()
            assert listing["entries"][0]["media"] == "raw"

            # A DNG previews as its capture's stored thumbnail.
            preview = await client.get(
                "/api/files/preview", params={"path": "raw/2026/10/03/20261003-010203.dng", "max_dim": 64}
            )
            assert preview.status_code == 200
            assert preview.headers["content-type"] == "image/png"

            content = await client.get("/api/files/content", params={"path": "raw/2026/10/03/20261003-010203.dng"})
            assert content.headers["content-type"] == "image/x-adobe-dng"
    finally:
        await harness.config_manager.stop()


async def test_live_frame_raw_download(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "filestest7")
    raws = harness.data_dir / "raw" / "2026" / "10" / "03"
    raws.mkdir(parents=True)
    (raws / "20261003-010203.dng").write_bytes(b"II*\x00dng")
    try:
        async with harness.client() as client:
            await login(client, "viewer1", VIEWER_PASSWORD)

            found = await client.get("/api/frame/raw", params={"captured_at": "2026-10-03T01:02:03.456789+00:00"})
            assert found.status_code == 200
            assert found.content == b"II*\x00dng"
            assert found.headers["content-type"] == "image/x-adobe-dng"
            assert "20261003-010203.dng" in found.headers["content-disposition"]

            missing = await client.get("/api/frame/raw", params={"captured_at": "2026-10-03T01:05:00+00:00"})
            assert missing.status_code == 404
    finally:
        await harness.config_manager.stop()
