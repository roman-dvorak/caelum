"""Generic, declarative periodic-trigger primitives.

Two independent trigger axes, proven by two real call sites rather than left
speculative: `on_period_end` (dispatched by `derivatives.base.PeriodTrackingMixin`
off the per-frame pipeline — see `derivatives/timelapse.py`) and `on_interval`
(dispatched by `IntervalScheduler`, a single shared background thread — see
`storage/retention.py`'s `RetentionSweeper`).

Deliberately minimal: no cron-expression parsing, no persistence/replay of
missed runs across restarts. `KeogramWorker`'s calendar-date rollover is a
third, similar-shaped axis that could adopt `on_period_end`-style dispatch
in the future, but isn't migrated here — it already works, and two proven
call sites are enough to validate the primitive without churning working
code.
"""
