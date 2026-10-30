"""The last step of every frame in `DerivativePool`: collect each worker's
overlay elements, render them once, and store the result the way
`storage_policy.overlay_mode` says — a PNG under `overlays/`, burned into
the thumbnail WebP, or nothing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from caelum.capture.frame_store import FrameStore
from caelum.capture.metadata import FrameMetadata, OverlayElement
from caelum.capture.thumbnail import encode_webp
from caelum.config.schema import StoragePolicyConfig
from caelum.derivatives.base import DerivativeWorker
from caelum.derivatives.pool import DerivativePool
from caelum.events import EventBus
from caelum.storage import paths
from tests.factories import make_image, make_processed_frame

CAPTURED_AT = datetime(2026, 10, 16, 21, 0, 0, tzinfo=UTC)


class RedMaskLeftHalf(DerivativeWorker):
    id = "red_mask"

    def provide_overlay_elements(self, frame):
        return [OverlayElement(type="mask", source=self.id,
                               payload={"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0, "color": "#ff0000"})]


class Broken(DerivativeWorker):
    id = "broken"

    def on_frame(self, frame):
        raise RuntimeError("boom")


def _run(tmp_path, mode: str):
    config = SimpleNamespace(current=SimpleNamespace(storage_policy=StoragePolicyConfig(overlay_mode=mode)))
    store = FrameStore()
    pool = DerivativePool(EventBus(), store, tmp_path, max_process_workers=1, config_manager=config)
    pool.register_all([RedMaskLeftHalf(), Broken()])

    image = make_image(width=200, height=100, fill=0)
    frame = make_processed_frame(captured_at=CAPTURED_AT, image=image)
    thumb = paths.thumbnail_path(tmp_path, CAPTURED_AT)
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(encode_webp(image))
    paths.sidecar_path(thumb).write_text(frame.metadata.model_dump_json())
    frame = replace(frame, thumbnail_path=thumb)

    store.update(frame)
    pool._dispatch(frame)
    pool.shutdown()
    return thumb, store


def _sidecar(thumb) -> FrameMetadata:
    return FrameMetadata.model_validate_json(paths.sidecar_path(thumb).read_text())


def test_file_mode_writes_a_transparent_png_and_the_full_sidecar(tmp_path):
    thumb, store = _run(tmp_path, "file")

    png = tmp_path / "overlays" / "2026" / "10" / "16" / "20261016-210000.png"
    layer = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
    assert layer.shape == (100, 200, 4)
    assert tuple(layer[50, 40]) == (0, 0, 255, 255)  # BGRA red, opaque
    assert layer[50, 150, 3] == 0  # right half transparent

    metadata = _sidecar(thumb)
    assert metadata.overlay == "file"
    assert [(e.type, e.source) for e in metadata.overlay_elements] == [("mask", "red_mask")]

    latest = store.get_latest()
    assert latest.overlay_png == png.read_bytes()
    assert latest.metadata.overlay == "file"


def test_burn_mode_draws_into_the_webp_and_writes_no_png(tmp_path):
    thumb, store = _run(tmp_path, "burn")

    assert not (tmp_path / "overlays").exists()
    burned = cv2.imread(str(thumb))
    b, g, r = burned[50, 40]
    assert r > 200 and g < 60 and b < 60
    assert burned[50, 150].max() < 40  # still the black frame
    assert _sidecar(thumb).overlay == "burned"
    assert store.get_latest().overlay_png is not None  # the live view still stacks the layer


def test_off_mode_renders_nothing_but_still_records_every_element(tmp_path):
    thumb, store = _run(tmp_path, "off")

    assert not (tmp_path / "overlays").exists()
    metadata = _sidecar(thumb)
    assert metadata.overlay is None
    assert any(e.type == "mask" for e in metadata.overlay_elements)
    assert store.get_latest().overlay_png is None


@pytest.mark.parametrize("mode", ["file", "burn"])
def test_frame_without_a_stored_thumbnail_only_feeds_the_live_view(tmp_path, mode):
    store = FrameStore()
    pool = DerivativePool(EventBus(), store, tmp_path, max_process_workers=1, config_manager=SimpleNamespace(
        current=SimpleNamespace(storage_policy=StoragePolicyConfig(overlay_mode=mode))
    ))
    pool.register(RedMaskLeftHalf())
    frame = make_processed_frame(captured_at=CAPTURED_AT, image=np.zeros((10, 20, 3), np.uint8))
    store.update(frame)
    pool._dispatch(frame)
    pool.shutdown()

    assert store.get_latest().overlay_png is not None
    assert store.get_latest().metadata.overlay is None
    assert not (tmp_path / "overlays").exists()


def test_outputs_complete_is_published_only_once_the_overlay_is_on_disk(tmp_path):
    from caelum.events import FRAME_OUTPUTS_COMPLETE

    bus = EventBus()
    seen = []
    png = tmp_path / "overlays" / "2026" / "10" / "16" / "20261016-210000.png"
    bus.subscribe(FRAME_OUTPUTS_COMPLETE, lambda frame: seen.append(png.is_file()))

    config = SimpleNamespace(current=SimpleNamespace(storage_policy=StoragePolicyConfig(overlay_mode="file")))
    store = FrameStore()
    pool = DerivativePool(bus, store, tmp_path, max_process_workers=1, config_manager=config)
    pool.register_all([RedMaskLeftHalf()])
    image = make_image(width=200, height=100, fill=0)
    frame = make_processed_frame(captured_at=CAPTURED_AT, image=image)
    thumb = paths.thumbnail_path(tmp_path, CAPTURED_AT)
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(encode_webp(image))
    paths.sidecar_path(thumb).write_text(frame.metadata.model_dump_json())
    frame = replace(frame, thumbnail_path=thumb)
    store.update(frame)
    pool._dispatch(frame)
    pool.shutdown()

    assert seen == [True]


class SkyLayers(DerivativeWorker):
    id = "sky_layers"

    def provide_overlay_elements(self, frame):
        return [
            OverlayElement(type="mask", source=self.id, payload={"layer": "stars", "x": 0.0, "y": 0.0, "w": 0.5,
                                                                 "h": 1.0, "color": "#00ff00"}),
            OverlayElement(type="mask", source=self.id, payload={"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0,
                                                                 "color": "#ff0000"}),
        ]


def _run_layers(tmp_path, mode: str):
    config = SimpleNamespace(current=SimpleNamespace(storage_policy=StoragePolicyConfig(overlay_mode=mode)))
    store = FrameStore()
    pool = DerivativePool(EventBus(), store, tmp_path, max_process_workers=1, config_manager=config)
    pool.register_all([SkyLayers()])
    image = make_image(width=200, height=100, fill=0)
    frame = make_processed_frame(captured_at=CAPTURED_AT, image=image)
    thumb = paths.thumbnail_path(tmp_path, CAPTURED_AT)
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(encode_webp(image))
    paths.sidecar_path(thumb).write_text(frame.metadata.model_dump_json())
    store.update(replace(frame, thumbnail_path=thumb))
    pool._dispatch(replace(frame, thumbnail_path=thumb))
    pool.shutdown()
    return thumb, store


def test_file_mode_stores_each_layer_in_its_own_png(tmp_path):
    thumb, store = _run_layers(tmp_path, "file")

    folder = tmp_path / "overlays" / "2026" / "10" / "16"
    base = cv2.imread(str(folder / "20261016-210000.png"), cv2.IMREAD_UNCHANGED)
    stars = cv2.imread(str(folder / "20261016-210000.stars.png"), cv2.IMREAD_UNCHANGED)
    assert base[50, 40, 3] == 0 and base[50, 150, 3] == 255  # the unlayered mask only
    assert stars[50, 40, 3] == 255 and stars[50, 150, 3] == 0  # the layer only
    assert _sidecar(thumb).overlay_layers == ["stars"]
    assert list(store.get_latest().overlay_layer_pngs) == ["stars"]
    assert store.get_latest().metadata.overlay_layers == ["stars"]


def test_burn_mode_burns_the_layers_in_and_stores_none(tmp_path):
    thumb, _store = _run_layers(tmp_path, "burn")

    burned = cv2.imread(str(thumb))
    assert burned[50, 40][1] > 200 and burned[50, 150][2] > 200  # green layer and red mask both there
    assert _sidecar(thumb).overlay_layers == []
    assert not list((tmp_path / "overlays").glob("**/*")) if (tmp_path / "overlays").exists() else True
