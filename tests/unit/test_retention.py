from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from caelum.config.schema import RetentionConfig, UploadConfig
from caelum.storage import retention


def _touch(path, content: bytes = b"x" * 1000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_max_age_deletes_only_files_older_than_cutoff(tmp_path):
    now = datetime(2026, 1, 10, tzinfo=UTC)
    old_path = tmp_path / "thumbnails" / "2026" / "01" / "01" / "20260101-120000.jpg"
    new_path = tmp_path / "thumbnails" / "2026" / "01" / "09" / "20260109-120000.jpg"
    _touch(old_path)
    _touch(new_path)

    cfg = RetentionConfig(max_age_days=5, min_free_space_mb=0)
    result = retention.sweep(tmp_path, cfg, UploadConfig(enabled=False), uploaded_before=None, now=now)

    assert not old_path.exists()
    assert new_path.exists()
    assert result.deleted_files == 1


def test_sidecar_is_deleted_alongside_its_image(tmp_path):
    now = datetime(2026, 1, 10, tzinfo=UTC)
    img = tmp_path / "thumbnails" / "2026" / "01" / "01" / "20260101-120000.jpg"
    _touch(img)
    img.with_suffix(".json").write_text("{}")

    cfg = RetentionConfig(max_age_days=1, min_free_space_mb=0)
    retention.sweep(tmp_path, cfg, UploadConfig(enabled=False), uploaded_before=None, now=now)

    assert not img.exists()
    assert not img.with_suffix(".json").exists()


def test_not_yet_uploaded_files_are_exempt_when_upload_enabled(tmp_path):
    now = datetime(2026, 1, 10, tzinfo=UTC)
    old_path = tmp_path / "raw" / "2026" / "01" / "01" / "20260101-120000.fits"
    _touch(old_path)

    cfg = RetentionConfig(max_age_days=1, min_free_space_mb=0)
    result = retention.sweep(tmp_path, cfg, UploadConfig(enabled=True), uploaded_before=None, now=now)

    assert old_path.exists()
    assert result.deleted_files == 0


def test_uploaded_files_older_than_watermark_are_eligible_for_deletion(tmp_path):
    now = datetime(2026, 1, 10, tzinfo=UTC)
    old_path = tmp_path / "raw" / "2026" / "01" / "01" / "20260101-120000.fits"
    _touch(old_path)

    cfg = RetentionConfig(max_age_days=1, min_free_space_mb=0)
    uploaded_before = datetime(2026, 1, 5, tzinfo=UTC)
    result = retention.sweep(tmp_path, cfg, UploadConfig(enabled=True), uploaded_before=uploaded_before, now=now)

    assert not old_path.exists()
    assert result.deleted_files == 1


def test_local_only_setup_ignores_upload_watermark_entirely(tmp_path):
    # upload disabled -> local copy is the only copy -> retention runs on
    # age/space alone, with no "not yet uploaded" exemption
    now = datetime(2026, 1, 10, tzinfo=UTC)
    old_path = tmp_path / "raw" / "2026" / "01" / "01" / "20260101-120000.fits"
    _touch(old_path)

    cfg = RetentionConfig(max_age_days=1, min_free_space_mb=0)
    result = retention.sweep(tmp_path, cfg, UploadConfig(enabled=False), uploaded_before=None, now=now)

    assert not old_path.exists()
    assert result.deleted_files == 1


def test_free_space_floor_deletes_oldest_first_until_satisfied(tmp_path):
    now = datetime(2026, 1, 10, tzinfo=UTC)
    p1 = tmp_path / "thumbnails" / "2026" / "01" / "01" / "20260101-120000.jpg"
    p2 = tmp_path / "thumbnails" / "2026" / "01" / "05" / "20260105-120000.jpg"
    p3 = tmp_path / "thumbnails" / "2026" / "01" / "09" / "20260109-120000.jpg"
    for p in (p1, p2, p3):
        _touch(p)

    # max_age never triggers here; only the free-space floor should.
    cfg = RetentionConfig(max_age_days=3650, min_free_space_mb=100)

    class _FakeUsage:
        def __init__(self, free_mb: float) -> None:
            self.free = free_mb * 1024 * 1024

    free_space_mb_sequence = iter([0, 0, 200])  # satisfied after the 3rd check

    def fake_disk_usage(_path):
        return _FakeUsage(next(free_space_mb_sequence, 200))

    with patch("caelum.storage.retention.shutil.disk_usage", side_effect=fake_disk_usage):
        result = retention.sweep(tmp_path, cfg, UploadConfig(enabled=False), uploaded_before=None, now=now)

    assert not p1.exists()
    assert not p2.exists()
    assert p3.exists()
    assert result.deleted_files == 2
