from __future__ import annotations

import json
from datetime import UTC, datetime

from caelum.upload import manifest


def _touch(path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_write_local_manifests_builds_expected_camera_manifest_and_date_index(tmp_path):
    _touch(tmp_path / "thumbnails" / "2026" / "01" / "01" / "20260101-120000.jpg")
    _touch(tmp_path / "thumbnails" / "2026" / "01" / "01" / "20260101-130000.jpg")
    _touch(tmp_path / "raw" / "2026" / "01" / "01" / "20260101-130000.fits")

    camera_manifest = manifest.write_local_manifests(tmp_path, "cam0", "Test Camera", {"lat": 1.0, "lon": 2.0})

    assert camera_manifest["slug"] == "cam0"
    assert len(camera_manifest["dates"]) == 1
    day = camera_manifest["dates"][0]
    assert day["date"] == "2026-01-01"
    assert day["thumbnail_count"] == 2
    assert day["has_raw"] is True
    assert day["raw_count"] == 1
    assert day["latest_thumbnail"] == "thumbnails/2026/01/01/20260101-130000.jpg"

    manifest_on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest_on_disk == camera_manifest

    index = json.loads((tmp_path / "thumbnails" / "2026" / "01" / "01" / "index.json").read_text())
    assert [img["time"] for img in index["images"]] == ["20260101-120000", "20260101-130000"]


def test_write_local_manifests_with_no_data_yet_produces_empty_dates(tmp_path):
    camera_manifest = manifest.write_local_manifests(tmp_path, "cam0", "Test Camera", {})
    assert camera_manifest["dates"] == []


def test_merge_cameras_index_preserves_other_cameras(tmp_path):
    existing = {
        "version": 1,
        "cameras": [
            {"slug": "other-cam", "name": "Other", "manifest": "other-cam/manifest.json", "latest_thumbnail": None}
        ],
    }
    camera_manifest = {"dates": [{"latest_thumbnail": "thumbnails/2026/01/01/20260101-120000.jpg"}]}

    merged = manifest.merge_cameras_index(existing, "cam0", "This Camera", camera_manifest, datetime.now(UTC))

    slugs = {c["slug"] for c in merged["cameras"]}
    assert slugs == {"other-cam", "cam0"}
    this_cam = next(c for c in merged["cameras"] if c["slug"] == "cam0")
    assert this_cam["latest_thumbnail"] == "cam0/thumbnails/2026/01/01/20260101-120000.jpg"


def test_merge_cameras_index_updates_own_entry_idempotently():
    camera_manifest = {"dates": []}
    first = manifest.merge_cameras_index(None, "cam0", "Cam Zero", camera_manifest, datetime.now(UTC))
    second = manifest.merge_cameras_index(first, "cam0", "Cam Zero Renamed", camera_manifest, datetime.now(UTC))

    assert len(second["cameras"]) == 1
    assert second["cameras"][0]["name"] == "Cam Zero Renamed"
