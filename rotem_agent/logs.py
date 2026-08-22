"""File logging, so a failure can be read after the fact.

The console transcript is the agent's account of what it did, but a background
watcher outlives the terminal it was started from, and the interesting output is
always the run that already scrolled away. Everything printed is therefore
mirrored to a rotating file.

The console stream is wrapped rather than every print statement rewritten. That
keeps the console output exactly as it reads today, and it captures tracebacks
from code that knows nothing about logging, which is precisely the output worth
having when something breaks.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from rotem_agent.config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
LOG_PATH = LOG_DIR / "agent.log"
LOGGER_NAME = "rotem"

# Five files of two megabytes each. Hebrew is multi-byte in UTF-8, so this is
# roughly a few weeks of watching rather than the months the size suggests.
_MAX_BYTES = 2_000_000
_BACKUP_COUNT = 5


def logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


class _Tee:
    """Writes to the original stream and mirrors completed lines to the log."""

    def __init__(self, stream: TextIO, level: int) -> None:
        self._stream = stream
        self._level = level
        self._pending = ""

    def write(self, text: str) -> int:
        written = self._stream.write(text)
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            if line.strip():
                logger().log(self._level, line.rstrip())
        return written

    def flush(self) -> None:
        self._stream.flush()
        if self._pending.strip():
            logger().log(self._level, self._pending.rstrip())
            self._pending = ""

    def __getattr__(self, name: str):
        # Indexing __dict__ rather than attribute access, so a lookup before
        # __init__ finishes raises instead of recursing forever.
        return getattr(self.__dict__["_stream"], name)


def setup(command: str, *, mirror_console: bool = True, log_dir: Path | None = None) -> Path:
    """Attach the file handler once per process and return the log path."""
    directory = log_dir or LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOG_PATH.name

    log = logger()
    if any(isinstance(handler, RotatingFileHandler) for handler in log.handlers):
        return path

    handler = RotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info("-" * 70)
    log.info("start: %s (pid %s)", command, os.getpid())

    if mirror_console:
        # stderr at ERROR level so a traceback stands out from the transcript.
        sys.stdout = _Tee(sys.stdout, logging.INFO)  # type: ignore[assignment]
        sys.stderr = _Tee(sys.stderr, logging.ERROR)  # type: ignore[assignment]
    return path
