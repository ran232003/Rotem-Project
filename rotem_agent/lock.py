"""Making sure only one watcher runs at a time.

Two watchers against one mailbox draft the same message twice. The ledger does
not prevent it: each process loads it at startup, both decide a new message is
unanswered, and the later write simply wins. Observed in practice, from a
stopped terminal whose Python child kept running: one message, two drafts in
Outlook, and the spend of the process that lost the race recorded nowhere.

The lock is held by the operating system for the lifetime of the process rather
than being a file the code has to remember to delete. A killed watcher therefore
releases it immediately, and there is no stale lock to reason about. Checking a
recorded PID instead would be worse than useless on Windows, where os.kill with
signal 0 terminates the process rather than testing it.
"""

from __future__ import annotations

import os
from pathlib import Path

from rotem_agent.state import STATE_DIR

# The lock is taken on a byte past any content, because on Windows a byte-range
# lock blocks reads as well as writes and the PID has to stay readable by the
# process that is being turned away.
_LOCK_OFFSET = 4096


class AlreadyRunning(RuntimeError):
    pass


class SingleInstance:
    """An exclusive claim on one activity, released when the process ends."""

    def __init__(self, name: str = "watch", path: Path | str | None = None) -> None:
        self.path = Path(path) if path else STATE_DIR / f"{name}.lock"
        self._handle = None

    def acquire(self) -> "SingleInstance":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            _take(handle)
        except OSError:
            holder = self._holder()
            handle.close()
            raise AlreadyRunning(
                f"Another watcher is already running{holder}. "
                "Two watchers would draft every message twice."
            ) from None

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        self._handle = handle
        return self

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            _release(self._handle)
        except OSError:
            pass
        self._handle.close()
        self._handle = None

    def _holder(self) -> str:
        try:
            pid = self.path.read_bytes()[:_LOCK_OFFSET].decode("ascii").strip()
        except (OSError, UnicodeDecodeError):
            return ""
        return f" (pid {pid})" if pid.isdigit() else ""

    def __enter__(self) -> "SingleInstance":
        return self.acquire()

    def __exit__(self, *exc_info) -> None:
        self.release()


def _take(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(_LOCK_OFFSET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(_LOCK_OFFSET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
