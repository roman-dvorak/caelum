"""Runs a `MountSource` in its own thread, so reading the mount is fully
asynchronous to capture: a frame only ever asks for the latest stored state."""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable

from .state import MountSource, MountState

logger = logging.getLogger(__name__)

_MAX_BACKOFF_S = 30.0


class MountPoller:
    def __init__(
        self,
        source: MountSource,
        interval_s: float = 1.0,
        stale_after_s: float = 10.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._source = source
        self._interval = max(0.1, interval_s)
        self._stale_after = stale_after_s
        self._clock = clock
        self._lock = threading.Lock()
        self._state: MountState | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="mount-poller", daemon=True)
            self._thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self._source.close()
        except Exception:  # noqa: BLE001
            logger.debug("closing mount source failed", exc_info=True)

    def latest(self) -> MountState | None:
        """The newest state; one older than `stale_after_s` is reported ``offline``."""
        with self._lock:
            state = self._state
        if state is None:
            return None
        if state.status != "offline" and self._clock() - state.timestamp > self._stale_after:
            return dataclasses.replace(state, status="offline", error=state.error or "no recent report")
        return state

    def poll_once(self) -> None:
        """One read, storing the result — or an ``offline`` state that keeps the last pointing."""
        try:
            state = self._source.read()
        except Exception as exc:  # noqa: BLE001 — any failure just means "offline"
            with self._lock:
                last = self._state
            state = (
                dataclasses.replace(last, status="offline", error=str(exc))
                if last
                else MountState(status="offline", timestamp=self._clock(), error=str(exc))
            )
            if last is None or last.status != "offline":
                logger.warning("Telescope unreachable: %s", exc)
            with self._lock:
                self._state = state
            raise
        with self._lock:
            if self._state is not None and self._state.status == "offline":
                logger.info("Telescope back online (%s)", state.status)
            self._state = state

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                self.poll_once()
                failures = 0
            except Exception:  # noqa: BLE001 — already recorded by poll_once
                failures += 1
            delay = min(self._interval * 2 ** min(failures, 5), _MAX_BACKOFF_S) if failures else self._interval
            self._stop.wait(delay)
