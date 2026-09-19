"""In-process pub/sub decoupling the live capture path from everything
downstream of it (derivatives, plugins, upload). `CaptureWorker` is the only
publisher of `FRAME_CAPTURED`; every subscriber runs on the publishing
thread's call stack, so subscribers must hand off slow work to a thread/
process pool instead of doing it inline — otherwise they'd stall capture,
which defeats the entire point of this bus.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

FRAME_CAPTURED = "frame_captured"
FRAME_METADATA_UPDATED = "frame_metadata_updated"

Subscriber = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)

    def subscribe(self, event_name: str, callback: Subscriber) -> None:
        self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Subscriber) -> None:
        try:
            self._subscribers[event_name].remove(callback)
        except ValueError:
            pass

    def publish(self, event_name: str, payload: Any) -> None:
        for callback in list(self._subscribers.get(event_name, ())):
            try:
                callback(payload)
            except Exception:
                logger.exception("Subscriber to %r raised", event_name)
