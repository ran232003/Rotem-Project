"""Turning the agent on and off from outside the process that runs it.

The button has to tell the truth. A dashboard that says the agent is off while
it quietly drafts, or claims to have stopped it when it has not, is worse than
no button, because it invites the lawyer to act on a wrong belief.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

from rotem_agent.control import (
    clear_stop,
    force_stop,
    request_stop,
    start_watcher,
    stop_pending_seconds,
    stop_requested,
    stop_watcher,
    watcher_status,
)

_HOLDER = textwrap.dedent(
    """
    import time
    from rotem_agent.lock import SingleInstance
    # Bound to a name: collecting the guard closes its handle, and closing the
    # handle releases the lock, so a temporary would hold nothing.
    guard = SingleInstance(path=r"%s").acquire()
    print("held", flush=True)
    time.sleep(60)
    """
)


@pytest.fixture
def held_lock(tmp_path):
    """A lock held by another process, which is the only honest simulation.

    Locks are re-entrant within a process on Windows, so acquiring it here would
    let the probe succeed and report the watcher as stopped.
    """
    path = tmp_path / "watch.lock"
    child = subprocess.Popen(
        [sys.executable, "-c", _HOLDER % str(path).replace("\\", "\\\\")],
        stdout=subprocess.PIPE,
        text=True,
        cwd=os.getcwd(),
    )
    assert child.stdout.readline().strip() == "held"
    try:
        yield path
    finally:
        child.terminate()
        child.wait(timeout=30)


def test_no_lock_means_no_watcher(tmp_path):
    status = watcher_status(tmp_path / "watch.lock")
    assert not status.running
    assert status.label == "stopped"


def test_a_held_lock_means_a_watcher_is_running(held_lock):
    status = watcher_status(held_lock)
    assert status.running
    assert status.pid


def test_the_holding_process_is_named(held_lock):
    """So a watcher started from a terminal can still be found and stopped."""
    assert watcher_status(held_lock).pid > 0


def test_a_stop_request_is_visible_to_another_process(tmp_path):
    path = tmp_path / "stop.request"
    assert not stop_requested(path)
    request_stop(path)
    assert stop_requested(path)
    clear_stop(path)
    assert not stop_requested(path)


def test_clearing_a_stop_that_is_not_there_is_harmless(tmp_path):
    clear_stop(tmp_path / "stop.request")


def test_starting_when_already_running_does_not_spawn_a_second(held_lock, tmp_path):
    calls = []

    status = start_watcher(
        spawn=lambda *a, **k: calls.append(a),
        lock_path=held_lock,
        stop_path=tmp_path / "stop.request",
    )

    assert status.running
    assert calls == []


def test_starting_clears_a_stop_left_by_a_killed_watcher(tmp_path):
    """Otherwise the new watcher reads the stale request and exits at once."""
    stop_path = tmp_path / "stop.request"
    request_stop(stop_path)
    spawned = []

    start_watcher(
        spawn=lambda *a, **k: spawned.append(a),
        lock_path=tmp_path / "watch.lock",
        stop_path=stop_path,
        wait_seconds=0.1,
    )

    assert not stop_requested(stop_path)
    assert len(spawned) == 1


def test_the_spawned_command_runs_the_watcher_with_saving_on(tmp_path):
    spawned = []
    start_watcher(
        interval_seconds=45,
        spawn=lambda command, **k: spawned.append(command),
        lock_path=tmp_path / "watch.lock",
        stop_path=tmp_path / "stop.request",
        wait_seconds=0.1,
    )
    command = spawned[0]
    assert "outlook-watch" in command
    assert "--save" in command
    assert "45" in command


def test_stopping_something_that_is_not_running_leaves_no_request(tmp_path):
    """A stale request would stop the next watcher the moment it starts."""
    stop_path = tmp_path / "stop.request"
    status = stop_watcher(lock_path=tmp_path / "watch.lock", stop_path=stop_path)
    assert not status.running
    assert not stop_requested(stop_path)


def test_stopping_a_running_watcher_asks_rather_than_kills(held_lock, tmp_path):
    """The holder ignores the request, so this proves nothing was terminated."""
    stop_path = tmp_path / "stop.request"

    status = stop_watcher(timeout=1.0, lock_path=held_lock, stop_path=stop_path)

    assert stop_requested(stop_path)
    assert status.running


def test_nothing_is_pending_when_no_stop_was_asked_for(tmp_path):
    assert stop_pending_seconds(tmp_path / "stop.request") is None


def test_an_unanswered_stop_reports_how_long_it_has_waited(tmp_path):
    """The dashboard needs this to offer a way out of a stop that never lands."""
    stop_path = tmp_path / "stop.request"
    request_stop(stop_path)
    elapsed = stop_pending_seconds(
        stop_path, now=datetime.now(timezone.utc) + timedelta(seconds=120)
    )
    assert 119 <= elapsed <= 121


def test_a_damaged_stop_file_reports_nothing_pending(tmp_path):
    stop_path = tmp_path / "stop.request"
    stop_path.write_text("not a timestamp", encoding="utf-8")
    assert stop_pending_seconds(stop_path) is None


def test_forcing_a_watcher_that_is_not_running_is_a_no_op(tmp_path):
    killed = []
    status = force_stop(
        lock_path=tmp_path / "watch.lock",
        stop_path=tmp_path / "stop.request",
        kill=killed.append,
    )
    assert not status.running
    assert killed == []


def test_forcing_terminates_the_process_holding_the_lock(held_lock, tmp_path):
    killed = []
    force_stop(
        lock_path=held_lock,
        stop_path=tmp_path / "stop.request",
        timeout=0.5,
        kill=killed.append,
    )
    assert killed == [watcher_status(held_lock).pid]
