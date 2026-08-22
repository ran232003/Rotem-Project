from __future__ import annotations

import pytest

from rotem_agent.config import ConfigError
from rotem_agent.outlook.com import MailboxConfig, OutlookError, OutlookMailbox, load_mailbox_config, rtl_html


def test_allowlist_is_case_and_whitespace_insensitive():
    config = MailboxConfig(mailbox="me@corp.com", allowed_senders=["  Client@Gmail.com "])
    assert config.allows("client@gmail.com")
    assert config.allows("CLIENT@GMAIL.COM")
    assert not config.allows("other@gmail.com")
    assert not config.allows(None)
    assert not config.allows("")


def test_scan_refuses_a_sender_outside_the_allowlist():
    """The mailbox holds thousands of unrelated messages, so this is the safety boundary."""
    box = OutlookMailbox(MailboxConfig(mailbox="me@corp.com", allowed_senders=["client@gmail.com"]))
    with pytest.raises(OutlookError, match="not in allowed_senders"):
        box.messages_from("colleague@corp.com")


def test_config_without_allowed_senders_is_rejected(tmp_path):
    path = tmp_path / "mailbox.yaml"
    path.write_text("mailbox: me@corp.com\nallowed_senders: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no allowed_senders"):
        load_mailbox_config(path)


def test_missing_config_names_the_example_file(tmp_path):
    with pytest.raises(ConfigError, match="mailbox.example.yaml"):
        load_mailbox_config(tmp_path / "absent.yaml")


def test_rtl_html_marks_direction_and_splits_paragraphs():
    html = rtl_html("שלום,\n\nשורה ראשונה\nשורה שנייה\n\nבברכה")
    assert 'dir="rtl"' in html
    assert html.count("<p ") == 3
    assert "<br>" in html


def test_rtl_html_escapes_markup():
    assert "<b>" not in rtl_html("שלום <b>מודגש</b>")
    assert "&lt;b&gt;" in rtl_html("שלום <b>מודגש</b>")
