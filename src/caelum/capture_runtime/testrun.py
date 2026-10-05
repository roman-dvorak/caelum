"""Test once: one run of a program on the real camera, outside production.

Runs on the capture thread right after a production slot (so the camera is
free), with its own state and a copy of the exposure regulator — production
carries on exactly as if the test never happened, apart from the slots the
test takes up. What the run returns is stored exactly as production stores
it — the same processing, the same `thumbnails/…` and `raw/…` layout (a set:
representative, `<stem>_set/` members, one multi-frame DNG) — only under
`<data_dir>/program-tests/<run_id>/`, with a `report.json`. Raw frames are
always kept, whatever the storage policy says for the time of day. Nothing
is published or uploaded.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from caelum.storage import paths

from .capture_set import CaptureSet
from .context import CaptureContext, CaptureDriver, Overrides
from .errors import ProgramStopped
from .program import LoadedProgram
from .runner import DEFAULT_MAX_CAPTURES, run_once, timeout_for
from .simulate import _ListHandler, describe_error

logger = logging.getLogger(__name__)

KEEP_RUNS = 20
_RUN_ID_CHARS = set("0123456789abcdef-T")


@dataclass(frozen=True)
class TestRequest:
    run_id: str
    program: LoadedProgram
    run_dir: Path
    requested_by: str


def tests_dir(data_dir: Path) -> Path:
    return data_dir / "program-tests"


def new_request(data_dir: Path, program: LoadedProgram, requested_by: str) -> TestRequest:
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    run_dir = tests_dir(data_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    request = TestRequest(run_id, program, run_dir, requested_by)
    write_report(run_dir, {"run_id": run_id, "status": "queued", "program": program.identity,
                           "requested_by": requested_by, "queued_at": datetime.now(UTC).isoformat()})
    _prune(tests_dir(data_dir))
    return request


def run_dir_for(data_dir: Path, run_id: str) -> Path | None:
    if not run_id or not set(run_id) <= _RUN_ID_CHARS:
        return None
    path = tests_dir(data_dir) / run_id
    return path if path.is_dir() else None


def write_report(run_dir: Path, report: dict[str, Any]) -> None:
    tmp = run_dir / ".report.json.tmp"
    tmp.write_text(json.dumps(report, indent=2, default=str))
    os.replace(tmp, run_dir / "report.json")


def read_report(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "report.json").read_text())


def _prune(base: Path) -> None:
    runs = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
    for old in runs[:-KEEP_RUNS]:
        shutil.rmtree(old, ignore_errors=True)


def execute(
    request: TestRequest,
    *,
    driver: CaptureDriver,
    config,
    sky,
    exposure_controller,
    commanded,
    capabilities,
    interval_s: float,
    loop,
    store: Callable[[Path, CaptureSet], None],
) -> dict[str, Any]:
    """`store(directory, capture_set)` writes the result exactly as
    production would (thumbnails, sidecars, DNG — multi-frame for a set),
    only into `directory` instead of the data directory."""
    program = request.program
    report = read_report(request.run_dir)
    report.update(status="running", started_at=datetime.now(UTC).isoformat())
    write_report(request.run_dir, report)

    handler = _ListHandler()
    log = logging.getLogger(f"caelum.capture_program.{program.name.removesuffix('.py')}")
    log.addHandler(handler)
    ctx = CaptureContext(
        driver=driver, config=config, sky=sky, program_name=program.name, state={},
        params=dict(config.capture.params.get(program.name.removesuffix(".py"), {})),
        exposure_controller=exposure_controller.clone(), commanded=commanded, camera_fresh=True,
        overrides=Overrides(), stream_mode=False, interval_s=interval_s, slot=0,
        max_captures=int(program.meta.get("max_captures", DEFAULT_MAX_CAPTURES)),
        capabilities=capabilities,
    )
    longest = max(p.exposure_us_max for p in config.exposure_policy.presets.values()) / 1e6
    started = time.monotonic()
    result = None
    try:
        result = run_once(loop, program, ctx, timeout_for(program, interval_s, longest))
        report["status"] = "done"
    except ProgramStopped:
        report["status"] = "stopped"
    except Exception as exc:  # noqa: BLE001 - camera errors are re-raised below, after the report
        report["status"] = "error"
        report["error"] = describe_error(exc, program)
        if ctx.camera_error is not None:
            report["camera_error"] = True
    finally:
        log.removeHandler(handler)
    report["duration_s"] = round(time.monotonic() - started, 3)
    report["captures"] = ctx.captures
    report["log"] = handler.lines
    frames = []
    if result is not None:
        report["returned"] = {"kind": result.kind, "count": len(result.frames),
                              "representative": result.representative, "annotations": result.annotations}
        try:
            store(request.run_dir, result)
        except Exception as exc:  # noqa: BLE001 - the report still counts
            logger.exception("Storing the test run's frames failed")
            report["store_error"] = repr(exc)
        set_time = result.primary.raw.captured_at
        for position, frame in enumerate(result.frames):
            is_primary = position == result.representative
            if len(result.frames) == 1 or is_primary:
                thumb = paths.thumbnail_path(request.run_dir, set_time)
            else:
                thumb = paths.member_path(
                    request.run_dir, "thumbnails", set_time, position, paths.THUMBNAIL_SUFFIXES[0]
                )
            frames.append({
                "file": _relative(request.run_dir, thumb),
                "index": frame.index,
                "captured_at": frame.raw.captured_at.isoformat(),
                "exposure_us": frame.raw.exposure_us,
                "analogue_gain": frame.raw.analogue_gain,
                "brightness_median": round(frame.brightness.median, 2),
                "capture_settings": frame.raw.capture_settings,
                "annotations": frame.annotations,
                "representative": is_primary,
            })
        dng = paths.raw_path(request.run_dir, set_time)
        report["dng"] = _relative(request.run_dir, dng)
    report["frames"] = frames
    report["files"] = sorted(
        str(p.relative_to(request.run_dir)) for p in request.run_dir.rglob("*")
        if p.is_file() and not p.name.startswith(".") and p.name != "report.json"
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    write_report(request.run_dir, report)
    logger.info("Test run %s of %s: %s (%d capture(s))", request.run_id, program.name, report["status"],
                ctx.captures)
    if ctx.camera_error is not None:
        raise ctx.camera_error
    return report



def _relative(run_dir: Path, path: Path) -> str | None:
    return str(path.relative_to(run_dir)) if path.is_file() else None
