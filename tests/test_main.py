import logging
import re

from inkcast.__main__ import utc_formatter


def test_log_timestamps_are_utc() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello", None, None)
    record.created = 0.0  # 1970-01-01T00:00:00Z
    record.msecs = 0

    line = utc_formatter().format(record)

    assert line == "1970-01-01T00:00:00.000Z INFO x: hello"
    assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z ", line)
