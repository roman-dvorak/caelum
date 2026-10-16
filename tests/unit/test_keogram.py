from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from caelum.config.schema import AppConfig, LocationConfig, ObservationDayConfig
from caelum.derivatives.keogram import KeogramWorker
from caelum.derivatives.pool import derivative_path, write_derivative
from tests.factories import make_processed_frame

# Observation days start at 12:00 UTC here — a fixed start keeps the tests
# free of sunrise computation, and UTC keeps the arithmetic obvious.
_CFG = AppConfig(location=LocationConfig(timezone="UTC"), observation_day=ObservationDayConfig(start="12:00"))


def _worker(settings: dict, data_dir=None) -> KeogramWorker:
    worker = KeogramWorker({"column_width": 2, "strip_height": 10, **settings})
    worker.config_manager = SimpleNamespace(current=_CFG)
    worker.data_dir = data_dir
    return worker


def test_no_derivative_before_live_flush_interval_elapses():
    worker = _worker({"live_flush_interval_s": 999.0})
    frame = make_processed_frame(datetime(2026, 1, 1, 22, 0, tzinfo=UTC))
    worker.on_frame(frame)
    assert worker.create_derivative({"frame": frame}) is None


def test_a_night_across_midnight_is_one_keogram_rewritten_in_place():
    worker = _worker({"live_flush_interval_s": 0.0})
    night = [datetime(2026, 1, 1, 22, 0, tzinfo=UTC), datetime(2026, 1, 2, 3, 0, tzinfo=UTC)]
    flushes = []
    for when in night:
        frame = make_processed_frame(when)
        worker.on_frame(frame)
        flushes.append(worker.create_derivative({"frame": frame}))

    assert [d.metadata["date"] for d in flushes] == ["2026-01-01", "2026-01-01"]
    assert {d.created_at for d in flushes} == {datetime(2026, 1, 1, 12, 0, tzinfo=UTC)}  # same file
    assert flushes[-1].kind == "keogram"
    assert flushes[-1].image.shape[1] == 2 * 2  # column_width * frames so far


def test_day_start_finishes_the_previous_days_keogram_without_losing_a_frame():
    worker = _worker({"live_flush_interval_s": 999.0})
    for i in range(3):
        f = make_processed_frame(datetime(2026, 1, 2, 9, 0, tzinfo=UTC) + timedelta(minutes=i))
        worker.on_frame(f)
        assert worker.create_derivative({"frame": f}) is None

    first_of_next_day = make_processed_frame(datetime(2026, 1, 2, 12, 5, tzinfo=UTC))
    worker.on_frame(first_of_next_day)
    finished = worker.create_derivative({"frame": first_of_next_day})

    assert (finished.metadata["date"], finished.metadata["complete"]) == ("2026-01-01", True)
    assert finished.image.shape[1] == 2 * 3
    assert worker._buffer and len(worker._buffer) == 1  # the new day's first column


def test_day_start_override_in_keogram_settings():
    worker = _worker({"day_start": "06:00"})
    worker.on_frame(make_processed_frame(datetime(2026, 1, 2, 7, 0, tzinfo=UTC)))
    assert worker._current_day == "2026-01-02"  # global 12:00 would say 2026-01-01


def test_a_restarted_worker_continues_the_days_keogram_from_disk(tmp_path):
    first = _worker({"live_flush_interval_s": 0.0}, data_dir=tmp_path)
    for minute in range(3):
        f = make_processed_frame(datetime(2026, 1, 1, 22, minute, tzinfo=UTC))
        first.on_frame(f)
        derivative = first.create_derivative({"frame": f})
    path = write_derivative(tmp_path, derivative, first.id)
    assert path == derivative_path(tmp_path, derivative, first.id)

    second = _worker({"live_flush_interval_s": 0.0}, data_dir=tmp_path)
    f = make_processed_frame(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))
    second.on_frame(f)
    resumed = second.create_derivative({"frame": f})
    assert resumed.image.shape[1] == 2 * 4  # three columns from disk + one new
