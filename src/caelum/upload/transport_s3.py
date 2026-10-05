"""S3 transport — the same push_tree/push_file/pull_file surface as
transport_rsync.py, against any S3-compatible object store (CESNET, MinIO,
Ceph RGW, AWS).

S3 has no rsync-style delta transfer, so push_tree does its own cheap
comparison instead: one listing of the remote prefix, then only files that
are missing remotely, differ in size, or were modified locally after the
remote copy was written get uploaded. That keeps the reconciliation pass in
uploader.py idempotent and self-healing exactly as with rsync — re-running
it after a failure just uploads whatever is still missing.
"""

from __future__ import annotations

import functools
import logging
import mimetypes
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from caelum.config.schema import UploadConfig

logger = logging.getLogger(__name__)

# Not in Python's default mimetypes table.
_CONTENT_TYPES = {".dng": "image/x-adobe-dng", ".json": "application/json"}


@functools.lru_cache(maxsize=4)
def _make_client(endpoint_url: str, profile: str) -> Any:
    # Imported lazily so rsync-only installs never pay for boto3's import.
    import boto3
    from botocore.config import Config

    session = boto3.Session(profile_name=profile or None)
    return session.client(
        "s3",
        endpoint_url=endpoint_url or None,
        config=Config(
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 3, "mode": "standard"},
            # botocore >= 1.36 adds CRC checksums to every PUT by default,
            # which many non-AWS stores (Ceph RGW included) reject.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def _client(cfg: UploadConfig) -> Any:
    return _make_client(cfg.s3_endpoint_url, cfg.s3_profile)


def _key(cfg: UploadConfig, relative_path: str) -> str:
    return "/".join(part.strip("/") for part in (cfg.s3_prefix, relative_path) if part.strip("/"))


def _extra_args(cfg: UploadConfig, path: Path) -> dict[str, str]:
    content_type = _CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    args = {"ContentType": content_type or "application/octet-stream"}
    if path.suffix.lower() == ".json":
        # Manifests are rewritten in place every cycle; without this a CDN
        # or browser would keep serving a stale date list.
        args["CacheControl"] = "no-cache"
    if cfg.s3_acl:
        args["ACL"] = cfg.s3_acl
    return args


def _is_s3_error(exc: Exception) -> bool:
    from botocore.exceptions import BotoCoreError, ClientError

    return isinstance(exc, BotoCoreError | ClientError)


def _list_remote(cfg: UploadConfig, prefix: str) -> dict[str, tuple[int, datetime]]:
    """Every object under `prefix` as {key: (size, last_modified)}."""
    client = _client(cfg)
    remote: dict[str, tuple[int, datetime]] = {}
    kwargs: dict[str, Any] = {"Bucket": cfg.s3_bucket, "Prefix": f"{prefix}/" if prefix else ""}
    while True:
        page = client.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []):
            remote[obj["Key"]] = (obj["Size"], obj["LastModified"])
        if not page.get("IsTruncated"):
            return remote
        kwargs["ContinuationToken"] = page["NextContinuationToken"]


def _needs_upload(path: Path, remote: tuple[int, datetime] | None) -> bool:
    if remote is None:
        return True
    size, last_modified = remote
    stat = path.stat()
    return stat.st_size != size or datetime.fromtimestamp(stat.st_mtime, UTC) > last_modified


def _upload(cfg: UploadConfig, path: Path, key: str) -> bool:
    try:
        _client(cfg).upload_file(str(path), cfg.s3_bucket, key, ExtraArgs=_extra_args(cfg, path))
    except FileNotFoundError:
        return True  # removed locally (e.g. by retention) between listing and upload
    except Exception as exc:
        if not _is_s3_error(exc):
            raise
        logger.warning("S3 upload of %s to s3://%s/%s failed: %s", path, cfg.s3_bucket, key, exc)
        return False
    return True


def push_tree(cfg: UploadConfig, local_dir: Path, remote_relative_path: str) -> bool:
    """Push an entire directory's contents, recursively. One-way archival:
    never deletes anything remotely. Skips the hidden `.<name>.tmp` files
    atomic writers rename into place, like the rsync transport does."""
    if not local_dir.exists():
        return True  # nothing to push yet is not a failure
    prefix = _key(cfg, remote_relative_path)
    try:
        remote = _list_remote(cfg, prefix)
    except Exception as exc:
        if not _is_s3_error(exc):
            raise
        logger.warning("S3 listing of s3://%s/%s failed: %s", cfg.s3_bucket, prefix, exc)
        return False

    ok = True
    for dirpath, _dirnames, filenames in os.walk(local_dir):
        for name in sorted(filenames):
            if name.startswith(".") and name.endswith(".tmp"):
                continue
            path = Path(dirpath) / name
            key = "/".join(filter(None, (prefix, path.relative_to(local_dir).as_posix())))
            try:
                if not _needs_upload(path, remote.get(key)):
                    continue
            except FileNotFoundError:
                continue
            ok = _upload(cfg, path, key) and ok
    return ok


def push_file(cfg: UploadConfig, local_path: Path, remote_relative_path: str) -> bool:
    if not local_path.exists():
        return False
    return _upload(cfg, local_path, _key(cfg, remote_relative_path))


def pull_file(cfg: UploadConfig, remote_relative_path: str, local_path: Path) -> bool:
    """Fetch one object — used to read back the shared `cameras.json`. Not
    finding it yet (first camera, first boot) is routine, not a warning."""
    key = _key(cfg, remote_relative_path)
    try:
        _client(cfg).download_file(cfg.s3_bucket, key, str(local_path))
    except Exception as exc:
        if not _is_s3_error(exc):
            raise
        logger.debug("S3 download of s3://%s/%s failed: %s", cfg.s3_bucket, key, exc)
        return False
    return True
