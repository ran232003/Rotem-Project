"""Starting and stopping the watcher from outside it.

The lawyer needs a button, which means something other than the watcher has to
be able to start it, see whether it is running, and stop it. All three are more
delicate than they look on Windows.

Liveness is asked of the lock rather than of a recorded PID. The lock is held by
the operating system for the lifetime of the process, so failing to take it is
proof that a watcher is alive, and it stays correct for a watcher someone
started from a terminal. Testing a PID would not: os.kill with signal 0
terminates the process on Windows instead of testing it, and a PID is reused.

Stopping is a request, not a kill. Terminating mid-draft can leave a half-written
reply in Outlook and a model call whose spend is recorded nowhere, which is close
to the duplicate-draft failure the lock already exists to prevent. The watcher
notices the request between messages and exits having finished what it was
doing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rotem_agent.config import PROJECT_ROOT
from rotem_agent.lock import AlreadyRunning, SingleInstance
from rotem_agent.state import STATE_DIR

STOP_FILE = STATE_DIR / "stop.request"
LOCK_FILE = STATE_DIR / "watch.lock"
STARTUP_LOG = PROJECT_ROOT / "logs" / "watcher-startup.log"

# Windows process creation flags, spelled out so the module imports on any
# platform. A detached watcher outlives the dashboard that started it, which is
# the point: closing the browser must not stop the agent.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class WatcherStatus:
    running: bool
    pid: int | None = None
    since: str | None = None

    @property
    def label(self) -> str:
        return "running" if self.running else "stopped"


def request_stop(path: Path | None = None) -> None:
    target = path or STOP_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(datetime.now(timezone.utc).isoformat(timespec="seconds"), encoding="utf-8")


def stop_requested(path: Path | None = None) -> bool:
    return (path or STOP_FILE).exists()


def stop_pending_seconds(path: Path | None = None, now: datetime | None = None) -> float | None:
    """How long a stop has gone unanswered, or None if none is outstanding.

    A watcher running older code, or wedged inside a COM call, will never see
    the request. Without this the dashboard would sit on 'stopping' forever with
    the button disabled and no way out.
    """
    target = path or STOP_FILE
    try:
        asked = datetime.fromisoformat(target.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if asked.tzinfo is None:
        asked = asked.replace(tzinfo=timezone.utc)
    return max(0.0, ((now or datetime.now(timezone.utc)) - asked).total_seconds())


def clear_stop(path: Path | None = None) -> None:
    try:
        (path or STOP_FILE).unlink()
    except FileNotFoundError:
        pass


def watcher_status(lock_path: Path | None = None) -> WatcherStatus:
    """Ask the lock whether a watcher holds it.

    Taking the lock and immediately dropping it is safe here. Only the watcher
    itself holds it for any length of time, and a probe that briefly succeeds
    cannot let a second watcher in: the real watcher takes it at startup and
    keeps it.
    """
    path = lock_path or LOCK_FILE
    guard = SingleInstance(path=path)
    try:
        guard.acquire()
    except AlreadyRunning:
        return WatcherStatus(running=True, pid=_recorded_pid(path), since=_held_since(path))
    guard.release()
    return WatcherStatus(running=False)


def start_watcher(
    *,
    interval_seconds: int = 60,
    python: str | None = None,
    cwd: Path | None = None,
    spawn=subprocess.Popen,
    lock_path: Path | None = None,
    stop_path: Path | None = None,
    wait_seconds: float = 20.0,
) -> WatcherStatus:
    """Launch a detached watcher, unless one is already running."""
    status = watcher_status(lock_path)
    if status.running:
        return status

    # A stop request left behind by a killed watcher would stop this one on its
    # first cycle, which reads as the button not working.
    clear_stop(stop_path)

    command = [
        python or sys.executable,
        "-u",
        "-m",
        "rotem_agent.cli",
        "outlook-watch",
        "--save",
        "--interval",
        str(interval_seconds),
    ]

    root = cwd or PROJECT_ROOT
    STARTUP_LOG.parent.mkdir(parents=True, exist_ok=True)
    # Anything failing before logging is configured, a bad interpreter or a
    # missing package, would otherwise disappear with the console.
    with STARTUP_LOG.open("a", encoding="utf-8") as sink:
        spawn(
            command,
            cwd=str(root),
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=_creation_flags(),
        )

    return _await_state(True, lock_path=lock_path, timeout=wait_seconds)


def stop_watcher(
    *,
    timeout: float = 90.0,
    lock_path: Path | None = None,
    stop_path: Path | None = None,
) -> WatcherStatus:
    """Ask the watcher to finish what it is doing and exit."""
    if not watcher_status(lock_path).running:
        clear_stop(stop_path)
        return WatcherStatus(running=False)

    request_stop(stop_path)
    status = _await_state(False, lock_path=lock_path, timeout=timeout)
    if not status.running:
        clear_stop(stop_path)
    return status


def force_stop(
    *,
    lock_path: Path | None = None,
    stop_path: Path | None = None,
    timeout: float = 15.0,
    kill=None,
) -> WatcherStatus:
    """Terminate the watcher outright. The last resort, not the button.

    Only reached when a polite stop has gone unanswered, which in practice means
    a process still running code from before the stop request existed, or one
    stuck inside a COM call. A draft may be lost and its spend may go unrecorded,
    which is why this is not what the switch does.
    """
    path = lock_path or LOCK_FILE
    status = watcher_status(path)
    if not status.running or not status.pid:
        clear_stop(stop_path)
        return WatcherStatus(running=False)

    terminate = kill or _terminate
    try:
        terminate(status.pid)
    except (OSError, PermissionError):
        return watcher_status(path)

    final = _await_state(False, lock_path=path, timeout=timeout)
    if not final.running:
        clear_stop(stop_path)
    return final


def _terminate(pid: int) -> None:
    # On Windows os.kill terminates whatever the signal, which is what is
    # wanted here and is also why it can never be used to test liveness.
    import signal

    os.kill(pid, signal.SIGTERM)


def _await_state(
    running: bool, *, lock_path: Path | None, timeout: float, poll: float = 0.25
) -> WatcherStatus:
    """Wait for the lock to reflect the change, so the UI never reports a lie."""
    deadline = time.monotonic() + timeout
    status = watcher_status(lock_path)
    while status.running != running and time.monotonic() < deadline:
        time.sleep(poll)
        status = watcher_status(lock_path)
    return status


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW


def _recorded_pid(path: Path) -> int | None:
    try:
        raw = path.read_bytes()[:64].decode("ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(raw) if raw.isdigit() else None


def _held_since(path: Path) -> str | None:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")
