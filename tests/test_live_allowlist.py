"""Re-reading config/mailbox.yaml while the agent runs.

The list is the agent's only boundary, so the failure modes matter more than the
happy path: a file saved half-written must not empty it, and must not crash the
watcher either.
"""

from __future__ import annotations

import pytest

from rotem_agent.cli import _live_senders
from rotem_agent.outlook.com import MailboxConfig


@pytest.fixture
def stub(monkeypatch):
    """Stands in for load_mailbox_config, so no file or Outlook is involved."""
    state = {"senders": ["a@x.com"], "error": None}

    def fake():
        if state["error"]:
            raise state["error"]
        return MailboxConfig(mailbox="me@corp.com", allowed_senders=list(state["senders"]))

    monkeypatch.setattr("rotem_agent.cli.load_mailbox_config", fake)
    return state


def test_an_added_address_appears_on_the_next_call(stub):
    provide = _live_senders(["a@x.com"], log=lambda m: None)
    assert provide() == ["a@x.com"]

    stub["senders"] = ["a@x.com", "b@x.com"]
    assert provide() == ["a@x.com", "b@x.com"]


def test_a_removed_address_disappears(stub):
    stub["senders"] = ["a@x.com", "b@x.com"]
    provide = _live_senders(["a@x.com", "b@x.com"], log=lambda m: None)
    stub["senders"] = ["a@x.com"]
    assert provide() == ["a@x.com"]


def test_a_change_is_announced_once_not_every_pass(stub):
    said = []
    provide = _live_senders(["a@x.com"], log=said.append)

    provide()
    assert said == []

    stub["senders"] = ["a@x.com", "b@x.com"]
    provide()
    provide()
    provide()
    assert len([m for m in said if "allowlist changed" in m]) == 1


def test_reordering_is_not_treated_as_a_change(stub):
    said = []
    stub["senders"] = ["a@x.com", "b@x.com"]
    provide = _live_senders(["b@x.com", "A@x.com"], log=said.append)
    provide()
    assert said == []


def test_a_half_saved_file_keeps_the_previous_list(stub):
    """Better a stale boundary for one pass than no boundary, or a crash."""
    said = []
    provide = _live_senders(["a@x.com"], log=said.append)
    stub["error"] = ValueError("while scanning a simple key")

    assert provide() == ["a@x.com"]
    assert any("keeping the current one" in m for m in said)


def test_it_recovers_once_the_file_is_valid_again(stub):
    provide = _live_senders(["a@x.com"], log=lambda m: None)
    stub["error"] = ValueError("bad yaml")
    assert provide() == ["a@x.com"]

    stub["error"] = None
    stub["senders"] = ["a@x.com", "b@x.com"]
    assert provide() == ["a@x.com", "b@x.com"]


def test_an_emptied_file_does_not_silently_widen_or_narrow(stub):
    """load_mailbox_config raises on an empty list, so this is the error path."""
    provide = _live_senders(["a@x.com"], log=lambda m: None)
    stub["error"] = RuntimeError("no allowed_senders; refusing to scan the whole mailbox")
    assert provide() == ["a@x.com"]
