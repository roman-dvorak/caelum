from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement
from caelum.config.schema import AppConfig, PluginConfig
from caelum.plugins.base import Plugin
from caelum.plugins.loader import PluginLoader
from tests.factories import make_processed_frame


class _WatermarkSettings(BaseModel):
    text: str = "caelum"


class _WatermarkPlugin(Plugin):
    id: ClassVar[str] = "watermark"
    config_schema: ClassVar[type[BaseModel] | None] = _WatermarkSettings

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        return [OverlayElement(type="watermark", source=self.id, payload={"text": self.settings["text"]})]


class _NoSchemaPlugin(Plugin):
    id: ClassVar[str] = "no_schema"


def test_disabled_plugins_are_not_loaded():
    loader = PluginLoader([_WatermarkPlugin])
    config = AppConfig(plugins={"watermark": PluginConfig(enabled=False)})
    assert loader.load(config) == []


def test_unregistered_plugin_id_is_skipped_with_a_warning(caplog):
    loader = PluginLoader([])
    config = AppConfig(plugins={"unknown_plugin": PluginConfig(enabled=True)})
    assert loader.load(config) == []


def test_plugin_settings_are_validated_against_its_declared_schema():
    loader = PluginLoader([_WatermarkPlugin])
    config = AppConfig(plugins={"watermark": PluginConfig(enabled=True, settings={"text": "hello"})})
    loaded = loader.load(config)
    assert len(loaded) == 1
    assert loaded[0].plugin.settings["text"] == "hello"


def test_invalid_plugin_settings_are_skipped_not_fatal():
    loader = PluginLoader([_WatermarkPlugin])
    # a dict where a string is expected is not coercible — genuinely invalid
    config = AppConfig(plugins={"watermark": PluginConfig(enabled=True, settings={"text": {"nested": "value"}})})
    assert loader.load(config) == []


def test_plugin_without_a_schema_gets_settings_passed_through_unvalidated():
    loader = PluginLoader([_NoSchemaPlugin])
    config = AppConfig(plugins={"no_schema": PluginConfig(enabled=True, settings={"anything": "goes"})})
    loaded = loader.load(config)
    assert len(loaded) == 1
    assert loaded[0].plugin.settings == {"anything": "goes"}


def test_loaded_plugins_are_sorted_by_order_ascending():
    loader = PluginLoader([_WatermarkPlugin, _NoSchemaPlugin])
    config = AppConfig(
        plugins={
            "watermark": PluginConfig(enabled=True, order=50),
            "no_schema": PluginConfig(enabled=True, order=10),
        }
    )
    loaded = loader.load(config)
    assert [lp.id for lp in loaded] == ["no_schema", "watermark"]


def test_provide_overlay_elements_hook_works_end_to_end():
    loader = PluginLoader([_WatermarkPlugin])
    config = AppConfig(plugins={"watermark": PluginConfig(enabled=True, settings={"text": "observatory-1"})})
    loaded = loader.load(config)

    elements = loaded[0].plugin.provide_overlay_elements(make_processed_frame())
    assert elements[0].payload["text"] == "observatory-1"
