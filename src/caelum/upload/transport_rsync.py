"""rsync-based transport — delta-aware, resumable, and idempotent, which is
exactly what makes the reconciliation pass in uploader.py a self-healing
retry mechanism with no separate ledger/retry-queue needed.

Chosen over scp (no delta/resume) and sftp/paramiko (a slower pure-Python
SSH stack for many small files). When `remote_host` is empty, targets are
treated as a plain local filesystem path instead of an SSH target — useful
for an NFS/USB-mounted archive with no SSH involved at all, and it's what
makes this module testable without a real network.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from pathlib import Path

from caelum.config.schema import UploadConfig

from .ssh import destination, ssh_command
from .stats import TransferStats

_FILES_RE = re.compile(r"Number of regular files transferred: ([\d,.]+)")
_BYTES_RE = re.compile(r"Total transferred file size: ([\d,.]+)")

logger = logging.getLogger(__name__)


def _is_local(cfg: UploadConfig) -> bool:
    return not cfg.remote_host


def _target(cfg: UploadConfig, relative_path: str) -> str:
    base_path = f"{cfg.remote_base_path}/{relative_path}" if relative_path else f"{cfg.remote_base_path}/"
    if _is_local(cfg):
        return base_path
    return f"{destination(cfg)}:{base_path}"


def _ssh_option(cfg: UploadConfig) -> list[str]:
    options = [f"--bwlimit={cfg.bandwidth_limit_kbps}"] if cfg.bandwidth_limit_kbps else []
    if _is_local(cfg):
        return options
    return [*options, "-e", shlex.join(ssh_command(cfg))]


def _number(pattern: re.Pattern[str], text: str) -> int:
    match = pattern.search(text)
    return int(re.sub(r"[,.]", "", match.group(1))) if match else 0


def _run(cmd: list[str], warn_on_failure: bool = True, stats: TransferStats | None = None) -> bool:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log = logger.warning if warn_on_failure else logger.debug
        log("rsync failed (%s): %s", " ".join(cmd), result.stderr.strip())
        if stats is not None and warn_on_failure:
            stats.error(f"rsync exit {result.returncode}: {result.stderr.strip()}")
        return False
    if stats is not None:
        stats.sent(_number(_FILES_RE, result.stdout), _number(_BYTES_RE, result.stdout))
    return True


def push_tree(cfg: UploadConfig, local_dir: Path, remote_relative_path: str,
              stats: TransferStats | None = None) -> bool:
    """Push an entire directory's contents, recursively. One-way archival:
    never deletes anything remotely, even if it's gone locally. Skips the
    hidden `.<name>.tmp` files atomic writers (e.g. the DNG writer) rename
    into place — they'd otherwise be uploaded half-written and then linger
    remotely forever."""
    if not local_dir.exists():
        return True  # nothing to push yet is not a failure
    cmd = [
        "rsync", "-az", "--mkpath", "--stats", "--exclude=.*.tmp", *_ssh_option(cfg),
        f"{local_dir}/", _target(cfg, remote_relative_path),
    ]
    return _run(cmd, stats=stats)


def push_file(cfg: UploadConfig, local_path: Path, remote_relative_path: str,
              stats: TransferStats | None = None) -> bool:
    if not local_path.exists():
        return False
    cmd = ["rsync", "-az", "--mkpath", "--stats", *_ssh_option(cfg), str(local_path),
           _target(cfg, remote_relative_path)]
    return _run(cmd, stats=stats)


def pull_file(cfg: UploadConfig, remote_relative_path: str, local_path: Path) -> bool:
    """Fetch one file from the remote — used to read back the shared
    `cameras.json` before merging this camera's entry into it. Not finding
    it yet (first camera, first boot) is routine, not a warning."""
    cmd = ["rsync", "-az", *_ssh_option(cfg), _target(cfg, remote_relative_path), str(local_path)]
    return _run(cmd, warn_on_failure=False)
