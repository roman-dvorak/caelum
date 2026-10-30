from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np

from caelum.config.schema import AppConfig, LocationConfig, ObservationDayConfig
from caelum.derivatives.keogram import AXIS_HEIGHT_PX, KeogramWorker, meridian_column
from caelum.derivatives.pool import derivative_path, write_derivative
from tests.factories import make_image, make_processed_frame

# Observation days start at 12:00 UTC here — a fixed start keeps the tests
# free of sunrise computation, and UTC keeps the arithmetic obvious.
_CFG = AppConfig(location=LocationConfig(timezone="UTC"), observation_day=ObservationDayConfig(start="12:00"))
_CFG.camera.lens.radius = 0.5
H = 61  # 2 * (0.5 * 60 px) + 1 samples along the meridian of a 80 x 60 frame
DAY_START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _worker(settings: dict | None = None, data_dir=None, cfg: AppConfig = _CFG) -> KeogramWorker:
    # 600 s per pixel: a 24 h day is 144 px wide.
    worker = KeogramWorker({"seconds_per_pixel": 600, "live_flush_interval_s": 0.0, **(settings or {})})
    worker.config_manager = SimpleNamespace(current=cfg)
    worker.data_dir = data_dir
    return worker


def _frame(when: datetime, **kw):
    return make_processed_frame(when, image=make_image(width=80, height=60, **kw))


def _push(worker: KeogramWorker, when: datetime, **kw):
    frame = _frame(when, **kw)
    worker.on_frame(frame)
    return worker.create_derivative({"frame": frame})


def test_no_derivative_before_live_flush_interval_elapses():
    worker = _worker({"live_flush_interval_s": 999.0})
    assert _push(worker, datetime(2026, 1, 1, 22, 0, tzinfo=UTC)) is None


def test_image_covers_the_whole_day_with_a_time_axis_band():
    keogram = _push(_worker(), datetime(2026, 1, 1, 22, 0, tzinfo=UTC))

    assert keogram.image.shape == (H + AXIS_HEIGHT_PX, 144, 3)  # 24 h / 600 s wide, full-resolution meridian
    assert keogram.metadata["seconds_per_pixel"] == 600
    axis = keogram.image[H:]
    assert axis.max() > 150  # ticks and labels were drawn


def test_a_frame_fills_the_columns_of_its_own_moment_and_the_rest_stays_black():
    worker = _worker({"max_fill_s": 0.0})
    keogram = _push(worker, datetime(2026, 1, 1, 22, 0, tzinfo=UTC), fill=200)  # 10 h after the start
    data = keogram.image[:H]
    lit = np.flatnonzero(data.max(axis=(0, 2)) > 0)
    assert list(lit) == [60]  # 10 h * 3600 / 600 s


def test_gaps_up_to_max_fill_are_bridged_longer_ones_stay_black():
    worker = _worker({"max_fill_s": 1200.0})
    _push(worker, datetime(2026, 1, 1, 22, 0, tzinfo=UTC), fill=200)
    keogram = _push(worker, datetime(2026, 1, 1, 22, 10, tzinfo=UTC), fill=200)  # 600 s later: one column gap
    assert list(np.flatnonzero(keogram.image[:H].max(axis=(0, 2)) > 0)) == [60, 61]
    keogram = _push(worker, datetime(2026, 1, 1, 23, 30, tzinfo=UTC), fill=200)  # 80 min later: > max_fill
    lit = list(np.flatnonzero(keogram.image[:H].max(axis=(0, 2)) > 0))
    assert lit == [60, 61, 69, 70]  # the long gap stayed black; the new frame is bridged by max_fill


def test_a_night_across_midnight_is_one_keogram_rewritten_in_place():
    worker = _worker()
    flushes = [
        _push(worker, datetime(2026, 1, 1, 22, 0, tzinfo=UTC)),
        _push(worker, datetime(2026, 1, 2, 3, 0, tzinfo=UTC)),
    ]
    assert [d.metadata["date"] for d in flushes] == ["2026-01-01", "2026-01-01"]
    assert {d.created_at for d in flushes} == {DAY_START}  # same file
    assert flushes[-1].image.shape == flushes[0].image.shape


def test_day_start_finishes_the_previous_days_keogram_without_losing_a_frame():
    worker = _worker({"live_flush_interval_s": 999.0})
    for i in range(3):
        assert _push(worker, datetime(2026, 1, 2, 9, 0, tzinfo=UTC) + timedelta(minutes=i)) is None

    finished = _push(worker, datetime(2026, 1, 2, 12, 5, tzinfo=UTC))

    assert (finished.metadata["date"], finished.metadata["complete"]) == ("2026-01-01", True)
    assert np.count_nonzero(finished.image[:H].max(axis=(0, 2))) > 0
    assert worker._current_day == "2026-01-02"


def test_day_start_override_in_keogram_settings():
    worker = _worker({"day_start": "06:00"})
    worker.on_frame(_frame(datetime(2026, 1, 2, 7, 0, tzinfo=UTC)))
    assert worker._current_day == "2026-01-02"  # global 12:00 would say 2026-01-01


def test_a_restarted_worker_continues_the_days_keogram_from_disk(tmp_path):
    first = _worker(data_dir=tmp_path)
    for minute in range(3):
        derivative = _push(first, datetime(2026, 1, 1, 22, minute * 10, tzinfo=UTC), fill=150)
    path = write_derivative(tmp_path, derivative, first.id)
    assert path == derivative_path(tmp_path, derivative, first.id)

    second = _worker(data_dir=tmp_path)
    resumed = _push(second, datetime(2026, 1, 1, 23, 0, tzinfo=UTC), fill=150)
    assert np.count_nonzero(resumed.image[:H].max(axis=(0, 2))) == 4  # three columns from disk + one new


def test_a_keogram_with_another_layout_is_not_resumed(tmp_path):
    first = _worker(data_dir=tmp_path)
    write_derivative(tmp_path, _push(first, datetime(2026, 1, 1, 22, 0, tzinfo=UTC), fill=150), first.id)

    second = _worker({"seconds_per_pixel": 300}, data_dir=tmp_path)
    fresh = _push(second, datetime(2026, 1, 1, 23, 0, tzinfo=UTC), fill=150)
    assert np.count_nonzero(fresh.image[:H].max(axis=(0, 2))) == 1


def test_meridian_runs_north_to_south_and_follows_the_north_offset():
    image = np.zeros((101, 101, 3), np.uint8)
    image[:50, 50] = (255, 0, 0)  # the column above the centre: north when the camera is not turned
    image[51:, 50] = (0, 0, 255)  # below: south
    lens = _CFG.camera.lens.model_copy(update={"center_x": 0.5, "center_y": 0.5, "radius": 50 / 101})

    column = meridian_column(image, lens)
    assert column.shape[0] == 101
    assert column[10, 0, 0] > 200 and column[90, 0, 2] > 200  # red north on top, blue south below

    turned = meridian_column(image, lens.model_copy(update={"azimuth_offset_deg": 180.0}))
    assert turned[10, 0, 2] > 200 and turned[90, 0, 0] > 200  # camera turned round: the image's "up" is now south

    sideways = np.zeros((101, 101, 3), np.uint8)
    sideways[50, 51:] = (0, 255, 0)  # right of the centre
    east_up = meridian_column(sideways, lens.model_copy(update={"azimuth_offset_deg": 90.0}))
    assert east_up[:50, 0, 1].max() > 200 or east_up[51:, 0, 1].max() > 200  # the line now runs left-right


def test_max_height_caps_the_resolution():
    column = meridian_column(np.zeros((1000, 1000, 3), np.uint8), _CFG.camera.lens, max_height=300)
    assert column.shape == (300, 1, 3)
