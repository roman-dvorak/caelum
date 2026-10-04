from __future__ import annotations

from datetime import UTC, datetime

from caelum.config.schema import AppConfig, PluginConfig
from caelum.derivatives.base import PeriodWindow
from caelum.derivatives.timelapse import TimelapseWorker, _resolve_frame_paths
from caelum.storage import paths


def _touch(path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_resolve_frame_paths_filters_to_window(tmp_path):
    start = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    end = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)
    inside = datetime(2026, 9, 20, 19, 0, tzinfo=UTC)
    before = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)
    after = datetime(2026, 9, 20, 21, 0, tzinfo=UTC)

    for when in (inside, before, after):
        _touch(paths.thumbnail_path(tmp_path, when))

    result = _resolve_frame_paths(tmp_path, start, end)

    assert result == [paths.thumbnail_path(tmp_path, inside)]


def test_resolve_frame_paths_prefers_raw_over_thumbnail(tmp_path):
    start = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    end = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)
    when = datetime(2026, 9, 20, 19, 0, tzinfo=UTC)

    _touch(paths.thumbnail_path(tmp_path, when))
    _touch(paths.raw_path(tmp_path, when))

    result = _resolve_frame_paths(tmp_path, start, end)

    assert result == [paths.raw_path(tmp_path, when)]


def test_resolve_frame_paths_spans_a_window_crossing_midnight(tmp_path):
    start = datetime(2026, 9, 20, 23, 0, tzinfo=UTC)
    end = datetime(2026, 9, 21, 1, 0, tzinfo=UTC)
    before_midnight = datetime(2026, 9, 20, 23, 30, tzinfo=UTC)
    after_midnight = datetime(2026, 9, 21, 0, 30, tzinfo=UTC)

    _touch(paths.thumbnail_path(tmp_path, before_midnight))
    _touch(paths.thumbnail_path(tmp_path, after_midnight))

    result = _resolve_frame_paths(tmp_path, start, end)

    assert set(result) == {
        paths.thumbnail_path(tmp_path, before_midnight),
        paths.thumbnail_path(tmp_path, after_midnight),
    }


def test_resolve_frame_paths_ignores_json_sidecars(tmp_path):
    start = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    end = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)
    when = datetime(2026, 9, 20, 19, 0, tzinfo=UTC)

    thumb = paths.thumbnail_path(tmp_path, when)
    _touch(thumb)
    paths.sidecar_path(thumb).write_text("{}")

    result = _resolve_frame_paths(tmp_path, start, end)

    assert result == [thumb]


def test_build_skips_encoding_below_min_frames(tmp_path):
    worker = TimelapseWorker({"min_frames": 5})
    worker.data_dir = tmp_path

    start = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    end = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)
    _touch(paths.thumbnail_path(tmp_path, start + (end - start) / 2))  # only 1 frame, min_frames=5

    window = PeriodWindow(period="night", start_at=start, end_at=end)
    result = worker._build(window, kind="night")

    assert result == []


class _StubConfigManager:
    def __init__(self, config: AppConfig) -> None:
        self.current = config


def test_current_overlay_elements_reads_live_config_not_a_cached_copy():
    worker = TimelapseWorker({})
    config = AppConfig()
    config.plugins["overlay"] = PluginConfig(
        enabled=True,
        order=30,
        settings={"templates": [{"name": "Default", "elements": [{"id": "m1", "kind": "mask", "x": 0, "y": 0}]}]},
    )
    stub = _StubConfigManager(config)
    worker.config_manager = stub

    first = worker._current_overlay_elements()
    assert first is not None
    assert len(first) == 1

    # Mutate the stub's live config in place — simulates an admin editing
    # the overlay template between two timelapse generations without the
    # worker being reconstructed.
    config.plugins["overlay"] = PluginConfig(
        enabled=True, order=30, settings={"templates": [], "active_template": None}
    )
    second = worker._current_overlay_elements()
    assert second == []


def test_current_overlay_elements_is_none_when_overlay_plugin_disabled():
    worker = TimelapseWorker({})
    config = AppConfig()
    config.plugins["overlay"] = PluginConfig(enabled=False, order=30, settings={})
    worker.config_manager = _StubConfigManager(config)

    assert worker._current_overlay_elements() is None


def test_current_overlay_elements_is_none_without_config_manager():
    worker = TimelapseWorker({})
    assert worker.config_manager is None
    assert worker._current_overlay_elements() is None
