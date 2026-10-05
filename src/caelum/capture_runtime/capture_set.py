"""Capture sets: several frames from one program run that belong together
(an HDR bracket, a calibration series, ...)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .context import CapturedFrame


@dataclass
class CaptureSet:
    frames: list[CapturedFrame]
    #: What the set is: "single", "hdr", "dark", "series", ... (free-form).
    kind: str = "single"
    #: Index into `frames` of the frame that stands for the whole set: the
    #: one shown live, listed, used by derivatives and uploaded.
    representative: int = 0
    annotations: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self) -> None:
        if not self.frames:
            raise ValueError("a capture set needs at least one frame")
        if not 0 <= self.representative < len(self.frames):
            raise ValueError(f"representative {self.representative} is not one of the {len(self.frames)} frames")

    @property
    def primary(self) -> CapturedFrame:
        return self.frames[self.representative]
