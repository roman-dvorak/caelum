"""Check a program before it runs for real.

1. Static: it parses, defines `async def capture(ctx)` with one argument,
   `PROGRAM` is a literal dict. Nothing is executed.
2. In a child process (never in the server): import it, then — optionally —
   run it twice against a simulated camera with the real camera's
   capabilities. What the camera would clamp or ignore is reported for
   information; it is never an error.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from typing import Any

from caelum.cameras.base import CameraCapabilities
from caelum.config.schema import AppConfig

CHILD_TIMEOUT_S = 30.0


def _issue(level: str, line: int | None, message: str) -> dict[str, Any]:
    return {"level": level, "line": line, "message": message}


def static_check(name: str, source: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        tree = ast.parse(source, filename=name)
    except SyntaxError as exc:
        return [{"level": "error", "line": exc.lineno, "message": f"syntax error: {exc.msg}"}]
    capture = None
    meta_node = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "capture":
            capture = node
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PROGRAM" for t in node.targets):
            meta_node = node
    if capture is None:
        issues.append({"level": "error", "line": None, "message": "no `async def capture(ctx)` at the top level"})
    elif not isinstance(capture, ast.AsyncFunctionDef):
        issues.append({"level": "error", "line": capture.lineno, "message": "`capture` must be `async def`"})
    elif len(capture.args.posonlyargs) + len(capture.args.args) != 1:
        issues.append(_issue("error", capture.lineno, "`capture` must take exactly one argument (ctx)"))
    if meta_node is None:
        issues.append({"level": "warning", "line": None, "message": "no PROGRAM = {...} with a description"})
    else:
        try:
            meta = ast.literal_eval(meta_node.value)
        except ValueError:
            issues.append({"level": "error", "line": meta_node.lineno, "message": "PROGRAM must be a literal dict"})
        else:
            if not isinstance(meta, dict):
                issues.append({"level": "error", "line": meta_node.lineno, "message": "PROGRAM must be a dict"})
    return issues


def check(
    name: str,
    source: str,
    config: AppConfig,
    capabilities: CameraCapabilities | None = None,
    simulate: bool = True,
    timeout_s: float = CHILD_TIMEOUT_S,
) -> dict[str, Any]:
    issues = static_check(name, source)
    report: dict[str, Any] = {"ok": False, "issues": issues, "simulation": None}
    if any(i["level"] == "error" for i in issues):
        return report
    request = {
        "name": name,
        "source": source,
        "config": config.model_dump(mode="json"),
        "capabilities": capabilities.to_dict() if capabilities else None,
        "simulate": simulate,
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "caelum.capture_runtime.check_child"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        issues.append({"level": "error", "line": None, "message": f"importing/simulating took over {timeout_s:.0f}s"})
        return report
    try:
        child = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        tail = (proc.stderr or proc.stdout).strip()[-2000:]
        issues.append(_issue("error", None, f"check process failed (exit {proc.returncode}): {tail}"))
        return report
    issues.extend(child.get("issues", []))
    report["simulation"] = child.get("simulation")
    report["meta"] = child.get("meta")
    if report["simulation"]:
        for run in report["simulation"]["runs"]:
            if "error" in run:
                err = run["error"]
                issues.append({"level": "error", "line": err.get("line"),
                               "message": f"simulated run {run['slot']}: {err['type']}: {err['message']}"})
            for frame in (run.get("returned") or {}).get("frames", []):
                for what, items in (("clamped", frame["clamped"]), ("ignored", frame["ignored"])):
                    if items:
                        where = f"run {run['slot']} frame {frame['index']}"
                        issues.append(_issue("info", None, f"{where}: camera {what} {', '.join(items)}"))
        slots = config.processing.slots
        largest = max(((run.get("returned") or {}).get("count", 0) for run in report["simulation"]["runs"]), default=0)
        if largest > slots:
            issues.append(_issue("warning", None, f"returns sets of {largest} frames but processing has {slots} slots "
                                 "— such sets are dropped whole (raise processing.slots)"))
    report["ok"] = not any(i["level"] == "error" for i in issues)
    return report
