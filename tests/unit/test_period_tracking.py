from __future__ import annotations

from datetime import UTC, datetime, timedelta

from caelum.derivatives.base import Derivative, PeriodTrackingMixin, PeriodWindow
from caelum.scheduling.decorators import on_period_end
from tests.factories import make_processed_frame


class _Worker(PeriodTrackingMixin):
    def __init__(self):
        super().__init__()
        self.day_calls: list[PeriodWindow] = []
        self.night_calls: list[PeriodWindow] = []

    @on_period_end("day")
    def _on_day(self, window: PeriodWindow):
        self.day_calls.append(window)
        return Derivative(kind="timelapse_day", created_at=window.end_at)

    @on_period_end("night")
    def _on_night(self, window: PeriodWindow):
        self.night_calls.append(window)
        return [
            Derivative(kind="timelapse_night", created_at=window.end_at, metadata={"variant": "clean"}),
            Derivative(kind="timelapse_night", created_at=window.end_at, metadata={"variant": "overlay"}),
        ]


def _feed(worker, periods_and_times):
    for period, when in periods_and_times:
        worker.on_frame(make_processed_frame(captured_at=when, period=period))


def test_transition_out_of_day_fires_the_day_handler_with_the_right_window():
    worker = _Worker()
    t0 = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=12)
    _feed(worker, [("day", t0), ("civil_twilight", t1)])

    assert len(worker.day_calls) == 1
    window = worker.day_calls[0]
    assert window.period == "day"
    assert window.start_at == t0
    assert window.end_at == t1
    assert worker.night_calls == []


def test_twilight_to_twilight_transitions_are_ignored():
    worker = _Worker()
    t0 = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    times = [t0 + timedelta(minutes=i * 10) for i in range(4)]
    _feed(
        worker,
        [
            ("day", times[0]),
            ("civil_twilight", times[1]),
            ("nautical_twilight", times[2]),
            ("astronomical_twilight", times[3]),
        ],
    )
    # Only the day->civil_twilight transition should have fired anything.
    assert len(worker.day_calls) == 1
    assert worker.night_calls == []


def test_full_day_night_cycle_fires_exactly_two_triggers():
    worker = _Worker()
    t = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)
    sequence = [
        "day",
        "civil_twilight",
        "nautical_twilight",
        "astronomical_twilight",
        "night",
        "astronomical_twilight",
        "nautical_twilight",
        "civil_twilight",
        "day",
    ]
    for i, period in enumerate(sequence):
        worker.on_frame(make_processed_frame(captured_at=t + timedelta(hours=i), period=period))

    assert len(worker.day_calls) == 1  # only the first day->twilight transition
    assert len(worker.night_calls) == 1


def test_multiple_derivatives_from_one_trigger_drain_over_several_create_derivative_calls():
    worker = _Worker()
    t0 = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=8)
    worker.on_frame(make_processed_frame(captured_at=t0, period="night"))
    worker.on_frame(make_processed_frame(captured_at=t1, period="astronomical_twilight"))

    first = worker.create_derivative({})
    second = worker.create_derivative({})
    third = worker.create_derivative({})

    assert first is not None and second is not None
    assert third is None
    variants = {first.metadata["variant"], second.metadata["variant"]}
    assert variants == {"clean", "overlay"}


def test_handler_exception_does_not_break_period_tracking():
    class FlakyWorker(PeriodTrackingMixin):
        def __init__(self):
            super().__init__()
            self.calls = 0

        @on_period_end("day")
        def _boom(self, window: PeriodWindow):
            self.calls += 1
            raise RuntimeError("boom")

    worker = FlakyWorker()
    t0 = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=12)
    t2 = t1 + timedelta(hours=12)
    t3 = t2 + timedelta(hours=12)

    worker.on_frame(make_processed_frame(captured_at=t0, period="day"))
    worker.on_frame(make_processed_frame(captured_at=t1, period="night"))  # triggers the flaky handler once
    worker.on_frame(make_processed_frame(captured_at=t2, period="day"))
    worker.on_frame(make_processed_frame(captured_at=t3, period="night"))  # must still trigger cleanly again

    assert worker.calls == 2
    assert worker._current_period == "night"
