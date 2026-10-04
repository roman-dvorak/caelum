"""Shared shape for built-in derivative workers (KeogramWorker,
MeteorDetectionWorker) and third-party Plugins (plugins/base.py) — every
hook is optional, a worker overrides only what it needs. Both kinds are
dispatched identically by `derivatives/pool.py`, which is what proves this
interface actually works rather than leaving it speculative.
"""

from __future__ import annotations

import logging
from concurrent.futures import Executor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement

if TYPE_CHECKING:
    from caelum.config.manager import ConfigManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Derivative:
    """One output derived from one or more source frames — a keogram, a
    meteor crop, or (in the future) whatever a plugin dreams up. `image`
    holds it in memory; `path` is filled in once/if it's been persisted."""

    kind: str
    created_at: datetime
    image: np.ndarray | None = None
    path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DerivativeWorker:
    """Not an ABC: every hook below has a working no-op default, so there is
    nothing a subclass is *required* to implement — only override what's
    actually needed."""

    id: str

    #: The shared ProcessPoolExecutor, injected by `DerivativePool.register()`
    #: so a worker never has to be handed one at construction — which is what
    #: lets every worker, built-in or third-party, be built uniformly from
    #: nothing but its config block. Use it for genuinely heavy, *stateless*
    #: computation (see meteor_detection.detect_streak); it is None until the
    #: worker is registered, and in unit tests that never register one.
    process_pool: Executor | None = None

    #: The app's live ConfigManager, injected by `DerivativePool.register()`
    #: alongside `process_pool` — for a worker that needs to read *another*
    #: plugin's current settings at derivative-creation time rather than its
    #: own settings frozen at construction (see `timelapse.py`'s use of the
    #: `overlay` plugin's currently-active template). None until registered,
    #: and in unit tests that never register one.
    config_manager: ConfigManager | None = None

    #: The data directory, injected by `DerivativePool.register()` alongside
    #: `process_pool`/`config_manager` — for a worker that needs it inside
    #: `on_frame()` itself (e.g. to resolve source files for a just-finished
    #: period, see `PeriodTrackingMixin`), where the per-call `context` dict
    #: `create_derivative()` receives isn't available yet: `on_frame()` runs
    #: *before* `create_derivative()` in `DerivativePool._run_worker`'s
    #: per-frame dispatch. None until registered.
    data_dir: Path | None = None

    def on_frame(self, frame: ProcessedFrame) -> None:
        """Called for every captured frame, off the capture thread —
        accumulate whatever state is needed (e.g. append a keogram column)."""

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        return []

    def modify_image(self, image: np.ndarray, frame: ProcessedFrame) -> np.ndarray:
        """Return a modified copy of `image` (or `image` itself, unchanged).

        Chained across every enabled worker in ascending `order` — see
        `DerivativePool._run_modify_chain` — so this worker's output becomes
        the next worker's `image` argument. `frame` is the original,
        unmodified `ProcessedFrame` throughout the chain (its metadata,
        stats and already-encoded thumbnail); only `image` accumulates
        changes. Offload genuinely heavy work to `self.process_pool`
        yourself (see meteor_detection.py's `_detect()`) — this hook runs
        synchronously in the chain, so it blocks every worker after it.
        """
        return image

    def create_derivative(self, context: dict[str, Any]) -> Derivative | None:
        """Called every frame after on_frame(); return None on most calls —
        only produce a Derivative when this worker's own internal state says
        it's actually time to (e.g. a finished keogram at day/night rollover,
        or a detection just fired). `context["frame"]` is always the frame
        that was just processed."""
        return None


@dataclass(frozen=True)
class PeriodWindow:
    """The sky-state period that just ended, and when it ran — handed to
    every `@on_period_end`-decorated method for that period."""

    period: str
    start_at: datetime
    end_at: datetime


def _collect_period_handlers(cls: type) -> dict[str, list[str]]:
    handlers: dict[str, list[str]] = {}
    for name in dir(cls):
        fn = getattr(cls, name, None)
        for period in getattr(fn, "_on_period_end", ()):
            handlers.setdefault(period, []).append(name)
    return handlers


class PeriodTrackingMixin:
    """Mix into a `DerivativeWorker`/`Plugin` for declarative
    `@on_period_end` dispatch (see `scheduling.decorators.on_period_end`):
    tracks `sky_state.period` transitions in `on_frame()`, and on a
    transition calls every method decorated for the period that just ended.

    Dispatch is by period *name* lookup in `_period_handlers`, not "fire on
    any change" — a period value with no decorated handler (e.g. the three
    twilight stages, when only "day"/"night" are decorated) is silently
    skipped. This is what makes "5 SkyPeriod values but exactly 2
    triggers/day" fall out for free, with no special-casing: the number of
    period values in existence and the number of registered handlers are
    entirely independent.

    Each handler's return value (`Derivative | list[Derivative] | None`) is
    queued; `create_derivative()` — called once per frame by
    `DerivativePool`, strictly one-`Derivative`-per-call — pops the queue
    one at a time, so a single transition producing multiple outputs (e.g.
    clean + overlay variants) drains cleanly over the next few frames
    without needing any change to `DerivativePool`'s dispatch contract.

    A config change mid-period rebuilds the whole worker (see
    `DerivativePool.replace_all`), which discards `_period_start_at` —
    that one in-progress period's timelapse would start from the rebuild
    point instead of the true period start. Rare and self-healing (the next
    full period is unaffected); not otherwise guarded against here.
    """

    def __init__(self) -> None:
        self._current_period: str | None = None
        self._period_start_at: datetime | None = None
        self._pending_derivatives: list[Derivative] = []
        self._period_handlers = _collect_period_handlers(type(self))

    def on_frame(self, frame: ProcessedFrame) -> None:
        period = frame.metadata.sky_state.period
        when = frame.metadata.captured_at
        if self._current_period is not None and period != self._current_period:
            assert self._period_start_at is not None
            window = PeriodWindow(period=self._current_period, start_at=self._period_start_at, end_at=when)
            # A handler exception must not prevent the period/start-time
            # bookkeeping below from advancing — otherwise a single bad
            # trigger would leave `_current_period` stuck on the old value,
            # making every subsequent frame look like "another transition"
            # with a stale, wrong window.
            for name in self._period_handlers.get(self._current_period, []):
                try:
                    result = getattr(self, name)(window)
                except Exception:
                    logger.exception("@on_period_end handler %s failed for period %r", name, window.period)
                    continue
                if result:
                    self._pending_derivatives.extend(result if isinstance(result, list) else [result])
            self._period_start_at = when
        elif self._period_start_at is None:
            self._period_start_at = when
        self._current_period = period

    def create_derivative(self, context: dict[str, Any]) -> Derivative | None:
        return self._pending_derivatives.pop(0) if self._pending_derivatives else None
