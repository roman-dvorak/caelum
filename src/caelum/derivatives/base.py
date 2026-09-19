"""Shared shape for built-in derivative workers (KeogramWorker,
MeteorDetectionWorker) and third-party Plugins (plugins/base.py) — every
hook is optional, a worker overrides only what it needs. Both kinds are
dispatched identically by `derivatives/pool.py`, which is what proves this
interface actually works rather than leaving it speculative.
"""

from __future__ import annotations

from concurrent.futures import Executor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement


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

    def on_frame(self, frame: ProcessedFrame) -> None:
        """Called for every captured frame, off the capture thread —
        accumulate whatever state is needed (e.g. append a keogram column)."""

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        return []

    def modify_image(self, image: np.ndarray, frame: ProcessedFrame) -> np.ndarray:
        return image

    def create_derivative(self, context: dict[str, Any]) -> Derivative | None:
        """Called every frame after on_frame(); return None on most calls —
        only produce a Derivative when this worker's own internal state says
        it's actually time to (e.g. a finished keogram at day/night rollover,
        or a detection just fired). `context["frame"]` is always the frame
        that was just processed."""
        return None
