"""What one upload pass did — filled in by the transports."""

from __future__ import annotations

from dataclasses import dataclass, field

_MAX_ERRORS = 20


@dataclass
class TransferStats:
    files: int = 0
    bytes: int = 0
    errors: list[str] = field(default_factory=list)

    def sent(self, files: int, size: int) -> None:
        self.files += files
        self.bytes += size

    def error(self, message: str) -> None:
        if len(self.errors) < _MAX_ERRORS:
            self.errors.append(message[:2000])
