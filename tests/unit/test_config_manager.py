from __future__ import annotations

import asyncio
from pathlib import Path

import redis.asyncio as redis

from caelum.config import store_disk, store_redis
from caelum.config.manager import ConfigManager
from caelum.config.schema import AppConfig


async def _manager(tmp_path: Path, redis_url: str, debounce: float = 0.05) -> ConfigManager:
    mgr = ConfigManager(
        disk_path=tmp_path / "config.json",
        default_path=None,
        redis_url=redis_url,
        key_prefix="caelumtest",
        debounce_seconds=debounce,
    )
    await mgr.start()
    return mgr


async def test_start_with_nothing_persisted_uses_defaults(tmp_path, redis_url):
    mgr = await _manager(tmp_path, redis_url)
    try:
        assert mgr.current == AppConfig()
        assert (tmp_path / "config.json").exists(), "startup should persist the resolved config to disk"
    finally:
        await mgr.stop()


async def test_update_applies_immediately_and_flushes_after_debounce(tmp_path, redis_url):
    mgr = await _manager(tmp_path, redis_url, debounce=0.05)
    try:
        updated = await mgr.update({"location": {"lat": 12.34}})
        assert updated.location.lat == 12.34
        assert mgr.current.location.lat == 12.34, "in-memory config must update immediately"

        # Before the debounce window elapses, don't assert on disk state (timing-fragile);
        # after it elapses, disk + Redis must both reflect the change.
        await asyncio.sleep(0.2)

        on_disk = store_disk.read(tmp_path / "config.json")
        assert on_disk is not None
        assert on_disk.location.lat == 12.34

        client = redis.from_url(redis_url, decode_responses=True)
        try:
            in_redis = await store_redis.read(client, "caelumtest")
            assert in_redis is not None
            assert in_redis.location.lat == 12.34
        finally:
            await client.aclose()
    finally:
        await mgr.stop()


async def test_partial_patch_does_not_clobber_sibling_fields(tmp_path, redis_url):
    mgr = await _manager(tmp_path, redis_url)
    try:
        await mgr.update({"location": {"lat": 1.0}})
        updated = await mgr.update({"location": {"lon": 2.0}})
        assert updated.location.lat == 1.0
        assert updated.location.lon == 2.0
    finally:
        await mgr.stop()


async def test_config_version_increments_on_each_update(tmp_path, redis_url):
    mgr = await _manager(tmp_path, redis_url)
    try:
        start_version = mgr.current.config_version
        updated = await mgr.update({"location": {"lat": 5.0}})
        assert updated.config_version == start_version + 1
    finally:
        await mgr.stop()


async def test_startup_reconciliation_disk_wins_when_redis_is_older(tmp_path, redis_url):
    disk_path = tmp_path / "config.json"
    disk_cfg = AppConfig(config_version=5, location={"lat": 9.0})
    store_disk.write(disk_path, disk_cfg)

    client = redis.from_url(redis_url, decode_responses=True)
    try:
        await store_redis.write(client, "caelumtest", AppConfig(config_version=2, location={"lat": 1.0}))
    finally:
        await client.aclose()

    mgr = ConfigManager(disk_path, None, redis_url, key_prefix="caelumtest")
    await mgr.start()
    try:
        assert mgr.current.config_version == 5
        assert mgr.current.location.lat == 9.0
    finally:
        await mgr.stop()


async def test_startup_reconciliation_redis_wins_when_strictly_newer(tmp_path, redis_url):
    disk_path = tmp_path / "config.json"
    store_disk.write(disk_path, AppConfig(config_version=2, location={"lat": 1.0}))

    client = redis.from_url(redis_url, decode_responses=True)
    try:
        await store_redis.write(client, "caelumtest", AppConfig(config_version=7, location={"lat": 42.0}))
    finally:
        await client.aclose()

    mgr = ConfigManager(disk_path, None, redis_url, key_prefix="caelumtest")
    await mgr.start()
    try:
        assert mgr.current.config_version == 7
        assert mgr.current.location.lat == 42.0
        # disk must be rewritten to match after reconciliation
        on_disk = store_disk.read(disk_path)
        assert on_disk is not None
        assert on_disk.config_version == 7
    finally:
        await mgr.stop()


async def test_change_subscribers_are_notified(tmp_path, redis_url):
    mgr = await _manager(tmp_path, redis_url)
    seen: list[AppConfig] = []
    mgr.on_change(seen.append)
    try:
        await mgr.update({"location": {"lat": 3.0}})
        assert len(seen) == 1
        assert seen[0].location.lat == 3.0
    finally:
        await mgr.stop()


async def test_redis_unreachable_falls_back_to_disk_only(tmp_path):
    mgr = ConfigManager(
        disk_path=tmp_path / "config.json",
        default_path=None,
        redis_url="redis://127.0.0.1:1/0",  # nothing listens on port 1
        key_prefix="caelumtest",
    )
    await mgr.start()
    try:
        assert mgr.current == AppConfig()
        updated = await mgr.update({"location": {"lat": 55.0}})
        assert updated.location.lat == 55.0
    finally:
        await mgr.stop()
