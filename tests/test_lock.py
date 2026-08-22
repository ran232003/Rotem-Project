"""Only one watcher may run, because two draft every message twice."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from rotem_agent.lock import AlreadyRunning, SingleInstance


def test_a_second_claim_in_another_process_is_refused(tmp_path):
    """Held in-process locks are re-entrant on Windows, so this needs a child."""
    lock_path = tmp_path / "watch.lock"
    guard = SingleInstance(path=lock_path).acquire()
    try:
        result = subprocess.run(
            [sys.executable, "-c", _CHILD % str(lock_path).replace("\\", "\\\\")],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )
        assert result.stdout.strip() == "refused", result.stderr
    finally:
        guard.release()


def test_the_lock_is_free_again_after_release(tmp_path):
    lock_path = tmp_path / "watch.lock"
    SingleInstance(path=lock_path).acquire().release()
    second = SingleInstance(path=lock_path)
    second.acquire()
    second.release()


def test_the_holding_pid_is_recorded(tmp_path):
    lock_path = tmp_path / "watch.lock"
    guard = SingleInstance(path=lock_path).acquire()
    try:
        assert lock_path.read_bytes().startswith(str(os.getpid()).encode())
    finally:
        guard.release()


def test_release_without_acquire_is_harmless(tmp_path):
    SingleInstance(path=tmp_path / "watch.lock").release()


def test_the_context_manager_releases(tmp_path):
    lock_path = tmp_path / "watch.lock"
    with SingleInstance(path=lock_path):
        pass
    with SingleInstance(path=lock_path):
        pass


_CHILD = textwrap.dedent(
    """
    from rotem_agent.lock import AlreadyRunning, SingleInstance
    try:
        SingleInstance(path=r"%s").acquire()
        print("acquired")
    except AlreadyRunning:
        print("refused")
    """
)
