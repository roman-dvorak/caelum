"""Where capture programs live.

- **Built-in** programs come with Caelum (`caelum.capture_programs`) and
  are read-only.
- **User** programs are plain `.py` files in the programs directory
  (`CAELUM_CAPTURE_PROGRAMS_DIR`, default `<data_dir>/capture-programs`).
- **Archive**: every version that was ever activated or tested is kept as
  `.archive/<sha256>.py`. Production runs from the archive, by the
  `(capture.active_program, capture.active_sha256)` pair in the config — so
  saving a file never changes what runs; only activating does.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from caelum.config.schema import AppConfig

from .errors import ProgramLoadError
from .program import LoadedProgram, builtin_names, builtin_program, builtin_source, load_program, source_sha256

logger = logging.getLogger(__name__)

DEFAULT_PROGRAM = "default.py"
MAX_SOURCE_BYTES = 256 * 1024
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\.py$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_CRASH_MARKER = ".crashed"


class ProgramStoreError(ValueError):
    pass


class ProgramNotFound(ProgramStoreError):
    pass


def validate_name(name: str) -> str:
    if not _NAME_RE.fullmatch(name):
        raise ProgramStoreError(
            f"invalid program name {name!r}: lower-case letters, digits, '-' and '_', ending in .py"
        )
    return name


@dataclass(frozen=True)
class ProgramInfo:
    name: str
    origin: str
    sha256: str
    size: int
    modified: float | None
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "origin": self.origin,
            "sha256": self.sha256,
            "size": self.size,
            "modified": self.modified,
            "description": self.meta.get("description"),
            "kind": self.meta.get("kind"),
        }


def _meta_or_empty(name: str, source: str) -> dict[str, Any]:
    import ast

    from .program import _program_meta

    try:
        return _program_meta(ast.parse(source), name)
    except (SyntaxError, ProgramLoadError, ValueError):
        return {}


class ProgramStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._archive = directory / ".archive"
        self._cache: dict[tuple[str, str], LoadedProgram] = {}

    # ---- listing and editing ---------------------------------------------

    def is_builtin(self, name: str) -> bool:
        return name in builtin_names()

    def list(self) -> list[ProgramInfo]:
        programs = []
        for name in builtin_names():
            source = builtin_source(name)
            meta = _meta_or_empty(name, source)
            programs.append(ProgramInfo(name, "builtin", source_sha256(source), len(source.encode()), None, meta))
        if self.directory.is_dir():
            for path in sorted(self.directory.glob("*.py")):
                if not _NAME_RE.fullmatch(path.name) or self.is_builtin(path.name) or not path.is_file():
                    continue
                source = path.read_text(encoding="utf-8", errors="replace")
                programs.append(
                    ProgramInfo(path.name, "user", source_sha256(source), path.stat().st_size,
                                path.stat().st_mtime, _meta_or_empty(path.name, source))
                )
        return programs

    def get(self, name: str) -> tuple[str, str]:
        """(source, origin)."""
        validate_name(name)
        if self.is_builtin(name):
            return builtin_source(name), "builtin"
        path = self.directory / name
        if not path.is_file():
            raise ProgramNotFound(f"no program {name!r}")
        return path.read_text(encoding="utf-8"), "user"

    def save(self, name: str, source: str) -> str:
        validate_name(name)
        if self.is_builtin(name):
            raise ProgramStoreError(f"{name} is a built-in program — save a copy under another name")
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ProgramStoreError(f"program is larger than {MAX_SOURCE_BYTES // 1024} KiB")
        self.directory.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.directory / name, source)
        return source_sha256(source)

    def delete(self, name: str) -> None:
        validate_name(name)
        if self.is_builtin(name):
            raise ProgramStoreError(f"{name} is a built-in program")
        path = self.directory / name
        if not path.is_file():
            raise ProgramNotFound(f"no program {name!r}")
        path.unlink()  # its archived versions stay — frames refer to them by sha256

    # ---- archive -----------------------------------------------------------

    def archive(self, source: str) -> str:
        sha = source_sha256(source)
        path = self._archive / f"{sha}.py"
        if not path.exists():
            self._archive.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, source)
        return sha

    def archived_source(self, sha256: str) -> str:
        if not _SHA_RE.fullmatch(sha256):
            raise ProgramStoreError("invalid sha256")
        path = self._archive / f"{sha256}.py"
        if not path.is_file():
            raise ProgramNotFound(f"no archived version {sha256[:12]}")
        return path.read_text(encoding="utf-8")

    def load(self, name: str, sha256: str | None) -> LoadedProgram:
        """A runnable program: a built-in by name, a user program by the
        archived version `sha256`."""
        validate_name(name)
        if self.is_builtin(name):
            key = (name, "builtin")
            if key not in self._cache:
                self._cache[key] = builtin_program(name)
            return self._cache[key]
        if sha256 is None:
            raise ProgramStoreError(f"{name}: no version (sha256) selected")
        key = (name, sha256)
        if key not in self._cache:
            self._cache[key] = load_program(name, self.archived_source(sha256), origin="user")
        return self._cache[key]

    def active(self, cfg: AppConfig) -> LoadedProgram:
        capture = cfg.capture
        return self.load(capture.active_program, capture.active_sha256)

    # ---- crash marker ------------------------------------------------------

    def mark_crashed(self, program: LoadedProgram) -> None:
        """Written right before the process is killed for a program that
        hung — so the next start doesn't run it straight into the same hang."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / _CRASH_MARKER).write_text(f"{program.name} {program.sha256}\n")
        except OSError:
            logger.exception("Could not write the capture-program crash marker")

    def take_crash_marker(self) -> tuple[str, str] | None:
        path = self.directory / _CRASH_MARKER
        try:
            name, sha = path.read_text().split()[:2]
        except (OSError, ValueError):
            return None
        try:
            path.unlink()
        except OSError:
            pass
        return name, sha


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
