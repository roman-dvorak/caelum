"""ConfigManager: the single place config is read from and written to.

Design (see the project plan for the full rationale):
- Disk is the durable source of truth; Redis is a fast-path/pub-sub
  convenience that the app is never blocked on.
- Every write goes: validate -> disk (atomic) -> Redis SET+version -> publish
  version on a change channel. Disk-first so a crash between steps never
  leaves Redis ahead of a config nothing has durably committed to.
- High-frequency changes apply to the in-memory config immediately; the
  disk+Redis flush is debounced to protect SD card write endurance.
- At startup, disk wins unless Redis holds a strictly newer, schema-valid
  config_version — then Redis wins and disk is rewritten to match. Either
  way both stores agree once start() returns.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import redis.asyncio as redis

from . import store_disk, store_redis
from .schema import AppConfig

logger = logging.getLogger(__name__)

ChangeCallback = Callable[[AppConfig], None]


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `patch` into `base`, returning a new dict. Dict
    values are merged key-by-key; any other value (including lists) fully
    replaces the base value — a partial `{"exposure_policy": {"presets":
    {"night": {...}}}}` patch therefore only touches the "night" preset."""
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class ConfigManager:
    def __init__(
        self,
        disk_path: Path,
        default_path: Path | None,
        redis_url: str,
        key_prefix: str = "caelum",
        debounce_seconds: float = 1.0,
    ) -> None:
        self._disk_path = disk_path
        self._default_path = default_path
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._debounce_seconds = debounce_seconds

        self._current: AppConfig = AppConfig()
        self._lock = threading.Lock()
        self._redis: redis.Redis | None = None
        self._flush_task: asyncio.Task | None = None
        self._listen_task: asyncio.Task | None = None
        self._subscribers: list[ChangeCallback] = []

    @property
    def current(self) -> AppConfig:
        """Thread-safe snapshot read — safe to call from CaptureWorker's thread."""
        with self._lock:
            return self._current

    def on_change(self, callback: ChangeCallback) -> None:
        """Register a callback invoked (from the event loop thread) whenever
        the resolved config changes, whether from a local update() or a
        remote Redis-originated change."""
        self._subscribers.append(callback)

    async def start(self) -> None:
        disk_cfg = store_disk.read(self._disk_path)
        base_cfg = disk_cfg or (self._default_path and store_disk.read(self._default_path)) or AppConfig()

        try:
            self._redis = redis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
        except Exception as exc:
            logger.warning("Redis unavailable at startup (%s) — running off disk config only", exc)
            self._redis = None

        redis_cfg: AppConfig | None = None
        redis_version: int | None = None
        if self._redis is not None:
            try:
                redis_cfg = await store_redis.read(self._redis, self._key_prefix)
                redis_version = await store_redis.read_version(self._redis, self._key_prefix)
            except Exception as exc:
                logger.warning("Failed reading config from Redis (%s)", exc)

        resolved = base_cfg
        if redis_cfg is not None and redis_version is not None and redis_version > base_cfg.config_version:
            resolved = redis_cfg
            logger.info(
                "Redis config_version=%d newer than disk=%d — Redis wins", redis_version, base_cfg.config_version
            )

        with self._lock:
            self._current = resolved

        # Make both stores agree right away, regardless of which one won.
        store_disk.write(self._disk_path, resolved)
        if self._redis is not None:
            try:
                await store_redis.write(self._redis, self._key_prefix, resolved)
            except Exception as exc:
                logger.warning("Failed writing reconciled config to Redis (%s)", exc)

        if self._redis is not None:
            self._listen_task = asyncio.create_task(self._listen_for_changes(), name="config-listen")

    async def stop(self) -> None:
        if self._listen_task is not None:
            self._listen_task.cancel()
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            await self._flush_now()
        if self._redis is not None:
            await self._redis.aclose()

    async def update(self, patch: dict[str, Any]) -> AppConfig:
        """Validate and apply a partial patch, bump config_version, apply it
        in-memory immediately, and schedule a debounced disk+Redis flush."""
        with self._lock:
            merged = _deep_merge(self._current.model_dump(mode="json"), patch)
            merged["config_version"] = self._current.config_version + 1
        new_config = AppConfig.model_validate(merged)

        with self._lock:
            self._current = new_config
        self._notify(new_config)
        self._schedule_flush()
        return new_config

    def _schedule_flush(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._debounced_flush(), name="config-flush")

    async def _debounced_flush(self) -> None:
        try:
            await asyncio.sleep(self._debounce_seconds)
        except asyncio.CancelledError:
            raise
        await self._flush_now()

    async def _flush_now(self) -> None:
        cfg = self.current
        store_disk.write(self._disk_path, cfg)
        if self._redis is not None:
            try:
                await store_redis.write(self._redis, self._key_prefix, cfg)
                await store_redis.publish_changed(self._redis, self._key_prefix, cfg.config_version)
            except Exception as exc:
                logger.warning("Failed flushing config to Redis (%s) — disk copy is still current", exc)

    async def _listen_for_changes(self) -> None:
        assert self._redis is not None
        try:
            async for version in store_redis.subscribe_changed(self._redis, self._key_prefix):
                if version <= self.current.config_version:
                    continue  # our own write echoing back, or stale
                try:
                    remote_cfg = await store_redis.read(self._redis, self._key_prefix)
                except Exception as exc:
                    logger.warning("Failed reading changed config from Redis (%s)", exc)
                    continue
                if remote_cfg is None:
                    continue
                with self._lock:
                    self._current = remote_cfg
                store_disk.write(self._disk_path, remote_cfg)
                self._notify(remote_cfg)
        except asyncio.CancelledError:
            pass

    def _notify(self, config: AppConfig) -> None:
        for callback in self._subscribers:
            try:
                callback(config)
            except Exception:
                logger.exception("Config-change subscriber raised")
