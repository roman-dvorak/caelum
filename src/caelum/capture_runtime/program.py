"""Turning a program's source into something runnable."""

from __future__ import annotations

import ast
import hashlib
import importlib.resources
import inspect
import linecache
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from .errors import ProgramLoadError

BUILTIN_PACKAGE = "caelum.capture_programs"

Origin = Literal["builtin", "user"]


@dataclass(frozen=True)
class LoadedProgram:
    name: str
    source: str
    sha256: str
    origin: Origin
    capture: Callable[[Any], Any]
    #: The program's optional `PROGRAM = {...}` literal: description, kind,
    #: timeout_s, max_captures.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> dict[str, str]:
        return {"name": self.name, "sha256": self.sha256, "origin": self.origin}


def source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _program_meta(tree: ast.Module, name: str) -> dict[str, Any]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PROGRAM" for t in node.targets):
            try:
                meta = ast.literal_eval(node.value)
            except ValueError as exc:
                raise ProgramLoadError(f"{name}: PROGRAM must be a literal dict") from exc
            if not isinstance(meta, dict):
                raise ProgramLoadError(f"{name}: PROGRAM must be a dict")
            return meta
    return {}


def load_program(name: str, source: str, origin: Origin = "user") -> LoadedProgram:
    """Compile and execute `source` as a fresh module and check it defines
    `async def capture(ctx)`. Tracebacks from the program show its own
    source lines (registered with `linecache`)."""
    filename = f"<capture-program {name}>"
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise ProgramLoadError(f"{name}: syntax error at line {exc.lineno}: {exc.msg}") from exc
    meta = _program_meta(tree, name)

    linecache.cache[filename] = (len(source), None, source.splitlines(keepends=True), filename)
    module = types.ModuleType(f"caelum_capture_program_{name.removesuffix('.py').replace('-', '_')}")
    module.__file__ = filename
    try:
        exec(compile(tree, filename, "exec"), module.__dict__)  # noqa: S102 - running programs is the point
    except Exception as exc:
        raise ProgramLoadError(f"{name}: failed to load: {exc!r}") from exc

    capture = getattr(module, "capture", None)
    if capture is None or not inspect.iscoroutinefunction(capture):
        raise ProgramLoadError(f"{name}: must define `async def capture(ctx)`")
    params = [
        p for p in inspect.signature(capture).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if len(params) != 1:
        raise ProgramLoadError(f"{name}: `capture` must take exactly one argument (ctx)")
    return LoadedProgram(
        name=name, source=source, sha256=source_sha256(source), origin=origin, capture=capture, meta=meta
    )


def builtin_source(name: str) -> str:
    return importlib.resources.files(BUILTIN_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def builtin_names() -> list[str]:
    return sorted(
        entry.name
        for entry in importlib.resources.files(BUILTIN_PACKAGE).iterdir()
        if entry.name.endswith(".py") and not entry.name.startswith("_")
    )


def builtin_program(name: str = "default.py") -> LoadedProgram:
    return load_program(name, builtin_source(name), origin="builtin")
