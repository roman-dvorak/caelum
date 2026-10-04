from __future__ import annotations

import time

from caelum.scheduling.decorators import on_interval, on_period_end
from caelum.scheduling.interval_scheduler import IntervalScheduler


def test_on_period_end_marks_the_function_and_stacks_across_calls():
    @on_period_end("day")
    @on_period_end("night")
    def handler():
        pass

    assert handler._on_period_end == ("night", "day")


def test_on_interval_marks_the_function():
    @on_interval(seconds=5)
    def handler():
        pass

    assert handler._on_interval_seconds == 5


def test_interval_scheduler_fires_a_registered_call():
    calls = []

    class Job:
        @on_interval(seconds=0.01)
        def tick(self):
            calls.append(time.monotonic())

    scheduler = IntervalScheduler()
    scheduler.register(Job())
    scheduler.start()
    try:
        deadline = time.monotonic() + 2.0
        while not calls and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        scheduler.request_stop()
        scheduler.join(timeout=2)

    assert calls, "expected the scheduled call to fire at least once"


def test_interval_scheduler_honors_a_handlers_returned_override():
    calls = []

    class Job:
        @on_interval(seconds=999)  # would never fire again within the test's timeout if not overridden
        def tick(self):
            calls.append(time.monotonic())
            return 0.01

    scheduler = IntervalScheduler()
    scheduler.register(Job())
    scheduler.start()
    try:
        deadline = time.monotonic() + 2.0
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        scheduler.request_stop()
        scheduler.join(timeout=2)

    assert len(calls) >= 2, "expected the override to make the call fire again quickly"


def test_interval_scheduler_survives_a_failing_call():
    calls = []

    class Job:
        @on_interval(seconds=0.01)
        def bad(self):
            raise RuntimeError("boom")

        @on_interval(seconds=0.01)
        def good(self):
            calls.append(1)

    scheduler = IntervalScheduler()
    scheduler.register(Job())
    scheduler.start()
    try:
        deadline = time.monotonic() + 2.0
        while not calls and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        scheduler.request_stop()
        scheduler.join(timeout=2)

    assert calls, "a failing scheduled call must not stop other calls from running"
