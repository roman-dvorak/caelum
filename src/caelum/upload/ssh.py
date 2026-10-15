"""SSH settings shared by the rsync and scp transports."""

from __future__ import annotations

from caelum.config.schema import UploadConfig


def ssh_options(cfg: UploadConfig) -> list[str]:
    """Options common to `ssh` and `scp` (except the port, whose flag
    differs: `-p` for ssh, `-P` for scp). Never prompts: a missing key or
    an unreachable host fails fast instead of hanging the upload thread."""
    return [
        "-i", cfg.ssh_key_path,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=30",
    ]


def destination(cfg: UploadConfig) -> str:
    return f"{cfg.remote_user}@{cfg.remote_host}" if cfg.remote_user else cfg.remote_host


def ssh_command(cfg: UploadConfig) -> list[str]:
    return ["ssh", *ssh_options(cfg), "-p", str(cfg.ssh_port)]
