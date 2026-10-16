"""Observation days: the unit a night's data is grouped by.

An observation day runs from one *start* to the next — sunrise, or a fixed
local wall-clock time — and is labelled with the local calendar date
(`location.timezone`) it started on. With a morning start a whole night
stays inside one day: the night of 15/16 October is observation day
"2026-10-15". The recordings API (`api/routes/frames.py`, `?night=`) and the
keogram (`derivatives/keogram.py`) both group by it, so the two always agree
on where a night begins and ends.

Every boundary is returned in UTC, like every other timestamp in the app.
"""

from __future__ import annotations

import functools
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from caelum.config.schema import AppConfig
from caelum.control.skystate import SkyStateCalculator


class ObservationDays:
    def __init__(self, calculator: SkyStateCalculator | None, tz: ZoneInfo, start: str = "sunrise") -> None:
        if start == "sunrise" and calculator is None:
            raise ValueError("a sunrise start needs a SkyStateCalculator")
        self._calculator = calculator
        self._tz = tz
        self._start = start
        self._fixed = None if start == "sunrise" else time.fromisoformat(start)

    @classmethod
    def from_config(
        cls, cfg: AppConfig, calculator: SkyStateCalculator | None = None, start: str | None = None
    ) -> ObservationDays:
        """`start` overrides `cfg.observation_day.start` (a plugin's own
        setting); `calculator` defaults to one for `cfg.location`."""
        start = start or cfg.observation_day.start
        if calculator is None and start == "sunrise":
            loc = cfg.location
            calculator = SkyStateCalculator(lat=loc.lat, lon=loc.lon, elevation_m=loc.elevation_m)
        return cls(calculator, ZoneInfo(cfg.location.timezone), start)

    def _start_of(self, day: date) -> datetime:
        if self._fixed is None:
            assert self._calculator is not None
            local_midnight = datetime.combine(day, time(), tzinfo=self._tz).astimezone(UTC)
            return self._calculator.next_sunrise(local_midnight)
        return datetime.combine(day, self._fixed, tzinfo=self._tz).astimezone(UTC)

    @functools.lru_cache(maxsize=512)  # noqa: B019 - one long-lived instance per config, few distinct days
    def window(self, label: str) -> tuple[datetime, datetime]:
        """`[start, end)` of observation day `label` ("YYYY-MM-DD"), UTC."""
        day = date.fromisoformat(label)
        return self._start_of(day), self._start_of(day + timedelta(days=1))

    def label_of(self, when: datetime) -> str:
        """The observation day `when` falls in."""
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        local = when.astimezone(self._tz).date()
        start, _ = self.window(local.isoformat())
        return local.isoformat() if when >= start else (local - timedelta(days=1)).isoformat()
