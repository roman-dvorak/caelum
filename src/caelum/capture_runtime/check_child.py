"""`python -m caelum.capture_runtime.check_child`: JSON request on stdin,
JSON report as the last line of stdout. See check.py."""

from __future__ import annotations

import contextlib
import io
import json
import sys


def main() -> None:
    request = json.loads(sys.stdin.read())
    out: dict = {"issues": [], "simulation": None, "meta": None}
    # Anything the program prints must not corrupt the report.
    with contextlib.redirect_stdout(io.StringIO()):
        from caelum.cameras.base import CameraCapabilities
        from caelum.config.schema import AppConfig

        from .errors import ProgramLoadError
        from .program import load_program
        from .simulate import describe_error, simulate

        try:
            program = load_program(request["name"], request["source"])
        except ProgramLoadError as exc:
            line = None
            cause = exc.__cause__
            if isinstance(cause, SyntaxError):
                line = cause.lineno
            elif cause is not None:
                line = describe_error(exc, _Named(request["name"]))["line"]
            out["issues"].append({"level": "error", "line": line, "message": str(exc)})
        else:
            out["meta"] = program.meta
            if request.get("simulate"):
                caps = request.get("capabilities")
                out["simulation"] = simulate(
                    program,
                    AppConfig.model_validate(request["config"]),
                    CameraCapabilities.from_dict(caps) if caps else None,
                )
    print(json.dumps(out, default=str))


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name


if __name__ == "__main__":
    main()
