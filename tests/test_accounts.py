"""Asking Outlook which mailboxes it has, out of process.

The interesting behaviour is the caching, because it decides whether an edit is
checked against a real answer or against a leftover one. In particular a failed
lookup must not be remembered: refusing a change for ten minutes because Outlook
happened to be closed once would look like the field is broken.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from rotem_agent.accounts import Accounts


class _Runs:
    """Stands in for the subprocess, counting how often it is asked."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def __call__(self, argv, **kwargs):
        self.calls += 1
        stdout, code = self.results[min(self.calls - 1, len(self.results) - 1)]
        return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr="")


@pytest.fixture
def run(monkeypatch):
    def install(*results):
        fake = _Runs(*results)
        monkeypatch.setattr(subprocess, "run", fake)
        return fake

    return install


def test_the_addresses_come_from_the_command(run):
    run(("her@firm.co.il\nother@firm.co.il\n", 0))
    assert Accounts().known() == ["her@firm.co.il", "other@firm.co.il"]


def test_blank_lines_and_noise_are_ignored(run):
    """logs.setup and Outlook itself are both free to print."""
    run(("\nstarting up\nher@firm.co.il\n\n", 0))
    assert Accounts().known() == ["her@firm.co.il"]


def test_the_answer_is_only_fetched_once(run):
    fake = run(("her@firm.co.il\n", 0))
    accounts = Accounts()
    accounts.known()
    accounts.known()
    assert fake.calls == 1


def test_a_stale_answer_is_fetched_again(run):
    fake = run(("her@firm.co.il\n", 0))
    accounts = Accounts(ttl=0.0)
    accounts.known()
    accounts.known()
    assert fake.calls == 2


def test_a_failure_is_not_remembered(run):
    """Outlook being closed is temporary; caching the emptiness is not."""
    fake = run(("", 1), ("her@firm.co.il\n", 0))
    accounts = Accounts()

    assert accounts.known() == []
    assert accounts.known() == ["her@firm.co.il"]
    assert fake.calls == 2


def test_a_crash_in_the_lookup_is_an_empty_answer_not_an_exception(monkeypatch):
    """This is called from a request handler; it must not take the page down."""

    def boom(*args, **kwargs):
        raise OSError("no python here")

    monkeypatch.setattr(subprocess, "run", boom)
    assert Accounts().known() == []


def test_a_timeout_is_an_empty_answer(monkeypatch):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("cli", 90)

    monkeypatch.setattr(subprocess, "run", slow)
    assert Accounts().known() == []


def test_nothing_is_known_before_anyone_asks(run):
    run(("her@firm.co.il\n", 0))
    assert Accounts().cached() == []


def test_priming_fills_the_cache_without_the_caller_waiting(run):
    fake = run(("her@firm.co.il\n", 0))
    accounts = Accounts()
    accounts.prime()

    deadline = time.monotonic() + 5
    while not accounts.cached() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert accounts.cached() == ["her@firm.co.il"]
    assert fake.calls == 1


def test_priming_a_fresh_cache_asks_nothing(run):
    fake = run(("her@firm.co.il\n", 0))
    accounts = Accounts()
    accounts.known()
    accounts.prime()
    assert fake.calls == 1
