"""The on-disk release layout and the operations on it.

    <root>/releases/<version>/venv/
    <root>/current  -> releases/<version>    what systemd runs
    <root>/previous -> releases/<version>    what the boot guard rolls back to
    <root>/update-pending                    start count of an unconfirmed release
    <root>/update-result.json                outcome of the last update
    <root>/incoming/                         downloaded/uploaded wheels

`update-pending` and the rollback itself belong to `scripts/caelum-launch`
(a shell script outside any venv, so a broken release cannot break it); the
file names here must stay in sync with it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

RELEASES_DIR_ENV = "CAELUM_RELEASES_DIR"

_WHEEL_NAME = re.compile(r"^caelum-(?P<version>[^-]+)-[^-]+-[^-]+-[^-]+\.whl$")
_CONSTRAINTS_IN_WHEEL = "caelum/constraints-rpi.txt"


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class ReleaseLayout:
    root: Path

    @property
    def releases(self) -> Path:
        return self.root / "releases"

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def previous(self) -> Path:
        return self.root / "previous"

    @property
    def pending(self) -> Path:
        return self.root / "update-pending"

    @property
    def result(self) -> Path:
        return self.root / "update-result.json"

    @property
    def incoming(self) -> Path:
        return self.root / "incoming"

    def version_of(self, link: Path) -> str | None:
        return Path(os.readlink(link)).name if link.is_symlink() else None


def managed_layout() -> ReleaseLayout | None:
    root = os.environ.get(RELEASES_DIR_ENV)
    if not root:
        return None
    layout = ReleaseLayout(Path(root))
    return layout if layout.current.is_symlink() else None


def wheel_version(wheel: Path) -> str:
    match = _WHEEL_NAME.match(wheel.name)
    if match is None:
        raise UpdateError(f"{wheel.name} is not a caelum wheel")
    return match["version"]


#: On top of a copy of the running release: pip's build and unpack temp files.
_INSTALL_MARGIN_MB = 200


def _tree_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def required_space_mb(layout: ReleaseLayout) -> int:
    """Rough disk space a new release needs: its venv holds about what the
    running one does (pip installs every dependency afresh — OpenCV,
    astropy, ... — only apt's packages are shared), plus pip's temp files."""
    current = layout.current.resolve()
    return int(_tree_size(current) / (1024 * 1024)) + _INSTALL_MARGIN_MB


def free_space_mb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024 * 1024)


def _read_pyvenv_cfg(venv: Path) -> dict[str, str]:
    cfg = {}
    for line in (venv / "pyvenv.cfg").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            cfg[key.strip()] = value.strip()
    return cfg


def _run(cmd: list[str], log: Callable[[str], None]) -> None:
    log("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip())
    if proc.wait() != 0:
        raise UpdateError(f"{Path(cmd[0]).name} exited with status {proc.returncode}")


def install_release(layout: ReleaseLayout, wheel: Path, log: Callable[[str], None]) -> str:
    """Install `wheel` into its own venv next to the running release.

    The new venv mirrors the current one's base interpreter and its
    `--system-site-packages` flag — that flag is how a Raspberry Pi install
    sees apt's picamera2, and it is exactly when the wheel's own numpy pins
    (constraints-rpi.txt, read from the *new* wheel) must apply.
    """
    version = wheel_version(wheel)
    if version == layout.version_of(layout.current):
        raise UpdateError(f"{version} is already the running version")

    current_cfg = _read_pyvenv_cfg(layout.current / "venv")
    base_python = current_cfg.get("executable") or str(Path(current_cfg["home"]) / "python3")
    system_site = current_cfg.get("include-system-site-packages") == "true"

    target = layout.releases / version
    # A venv's scripts hardcode its path, so it is built in place rather than
    # in a temp dir and renamed; a leftover from a failed attempt goes first.
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    try:
        venv_cmd = [base_python, "-m", "venv"]
        if system_site:
            venv_cmd.append("--system-site-packages")
        _run([*venv_cmd, str(target / "venv")], log)

        pip_cmd = [str(target / "venv" / "bin" / "pip"), "install", "--disable-pip-version-check", "--no-input"]
        # No cache: it would only keep a second copy of every wheel on a disk
        # the release itself has to fit on.
        pip_cmd += ["--progress-bar", "off", "--no-cache-dir"]
        if system_site:
            constraints = target / "constraints.txt"
            with zipfile.ZipFile(wheel) as zf:
                constraints.write_bytes(zf.read(_CONSTRAINTS_IN_WHEEL))
            pip_cmd += ["-c", str(constraints)]
        _run([*pip_cmd, str(wheel)], log)

        # Imports the whole app (every route, worker, camera backend) — the
        # cheapest check that catches a wheel incompatible with this system.
        _run([str(target / "venv" / "bin" / "python"), "-c", "import caelum.main"], log)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return version


def _atomic_symlink(link: Path, target: str) -> None:
    tmp = link.with_name(link.name + ".tmp")
    tmp.unlink(missing_ok=True)
    os.symlink(target, tmp)
    os.replace(tmp, link)


def _write_result(layout: ReleaseLayout, **fields: str) -> None:
    fields["at"] = datetime.now(UTC).isoformat(timespec="seconds")
    tmp = layout.result.with_suffix(".tmp")
    tmp.write_text(json.dumps(fields) + "\n")
    os.replace(tmp, layout.result)


def switch_to(layout: ReleaseLayout, version: str) -> None:
    """Make `version` what the next start runs, keeping the current release
    as the rollback target. Takes effect on restart."""
    running = layout.version_of(layout.current)
    if running is not None:
        _atomic_symlink(layout.previous, f"releases/{running}")
    layout.pending.write_text("0\n")
    _write_result(layout, state="pending", **{"from": running or "", "to": version})
    _atomic_symlink(layout.current, f"releases/{version}")


def read_result(layout: ReleaseLayout) -> dict | None:
    try:
        return json.loads(layout.result.read_text())
    except (OSError, ValueError):
        return None


def confirm_healthy(layout: ReleaseLayout) -> bool:
    """Called once the running release has proven itself; clears the boot
    guard's counter and drops releases that are neither current nor the
    rollback target. Returns whether there was anything to confirm."""
    if not layout.pending.exists():
        return False
    layout.pending.unlink()
    result = read_result(layout) or {}
    running = layout.version_of(layout.current) or ""
    _write_result(layout, state="success", **{"from": result.get("from", ""), "to": running})

    keep = {layout.version_of(layout.current), layout.version_of(layout.previous)}
    for entry in layout.releases.iterdir():
        if entry.is_dir() and entry.name not in keep:
            shutil.rmtree(entry, ignore_errors=True)
    shutil.rmtree(layout.incoming, ignore_errors=True)
    return True
