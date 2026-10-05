"""scp transport — the same push_tree/push_file/pull_file surface as
transport_rsync.py, for servers that offer SSH with scp/sftp but no rsync
(hosting accounts, some NAS boxes, restricted shells).

scp copies whole files and knows nothing about what is already there, so
push_tree does its own comparison, like the S3 transport: one `find` over
SSH lists the remote tree with sizes and times, and only files that are
missing remotely, differ in size, or are newer locally get copied — with
`scp -p`, so the remote times match and the next comparison is exact. One
`mkdir -p` creates every directory needed, then files go up in batches per
directory. That keeps the reconciliation pass in uploader.py idempotent and
self-healing: a transfer cut short leaves a file of the wrong size, which
the next pass copies again.

The remote needs a POSIX shell with GNU `find` (for `-printf`); without it
the listing is empty and every pass re-copies everything (with a warning).
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath

from caelum.config.schema import UploadConfig

from .ssh import destination, ssh_command, ssh_options
from .stats import TransferStats

logger = logging.getLogger(__name__)

#: Files per scp invocation — keeps the command line well within limits.
_BATCH = 100
#: Remote times come back with sub-second precision, local ones may not
#: survive the round trip exactly; anything within this counts as equal.
_MTIME_SLACK_S = 1.0
_TIMEOUT_S = 600


def _remote_path(cfg: UploadConfig, relative_path: str) -> str:
    base = cfg.remote_base_path.rstrip("/") or "/"
    return str(PurePosixPath(base) / relative_path) if relative_path else base


def _ssh(cfg: UploadConfig, command: str, stats: TransferStats | None = None) -> subprocess.CompletedProcess | None:
    cmd = [*ssh_command(cfg), destination(cfg), command]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        logger.warning("ssh to %s timed out: %s", cfg.remote_host, command)
        if stats is not None:
            stats.error(f"ssh to {cfg.remote_host} timed out")
        return None
    if result.returncode != 0:
        logger.warning("ssh to %s failed (%s): %s", cfg.remote_host, command, result.stderr.strip())
        if stats is not None:
            stats.error(f"ssh to {cfg.remote_host} failed (exit {result.returncode}): {result.stderr.strip()}")
        return None
    return result


def _scp(cfg: UploadConfig, sources: list[str], target: str, warn_on_failure: bool = True,
         stats: TransferStats | None = None) -> bool:
    limit = ["-l", str(cfg.bandwidth_limit_kbps * 8)] if cfg.bandwidth_limit_kbps else []  # scp: Kbit/s
    cmd = ["scp", "-p", "-q", "-B", *ssh_options(cfg), "-P", str(cfg.ssh_port), *limit, *sources, target]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        logger.warning("scp to %s timed out", target)
        if stats is not None:
            stats.error(f"scp to {target} timed out")
        return False
    if result.returncode != 0:
        (logger.warning if warn_on_failure else logger.debug)("scp to %s failed: %s", target, result.stderr.strip())
        if stats is not None and warn_on_failure:
            stats.error(f"scp to {target} failed (exit {result.returncode}): {result.stderr.strip()}")
        return False
    if stats is not None:
        stats.sent(len(sources), sum(_size(s) for s in sources))
    return True


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _configured(cfg: UploadConfig, stats: TransferStats | None = None) -> bool:
    if not cfg.remote_host:
        logger.warning("scp upload needs upload.remote_host")
        if stats is not None:
            stats.error("scp upload needs upload.remote_host")
        return False
    return True


def _list_remote(cfg: UploadConfig, remote_dir: str,
                 stats: TransferStats | None = None) -> dict[str, tuple[int, float]] | None:
    """{relative path: (size, mtime)} of every file under `remote_dir`; an
    empty dict if it doesn't exist yet, None if the listing failed."""
    quoted = shlex.quote(remote_dir)
    result = _ssh(cfg, f"if [ -d {quoted} ]; then cd {quoted} && find . -type f -printf '%P\\t%s\\t%T@\\n'; fi",
                  stats)
    if result is None:
        return None
    remote = {}
    for line in result.stdout.splitlines():
        try:
            path, size, mtime = line.split("\t")
            remote[path] = (int(size), float(mtime))
        except ValueError:
            continue
    return remote


def _needs_upload(path: Path, remote: tuple[int, float] | None) -> bool:
    if remote is None:
        return True
    size, mtime = remote
    stat = path.stat()
    return stat.st_size != size or stat.st_mtime > mtime + _MTIME_SLACK_S


def push_tree(cfg: UploadConfig, local_dir: Path, remote_relative_path: str,
              stats: TransferStats | None = None) -> bool:
    """Push an entire directory's contents, recursively. One-way archival:
    never deletes anything remotely. Skips the hidden `.<name>.tmp` files
    atomic writers rename into place, like the other transports."""
    if not local_dir.exists():
        return True  # nothing to push yet is not a failure
    if not _configured(cfg, stats):
        return False
    remote_dir = _remote_path(cfg, remote_relative_path)
    remote = _list_remote(cfg, remote_dir, stats)
    if remote is None:
        return False
    if not remote and any(local_dir.iterdir()):
        logger.debug("scp: nothing listed under %s:%s yet", cfg.remote_host, remote_dir)

    by_dir: dict[str, list[Path]] = defaultdict(list)
    for dirpath, _dirnames, filenames in os.walk(local_dir):
        for name in sorted(filenames):
            if name.startswith(".") and name.endswith(".tmp"):
                continue
            path = Path(dirpath) / name
            relative = path.relative_to(local_dir).as_posix()
            try:
                if _needs_upload(path, remote.get(relative)):
                    by_dir[str(PurePosixPath(relative).parent)].append(path)
            except FileNotFoundError:
                continue  # removed locally (e.g. by retention) meanwhile
    if not by_dir:
        return True

    targets = {d: _remote_path(cfg, str(PurePosixPath(remote_relative_path) / d) if d != "." else remote_relative_path)
               for d in by_dir}
    if _ssh(cfg, "mkdir -p " + " ".join(shlex.quote(t) for t in sorted(set(targets.values()))), stats) is None:
        return False
    ok = True
    for directory, files in sorted(by_dir.items()):
        existing = [str(p) for p in files if p.exists()]
        for start in range(0, len(existing), _BATCH):
            batch = existing[start:start + _BATCH]
            ok = _scp(cfg, batch, f"{destination(cfg)}:{targets[directory]}/", stats=stats) and ok
    return ok


def push_file(cfg: UploadConfig, local_path: Path, remote_relative_path: str,
              stats: TransferStats | None = None) -> bool:
    if not local_path.exists() or not _configured(cfg, stats):
        return False
    target = _remote_path(cfg, remote_relative_path)
    parent = str(PurePosixPath(target).parent)
    if _ssh(cfg, f"mkdir -p {shlex.quote(parent)}", stats) is None:
        return False
    return _scp(cfg, [str(local_path)], f"{destination(cfg)}:{target}", stats=stats)


def pull_file(cfg: UploadConfig, remote_relative_path: str, local_path: Path) -> bool:
    """Fetch one file — used to read back the shared `cameras.json`. Not
    finding it yet (first camera, first boot) is routine, not a warning."""
    if not cfg.remote_host:
        return False
    return _scp(cfg, [f"{destination(cfg)}:{_remote_path(cfg, remote_relative_path)}"], str(local_path),
                warn_on_failure=False)
