"""One shared background thread driving every `@on_interval`-decorated
method across every object registered with it — replaces one bespoke
`threading.Thread` subclass per periodic job with a single, declarative
mechanism. See `scheduling/decorators.py`'s `on_interval`.

Calls are dispatched one at a time on this single thread, in whatever order
they become due — not concurrently with each other. A slow handler delays
every other registered call behind it until it returns. Fine at today's
scale (one registrant, `RetentionSweeper`); worth remembering if a second
one shows up.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: How often the scheduler wakes up to check for due calls — fine-grained
#: enough for anything from sub-minute to hour-scale intervals without
#: busy-looping.
_TICK_S = 1.0


@dataclass
class _ScheduledCall:
    name: str
    fn: Callable[[], object]
    interval_s: float
    next_due: float


class IntervalScheduler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="IntervalScheduler", daemon=True)
        self._stop_event = threading.Event()
        self._calls: list[_ScheduledCall] = []
        self._lock = threading.Lock()

    def register(self, obj: object) -> None:
        """Scans `type(obj)` for `@on_interval`-decorated methods and adds
        each as its own independently-timed scheduled call, due immediately
        on the first tick after `start()`."""
        now = time.monotonic()
        with self._lock:
            for name in dir(type(obj)):
                fn = getattr(type(obj), name, None)
                interval = getattr(fn, "_on_interval_seconds", None)
                if interval is None:
                    continue
                bound = getattr(obj, name)
                self._calls.append(
                    _ScheduledCall(name=f"{type(obj).__name__}.{name}", fn=bound, interval_s=interval, next_due=now)
                )

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            due: list[_ScheduledCall] = []
            with self._lock:
                for call in self._calls:
                    if call.next_due <= now:
                        due.append(call)

            for call in due:
                try:
                    result = call.fn()
                except Exception:
                    logger.exception("Scheduled call %s failed", call.name)
                    result = None
                delay = result if isinstance(result, int | float) else call.interval_s
                call.next_due = time.monotonic() + delay

            self._stop_event.wait(_TICK_S)
