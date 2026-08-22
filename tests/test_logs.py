"""The log file exists so a failure can be read after the terminal is gone."""

from __future__ import annotations

import logging

import pytest

from rotem_agent import logs


@pytest.fixture(autouse=True)
def _detach_handlers():
    """Leave the shared logger as it was found.

    A handler left pointing into a deleted tmp_path would fail on the next
    write, in an unrelated test.
    """
    log = logging.getLogger(logs.LOGGER_NAME)
    original = list(log.handlers)
    for handler in original:
        log.removeHandler(handler)
    yield
    for handler in list(log.handlers):
        handler.close()
        log.removeHandler(handler)
    for handler in original:
        log.addHandler(handler)


def _fresh_logger(tmp_path, monkeypatch=None):
    log = logging.getLogger(logs.LOGGER_NAME)
    path = logs.setup("test-command", mirror_console=False, log_dir=tmp_path)
    return log, path


def test_setup_writes_a_header_naming_the_command(tmp_path):
    log, path = _fresh_logger(tmp_path, None)
    for handler in log.handlers:
        handler.flush()
    assert "start: test-command" in path.read_text(encoding="utf-8")


def test_setup_is_idempotent(tmp_path):
    """The CLI may be invoked twice in one process; handlers must not stack."""
    log, _ = _fresh_logger(tmp_path, None)
    before = len(log.handlers)
    logs.setup("again", mirror_console=False, log_dir=tmp_path)
    assert len(log.handlers) == before


def test_hebrew_survives_the_round_trip(tmp_path):
    log, path = _fresh_logger(tmp_path, None)
    log.info("דחוף - מכתב מרשות האוכלוסין")
    for handler in log.handlers:
        handler.flush()
    assert "מכתב מרשות האוכלוסין" in path.read_text(encoding="utf-8")


def test_the_tee_forwards_to_the_console_and_the_log(tmp_path):
    log, path = _fresh_logger(tmp_path, None)

    class _Sink:
        def __init__(self):
            self.text = ""

        def write(self, value):
            self.text += value
            return len(value)

        def flush(self):
            pass

    sink = _Sink()
    tee = logs._Tee(sink, logging.INFO)
    tee.write("first line\nsecond line\n")
    for handler in log.handlers:
        handler.flush()

    assert sink.text == "first line\nsecond line\n"
    written = path.read_text(encoding="utf-8")
    assert "first line" in written and "second line" in written


def test_the_tee_holds_a_partial_line_until_it_is_flushed(tmp_path):
    log, path = _fresh_logger(tmp_path, None)

    class _Sink:
        def write(self, value):
            return len(value)

        def flush(self):
            pass

    tee = logs._Tee(_Sink(), logging.INFO)
    tee.write("no newline yet")
    for handler in log.handlers:
        handler.flush()
    assert "no newline yet" not in path.read_text(encoding="utf-8")

    tee.flush()
    for handler in log.handlers:
        handler.flush()
    assert "no newline yet" in path.read_text(encoding="utf-8")


def test_the_tee_passes_unknown_attributes_to_the_wrapped_stream(tmp_path):
    _fresh_logger(tmp_path, None)

    class _Sink:
        encoding = "utf-8"

        def write(self, value):
            return len(value)

    assert logs._Tee(_Sink(), logging.INFO).encoding == "utf-8"
