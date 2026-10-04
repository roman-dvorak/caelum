from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def on_period_end(*periods: str) -> Callable[[F], F]:
    """Mark a method to run once when `sky_state.period` transitions OUT of
    any of `periods`. Dispatched by `derivatives.base.PeriodTrackingMixin` —
    only meaningful on a class that mixes it in. The method receives one
    `PeriodWindow(period, start_at, end_at)` argument and may return a
    `Derivative`, a `list[Derivative]`, or `None`.

    Stacks across repeated application (`@on_period_end("day")` then
    `@on_period_end("night")` on two different methods, or multiple periods
    on one method) — each call appends rather than replaces.
    """

    def decorator(fn: F) -> F:
        existing = getattr(fn, "_on_period_end", ())
        fn._on_period_end = (*existing, *periods)  # type: ignore[attr-defined]
        return fn

    return decorator


def on_interval(seconds: float) -> Callable[[F], F]:
    """Mark a method to run every `seconds` on the shared `IntervalScheduler`
    thread (see `interval_scheduler.py`). Takes no arguments beyond `self`.

    May optionally return a `float` to override the delay before its *next*
    run — lets a handler honor a live-reconfigurable interval (e.g.
    `RetentionConfig.sweep_interval_s`) instead of the fixed value given
    here, which only sets the initial/default cadence.
    """

    def decorator(fn: F) -> F:
        fn._on_interval_seconds = seconds  # type: ignore[attr-defined]
        return fn

    return decorator
