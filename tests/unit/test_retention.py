from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from caelum.config.schema import AppConfig, PluginConfig, RetentionConfig, UploadConfig
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


def test_sweep_timelapses_deletes_only_files_older_than_cutoff(tmp_path):
    now = datetime(2026, 1, 10, tzinfo=UTC)
    old = tmp_path / "timelapses" / "2026" / "01" / "01" / "20260101-060000_day_clean.mp4"
    new = tmp_path / "timelapses" / "2026" / "01" / "09" / "20260109-060000_day_clean.mp4"
    _touch(old)
    _touch(new)

    result = retention.sweep_timelapses(tmp_path, retention_days=5, now=now)

    assert not old.exists()
    assert new.exists()
    assert result.deleted_files == 1


def test_sweep_timelapses_zero_retention_days_keeps_everything(tmp_path):
    now = datetime(2026, 1, 10, tzinfo=UTC)
    old = tmp_path / "timelapses" / "2026" / "01" / "01" / "20260101-060000_day_clean.mp4"
    _touch(old)

    result = retention.sweep_timelapses(tmp_path, retention_days=0, now=now)

    assert old.exists()
    assert result.deleted_files == 0


def test_sweep_timelapses_ignores_files_outside_the_timelapses_dir(tmp_path):
    now = datetime(2026, 1, 10, tzinfo=UTC)
    old_raw = tmp_path / "raw" / "2026" / "01" / "01" / "20260101-060000.fits"
    _touch(old_raw)

    result = retention.sweep_timelapses(tmp_path, retention_days=1, now=now)

    assert old_raw.exists()
    assert result.deleted_files == 0


def test_sweep_timelapses_missing_directory_is_a_no_op(tmp_path):
    result = retention.sweep_timelapses(tmp_path, retention_days=5)
    assert result.deleted_files == 0


class _StubConfigManager:
    def __init__(self, config: AppConfig) -> None:
        self.current = config


def test_retention_sweeper_run_sweep_runs_both_sweeps_and_returns_live_interval(tmp_path):
    old_thumb = tmp_path / "thumbnails" / "2020" / "01" / "01" / "20200101-060000.jpg"
    old_timelapse = tmp_path / "timelapses" / "2020" / "01" / "01" / "20200101-060000_day_clean.mp4"
    _touch(old_thumb)
    _touch(old_timelapse)

    config = AppConfig()
    config.retention = RetentionConfig(max_age_days=1, min_free_space_mb=0, sweep_interval_s=42.0)
    config.upload = UploadConfig(enabled=False)
    config.plugins["timelapse"] = PluginConfig(enabled=True, order=50, settings={"retention_days": 1})

    sweeper = retention.RetentionSweeper(_StubConfigManager(config), tmp_path)
    next_delay = sweeper._run_sweep()

    assert not old_thumb.exists()
    assert not old_timelapse.exists()
    assert next_delay == 42.0


def test_retention_sweeper_run_sweep_skips_timelapse_sweep_when_plugin_unconfigured(tmp_path):
    old_thumb = tmp_path / "thumbnails" / "2020" / "01" / "01" / "20200101-060000.jpg"
    _touch(old_thumb)

    config = AppConfig()
    config.retention = RetentionConfig(max_age_days=1, min_free_space_mb=0)
    config.upload = UploadConfig(enabled=False)
    config.plugins.pop("timelapse", None)

    sweeper = retention.RetentionSweeper(_StubConfigManager(config), tmp_path)
    sweeper._run_sweep()  # must not raise even with no "timelapse" plugin entry

    assert not old_thumb.exists()
