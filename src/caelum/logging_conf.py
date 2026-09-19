"""Logging setup, plus an in-memory ring buffer the web UI reads from.

A headless camera has no console to look at, so `LogBuffer` exists to make
`journalctl -u caelum -f`-equivalent information reachable from the browser
(see `api/routes/logs.py`) regardless of whether caelum is even running
under systemd. It attaches as an ordinary `logging.Handler` on the root
logger, so it captures everything any module logs — including uvicorn's own
access/error logs — with no changes needed anywhere else.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

_DEFAULT_CAPACITY = 2000


@dataclass(frozen=True)
class LogEntry:
    timestamp: str  # ISO-8601 UTC, millisecond precision
    level: str
    logger: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"timestamp": self.timestamp, "level": self.level, "logger": self.logger, "message": self.message}


class LogBuffer(logging.Handler):
    """Keeps the last `capacity` log records in memory and fans new ones out
    to live subscribers.

    `emit()` runs synchronously on whatever thread produced the log call —
    the capture thread, a derivative worker thread, the event loop, uvicorn's
    own logging — so it only ever appends to a deque and schedules a
    threadsafe queue put; it never blocks on a subscriber that stopped
    reading. Subscription bookkeeping (`subscribe`/`unsubscribe`) happens
    from the event loop thread (a WebSocket handler), which is why both
    sides share `self._lock` rather than relying on the `logging.Handler`
    lock that only wraps `emit()`.
    """

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        super().__init__()
        self._capacity = capacity
        self._entries: list[LogEntry] = []
        self._lock = threading.Lock()
        self._queues: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[LogEntry]]] = []
        self._formatter = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = self._build_entry(record)
        except Exception:
            return  # a broken log call must not take down whatever logged it
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._capacity:
                del self._entries[: len(self._entries) - self._capacity]
            queues = list(self._queues)
        for loop, queue in queues:
            loop.call_soon_threadsafe(self._offer, queue, entry)

    def _build_entry(self, record: logging.LogRecord) -> LogEntry:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self._formatter.formatException(record.exc_info)}"
        return LogEntry(
            timestamp=datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            level=record.levelname,
            logger=record.name,
            message=message,
        )

    @staticmethod
    def _offer(queue: asyncio.Queue[LogEntry], entry: LogEntry) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(entry)

    def snapshot(self) -> list[LogEntry]:
        with self._lock:
            return list(self._entries)

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue[LogEntry]:
        """Must be called from `loop` — creates a queue new entries are
        pushed onto until `unsubscribe()`. Bounded so a client that stops
        reading drops the oldest unread lines rather than growing forever."""
        queue: asyncio.Queue[LogEntry] = asyncio.Queue(maxsize=500)
        with self._lock:
            self._queues.append((loop, queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[LogEntry]) -> None:
        with self._lock:
            self._queues = [(loop, q) for loop, q in self._queues if q is not queue]


def configure_logging(level: str = "INFO", capacity: int = _DEFAULT_CAPACITY) -> LogBuffer:
    """Attaches `LogBuffer` to the root logger — every `caelum.*` module
    logs through it with no further wiring needed.

    Deliberately *not* everything: uvicorn configures `uvicorn.access` and
    `uvicorn.error` with their own handlers and `propagate=False`, so plain
    HTTP request lines never reach this buffer (they still go to the
    console/journal). That is by design, not a gap — the web log viewer is
    for "what is the application doing", and every poll from the frontend
    (status every few seconds, camera options while a switch is pending)
    would otherwise drown that out within minutes.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    buffer = LogBuffer(capacity=capacity)
    logging.getLogger().addHandler(buffer)
    return buffer
