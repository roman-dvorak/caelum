"""`modify_image` is declared on `DerivativeWorker`/`Plugin` and documented as
chained in `order` — these prove `DerivativePool` actually dispatches it that
way, rather than leaving it a declared-but-dead hook (see
`DerivativePool._run_modify_chain`).
"""

from __future__ import annotations

import numpy as np

from caelum.derivatives.base import DerivativeWorker
from caelum.derivatives.pool import DerivativePool
from caelum.events import EventBus
from tests.factories import make_processed_frame


class AddTen(DerivativeWorker):
    id = "add_ten"

    def modify_image(self, image, frame):
        return image + 10


class DoubleIt(DerivativeWorker):
    id = "double_it"

    def modify_image(self, image, frame):
        return image * 2


class Explodes(DerivativeWorker):
    id = "explodes"

    def modify_image(self, image, frame):
        raise RuntimeError("boom")


class RecordsWhatItSaw(DerivativeWorker):
    id = "recorder"

    def __init__(self) -> None:
        self.seen: np.ndarray | None = None

    def on_frame(self, frame) -> None:
        self.seen = frame.image


def _pool(tmp_path) -> DerivativePool:
    return DerivativePool(EventBus(), frame_store=None, data_dir=tmp_path, max_process_workers=1)


def test_chain_feeds_one_workers_output_into_the_next(tmp_path):
    """Two plugins — one adds 10, the next doubles — chained in that order
    must produce (x + 10) * 2, not x * 2 + 10 and not either plugin alone;
    proving the chain actually threads output to input, not just "the last
    plugin wins" or "each plugin sees the untouched original"."""
    original = np.array([[1.0, 2.0], [3.0, 4.0]])
    frame = make_processed_frame(image=original)

    pool = _pool(tmp_path)
    try:
        pool.register_all([AddTen(), DoubleIt()])
        result = pool._run_modify_chain(frame)
    finally:
        pool.shutdown()

    np.testing.assert_array_equal(result.image, (original + 10) * 2)


def test_swapping_the_order_changes_the_result(tmp_path):
    """The same two plugins, registered in the opposite order, must produce
    a different — and specifically the algebraically-opposite-ordered —
    result: x * 2 + 10. This is the direct test that `order` has a real,
    visible effect on the outcome, not just on bookkeeping."""
    original = np.array([[1.0, 2.0], [3.0, 4.0]])
    frame = make_processed_frame(image=original)

    add_first = _pool(tmp_path)
    try:
        add_first.register_all([AddTen(), DoubleIt()])
        add_first_result = add_first._run_modify_chain(frame)
    finally:
        add_first.shutdown()

    double_first = _pool(tmp_path)
    try:
        double_first.register_all([DoubleIt(), AddTen()])
        double_first_result = double_first._run_modify_chain(frame)
    finally:
        double_first.shutdown()

    np.testing.assert_array_equal(add_first_result.image, (original + 10) * 2)
    np.testing.assert_array_equal(double_first_result.image, (original * 2) + 10)
    assert not np.array_equal(add_first_result.image, double_first_result.image)


def test_chain_returns_the_same_frame_object_when_no_worker_modifies_the_image(tmp_path):
    """The default `modify_image` is a no-op that returns its input
    unchanged — when every registered worker leaves it at that default, the
    chain must skip building a new frame at all (identity, not equality)."""
    frame = make_processed_frame(image=np.zeros((2, 2)))

    pool = _pool(tmp_path)
    try:
        pool.register_all([RecordsWhatItSaw(), RecordsWhatItSaw()])
        result = pool._run_modify_chain(frame)
    finally:
        pool.shutdown()

    assert result is frame


def test_downstream_workers_receive_the_chained_image(tmp_path):
    """What the chain produces is what the rest of the pipeline — every
    other worker's on_frame/create_derivative — actually sees next, not
    just a value the chain computes and discards."""
    frame = make_processed_frame(image=np.zeros((2, 2)))
    recorder = RecordsWhatItSaw()

    pool = _pool(tmp_path)
    try:
        pool.register_all([AddTen(), recorder])
        modified = pool._run_modify_chain(frame)
        pool._run_worker(recorder, modified)
    finally:
        pool.shutdown()

    np.testing.assert_array_equal(recorder.seen, np.full((2, 2), 10.0))


def test_a_failing_plugin_does_not_break_the_chain_for_the_rest(tmp_path):
    """One plugin raising must not stop the ones after it from running, and
    must not crash frame processing — it passes the image through
    unchanged and the chain continues."""
    original = np.array([[1.0, 2.0]])
    frame = make_processed_frame(image=original)

    pool = _pool(tmp_path)
    try:
        pool.register_all([AddTen(), Explodes(), DoubleIt()])
        result = pool._run_modify_chain(frame)
    finally:
        pool.shutdown()

    np.testing.assert_array_equal(result.image, (original + 10) * 2)


def test_frame_metadata_and_stats_are_unchanged_by_the_chain(tmp_path):
    """Only `.image` moves through the chain — the rest of the frame
    (metadata, stats, the already-encoded thumbnail) is untouched, since
    those were fixed on the capture thread before any plugin ran."""
    frame = make_processed_frame(image=np.zeros((2, 2)))

    pool = _pool(tmp_path)
    try:
        pool.register_all([AddTen()])
        result = pool._run_modify_chain(frame)
    finally:
        pool.shutdown()

    assert result.metadata == frame.metadata
    assert result.stats == frame.stats
    assert result.thumbnail_jpeg == frame.thumbnail_jpeg
