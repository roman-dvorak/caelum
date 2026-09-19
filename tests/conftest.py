from __future__ import annotations

import socket
import subprocess
import time
from collections.abc import Iterator

import pytest
import redis as sync_redis


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def redis_url() -> Iterator[str]:
    """Spin up a throwaway real redis-server for the duration of one test —
    ConfigManager talks to Redis for real, so tests should too."""
    port = _free_port()
    proc = subprocess.Popen(
        [
            "redis-server",
            "--port", str(port),
            "--bind", "127.0.0.1",
            "--save", "",
            "--appendonly", "no",
            "--daemonize", "no",
            "--loglevel", "warning",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"redis://127.0.0.1:{port}/0"
    try:
        client = sync_redis.from_url(url)
        deadline = time.monotonic() + 5.0
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            try:
                if client.ping():
                    break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        else:
            raise RuntimeError(f"redis-server did not become ready: {last_exc}")
        client.close()
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
