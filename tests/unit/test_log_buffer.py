from __future__ import annotations

import asyncio
import logging
import sys

from caelum.logging_conf import LogBuffer


def _log(buffer: LogBuffer, logger_name: str = "test", level: int = logging.INFO, msg: str = "hello") -> None:
    record = logging.LogRecord(
        name=logger_name, level=level, pathname=__file__, lineno=1, msg=msg, args=(), exc_info=None
    )
    buffer.handle(record)


def test_snapshot_reflects_emitted_records():
    buffer = LogBuffer()
    _log(buffer, msg="first")
    _log(buffer, msg="second")

    entries = buffer.snapshot()
    assert [e.message for e in entries] == ["first", "second"]
    assert entries[0].level == "INFO"
    assert entries[0].logger == "test"


def test_capacity_drops_the_oldest_entries_first():
    buffer = LogBuffer(capacity=3)
    for i in range(5):
        _log(buffer, msg=str(i))

    assert [e.message for e in buffer.snapshot()] == ["2", "3", "4"]


def test_exception_info_is_included_in_the_message():
    buffer = LogBuffer()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname=__file__, lineno=1, msg="failed", args=(), exc_info=True
        )
        record.exc_info = sys.exc_info()
        buffer.handle(record)

    entry = buffer.snapshot()[0]
    assert "failed" in entry.message
    assert "ValueError: boom" in entry.message
    assert entry.level == "ERROR"


def test_a_record_with_percent_style_args_is_formatted():
    buffer = LogBuffer()
    record = logging.LogRecord(
        name="test", level=logging.WARNING, pathname=__file__, lineno=1, msg="value is %s", args=("42",), exc_info=None
    )
    buffer.handle(record)
    assert buffer.snapshot()[0].message == "value is 42"


def test_to_dict_round_trips_the_fields():
    buffer = LogBuffer()
    _log(buffer, msg="hi")
    entry = buffer.snapshot()[0]
    as_dict = entry.to_dict()
    assert as_dict == {
        "timestamp": entry.timestamp,
        "level": entry.level,
        "logger": entry.logger,
        "message": entry.message,
    }


async def test_subscribers_receive_new_entries_live():
    buffer = LogBuffer()
    loop = asyncio.get_running_loop()
    queue = buffer.subscribe(loop)

    _log(buffer, msg="live")
    entry = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert entry.message == "live"


async def test_unsubscribed_queue_receives_nothing_further():
    buffer = LogBuffer()
    loop = asyncio.get_running_loop()
    queue = buffer.subscribe(loop)
    buffer.unsubscribe(queue)

    _log(buffer, msg="after unsubscribe")
    await asyncio.sleep(0.05)
    assert queue.empty()


async def test_a_slow_subscriber_drops_oldest_rather_than_blocking_the_logger():
    buffer = LogBuffer()
    loop = asyncio.get_running_loop()
    queue = buffer.subscribe(loop)

    for i in range(600):  # comfortably over the queue's maxsize of 500
        _log(buffer, msg=str(i))
    await asyncio.sleep(0.05)

    assert queue.full()
    first = queue.get_nowait()
    assert first.message != "0", "the oldest entries should have been dropped, not the newest"


def test_a_broken_record_does_not_raise_out_of_emit():
    """A formatting bug in someone else's log call must not blow up
    whatever was logging, e.g. `logger.info("%s", not_enough_args)`."""
    buffer = LogBuffer()
    bad_record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1, msg="%s %s", args=("only one",), exc_info=None
    )
    buffer.handle(bad_record)  # must not raise
    assert buffer.snapshot() == []
