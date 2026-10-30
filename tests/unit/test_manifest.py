from __future__ import annotations

import json
from datetime import UTC, datetime

from caelum.config.schema import AppConfig
from caelum.upload import manifest


def _config(name="Test Camera", slug="cam0", **identity) -> AppConfig:
    data = {"camera": {"identity": {"name": name, "slug": slug, **identity}}, "location": {"lat": 1.0, "lon": 2.0}}
    return AppConfig.model_validate(data)


def _touch(path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_write_local_manifests_builds_expected_camera_manifest_and_date_index(tmp_path):
    _touch(tmp_path / "thumbnails" / "2026" / "01" / "01" / "20260101-120000.jpg")
    _touch(tmp_path / "thumbnails" / "2026" / "01" / "01" / "20260101-130000.jpg")
    _touch(tmp_path / "raw" / "2026" / "01" / "01" / "20260101-130000.fits")

    camera_manifest = manifest.write_local_manifests(
        tmp_path,
        manifest.camera_identity(_config(observatory_name="Obs", camera_type="allsky", owner="Me")),
    )

    assert camera_manifest["slug"] == "cam0"
    assert (camera_manifest["observatory_name"], camera_manifest["camera_type"], camera_manifest["owner"]) == (
        "Obs", "allsky", "Me")
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


def test_date_index_points_at_a_rendered_overlay_when_there_is_one(tmp_path):
    _touch(tmp_path / "thumbnails" / "2026" / "01" / "01" / "20260101-120000.webp")
    _touch(tmp_path / "thumbnails" / "2026" / "01" / "01" / "20260101-130000.webp")
    _touch(tmp_path / "overlays" / "2026" / "01" / "01" / "20260101-130000.png")

    camera_manifest = manifest.write_local_manifests(tmp_path, manifest.camera_identity(_config()))

    assert camera_manifest["dates"][0]["thumbnail_count"] == 2
    index = json.loads((tmp_path / "thumbnails" / "2026" / "01" / "01" / "index.json").read_text())
    first, second = index["images"]
    assert "overlay" not in first
    assert second["overlay"] == "overlays/2026/01/01/20260101-130000.png"


def test_write_local_manifests_with_no_data_yet_produces_empty_dates(tmp_path):
    camera_manifest = manifest.write_local_manifests(tmp_path, manifest.camera_identity(_config()))
    assert camera_manifest["dates"] == []


def test_merge_cameras_index_preserves_other_cameras_and_keeps_own_entry_static():
    existing = {
        "version": 1,
        "cameras": [{"slug": "other-cam", "name": "Other", "manifest": "other-cam/manifest.json"}],
    }
    identity = manifest.camera_identity(_config("This Camera", owner="Me"))

    merged = manifest.merge_cameras_index(existing, identity, datetime.now(UTC))

    assert {c["slug"] for c in merged["cameras"]} == {"other-cam", "cam0"}
    this_cam = next(c for c in merged["cameras"] if c["slug"] == "cam0")
    assert this_cam["owner"] == "Me"
    assert this_cam["manifest"] == "cam0/manifest.json"
    assert "latest_thumbnail" not in this_cam


def test_merge_cameras_index_updates_own_entry_idempotently():
    first = manifest.merge_cameras_index(None, manifest.camera_identity(_config("Cam Zero")), datetime.now(UTC))
    second = manifest.merge_cameras_index(
        first, manifest.camera_identity(_config("Cam Zero Renamed")), datetime.now(UTC)
    )

    assert len(second["cameras"]) == 1
    assert second["cameras"][0]["name"] == "Cam Zero Renamed"


def test_location_is_published_only_when_asked_for():
    assert "location" not in manifest.camera_identity(_config())
    assert manifest.camera_identity(_config(publish_location=True))["location"] == {"lat": 1.0, "lon": 2.0}


def test_sky_info_carries_the_lens_only_together_with_the_location():
    assert manifest.sky_info(_config()) is None
    info = manifest.sky_info(_config(publish_location=True))
    assert info["lens"]["projection"] == "equidistant_fisheye"
    assert '"lat"' not in json.dumps(info)  # the location itself is the manifest's `location`
