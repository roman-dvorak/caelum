"""Per-frame decision: keep a full raw frame, or a thumbnail only.

Keyed exclusively off `sky_state.period` — the same source of truth the
exposure controller reads — so "is this a night frame" and "how long should
we expose" can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

from caelum.config.schema import StoragePolicyConfig
from caelum.control.skystate import SkyState


@dataclass(frozen=True)
class StorageDecision:
    save_raw: bool
    capture_interval_s: float


class StoragePolicy:
    def decide(self, sky_state: SkyState, cfg: StoragePolicyConfig) -> StorageDecision:
        save_raw = sky_state.period in cfg.raw_periods
        interval = cfg.night_capture_interval_s if save_raw else cfg.day_capture_interval_s
        return StorageDecision(save_raw=save_raw, capture_interval_s=interval)
