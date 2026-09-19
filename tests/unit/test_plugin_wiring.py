"""The built-in workers are loaded as plugins, not hardwired.

These assert the thing that was actually broken before: that the `enabled`
and `order` fields in `AppConfig.plugins` reach the two built-in derivative
workers at all.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from caelum.config.schema import AppConfig, PluginConfig
from caelum.derivatives.keogram import KeogramWorker
from caelum.derivatives.meteor_detection import MeteorDetectionWorker
from caelum.derivatives.pool import DerivativePool
from caelum.events import EventBus
from caelum.plugins.loader import PluginLoader


@pytest.fixture
def loader() -> PluginLoader:
    return PluginLoader([KeogramWorker, MeteorDetectionWorker])


def test_built_in_workers_are_enabled_by_default(loader):
    loaded = loader.load(AppConfig())
    assert [lp.id for lp in loaded] == ["keogram", "meteor_detection"]


def test_disabling_a_built_in_worker_stops_it_loading(loader):
    config = AppConfig(plugins={"keogram": PluginConfig(enabled=False), "meteor_detection": PluginConfig()})
    assert [lp.id for lp in loader.load(config)] == ["meteor_detection"]


def test_order_governs_load_sequence(loader):
    config = AppConfig(
        plugins={
            "keogram": PluginConfig(order=99),
            "meteor_detection": PluginConfig(order=1),
        }
    )
    assert [lp.id for lp in loader.load(config)] == ["meteor_detection", "keogram"]


def test_settings_reach_the_worker(loader):
    config = AppConfig(
        plugins={"keogram": PluginConfig(settings={"column_width": 7, "strip_height": 64})}
    )
    keogram = next(lp.plugin for lp in loader.load(config) if lp.id == "keogram")
    assert keogram._column_width == 7
    assert keogram._strip_height == 64


def test_invalid_settings_skip_the_plugin_rather_than_crashing(loader):
    config = AppConfig(plugins={"keogram": PluginConfig(settings={"column_width": -5})})
    assert loader.load(config) == []


def test_registering_injects_the_process_pool(tmp_path):
    """MeteorDetectionWorker needs a pool but is constructed from settings
    alone — DerivativePool supplies it on register()."""
    pool = DerivativePool(EventBus(), None, tmp_path, max_process_workers=1)
    try:
        worker = MeteorDetectionWorker()
        assert worker.process_pool is None
        pool.register(worker)
        assert worker.process_pool is pool.process_pool
    finally:
        pool.shutdown()


def test_meteor_worker_runs_without_a_pool():
    """Usable standalone — the pool is an optimisation, not a dependency."""
    import numpy as np

    from tests.factories import make_processed_frame

    worker = MeteorDetectionWorker({"max_dim": 64})
    blank = make_processed_frame(image=np.zeros((64, 64, 3), dtype=np.uint8))

    # Two rows, not one: a 1px-tall line has a contourArea of 0 and is
    # rejected by min_area, which is the detector working as intended.
    streaked_image = np.zeros((64, 64, 3), dtype=np.uint8)
    streaked_image[30:32, 10:50] = 255
    streaked = make_processed_frame(image=streaked_image)

    worker.on_frame(blank)
    worker.on_frame(streaked)
    assert worker.provide_overlay_elements(streaked), "no detection without a process pool"


def test_replace_all_swaps_the_worker_set(tmp_path):
    pool = DerivativePool(EventBus(), None, tmp_path, max_process_workers=1)
    try:
        pool.register_all([KeogramWorker(), MeteorDetectionWorker()])
        pool.replace_all([KeogramWorker()])
        assert [type(w).__name__ for w in pool._workers] == ["KeogramWorker"]
    finally:
        pool.shutdown()


def test_thread_pool_executor_satisfies_the_process_pool_slot():
    """The slot is typed as Executor, so a thread pool works in tests."""
    worker = MeteorDetectionWorker()
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker.process_pool = executor
        assert worker.process_pool is executor
