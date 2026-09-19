"""Redis-side of AppConfig persistence: the fast runtime store + pub/sub.

Redis is a convenience, never a hard dependency — every function here is
expected to be wrapped by callers in a try/except that falls back to disk
alone if Redis is unreachable (see manager.py).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import redis.asyncio as redis

from .schema import AppConfig

logger = logging.getLogger(__name__)


def _config_key(prefix: str) -> str:
    return f"{prefix}:config"


def _version_key(prefix: str) -> str:
    return f"{prefix}:config:version"


def _channel(prefix: str) -> str:
    return f"{prefix}:config:changed"


async def read(client: redis.Redis, key_prefix: str) -> AppConfig | None:
    raw = await client.get(_config_key(key_prefix))
    if raw is None:
        return None
    return AppConfig.model_validate_json(raw)


async def write(client: redis.Redis, key_prefix: str, config: AppConfig) -> None:
    async with client.pipeline(transaction=True) as pipe:
        pipe.set(_config_key(key_prefix), config.model_dump_json())
        pipe.set(_version_key(key_prefix), config.config_version)
        await pipe.execute()


async def read_version(client: redis.Redis, key_prefix: str) -> int | None:
    raw = await client.get(_version_key(key_prefix))
    return int(raw) if raw is not None else None


async def publish_changed(client: redis.Redis, key_prefix: str, version: int) -> None:
    await client.publish(_channel(key_prefix), str(version))


async def subscribe_changed(client: redis.Redis, key_prefix: str) -> AsyncIterator[int]:
    pubsub = client.pubsub()
    await pubsub.subscribe(_channel(key_prefix))
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                yield int(message["data"])
            except (TypeError, ValueError):
                logger.warning("Ignoring malformed config-change notification: %r", message)
    finally:
        await pubsub.unsubscribe(_channel(key_prefix))
        await pubsub.aclose()
