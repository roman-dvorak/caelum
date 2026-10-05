from __future__ import annotations


class CaptureProgramError(RuntimeError):
    """A capture program misbehaved (as opposed to the camera failing)."""


class ProgramLoadError(CaptureProgramError):
    """The program's source can't be turned into a runnable program."""


class ProgramTimeout(CaptureProgramError):
    """One run of the program took longer than its time budget."""


class TooManyCaptures(CaptureProgramError):
    """One run asked for more frames than it is allowed."""


class ProgramStopped(Exception):
    """The worker is shutting down; unwinds a running program quietly."""
