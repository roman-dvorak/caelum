from __future__ import annotations

from datetime import UTC, datetime, timedelta

from caelum.derivatives.keogram import KeogramWorker
from tests.factories import make_processed_frame


def test_no_derivative_before_live_flush_interval_elapses():
    worker = KeogramWorker(live_flush_interval_s=999.0)
    frame = make_processed_frame(datetime(2026, 1, 1, 22, 0, tzinfo=UTC))
    worker.on_frame(frame)
    assert worker.create_derivative({"frame": frame}) is None


def test_live_derivative_contains_one_column_per_accumulated_frame():
    worker = KeogramWorker(column_width=2, strip_height=10, live_flush_interval_s=0.0)
    base = datetime(2026, 1, 1, 22, 0, tzinfo=UTC)
    frame = None
    for i in range(4):
        frame = make_processed_frame(base + timedelta(minutes=i))
        worker.on_frame(frame)

    derivative = worker.create_derivative({"frame": frame})
    assert derivative is not None
    assert derivative.kind == "keogram_live"
    assert derivative.image.shape[1] == 2 * 4  # column_width * frame_count
    assert derivative.metadata["frame_count"] == 4


def test_date_rollover_flushes_previous_days_keogram_and_starts_fresh():
    worker = KeogramWorker(column_width=2, strip_height=10, live_flush_interval_s=999.0)
    day1 = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
    day2 = datetime(2026, 1, 2, 0, 30, tzinfo=UTC)

    for i in range(3):
        f = make_processed_frame(day1 + timedelta(minutes=i))
        worker.on_frame(f)
        assert worker.create_derivative({"frame": f}) is None

    rollover_frame = make_processed_frame(day2)
    worker.on_frame(rollover_frame)
    derivative = worker.create_derivative({"frame": rollover_frame})

    assert derivative is not None
    assert derivative.kind == "keogram"
    assert derivative.metadata["date"] == "2026-01-01"
    assert derivative.metadata["frame_count"] == 3
    assert derivative.image.shape[1] == 2 * 3


def test_frame_that_triggers_rollover_is_not_lost():
    worker = KeogramWorker(column_width=2, strip_height=10, live_flush_interval_s=0.0)
    day1 = datetime(2026, 1, 1, 23, 59, tzinfo=UTC)
    day2 = datetime(2026, 1, 2, 0, 1, tzinfo=UTC)

    f1 = make_processed_frame(day1)
    worker.on_frame(f1)
    worker.create_derivative({"frame": f1})  # consume any pending live flush

    f2 = make_processed_frame(day2)
    worker.on_frame(f2)
    finished = worker.create_derivative({"frame": f2})
    assert finished is not None  # day1's keogram
    assert finished.metadata["date"] == "2026-01-01"

    # day2's frame should already be buffered for the new day, not dropped
    live = worker.create_derivative({"frame": f2})
    assert live is not None
    assert live.metadata["date"] == "2026-01-02"
    assert live.metadata["frame_count"] == 1
