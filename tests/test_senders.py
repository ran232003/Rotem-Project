"""Editing the allowlist from the dashboard.

This file is the agent's only boundary on whose mail it reads, so the tests
weigh towards the ways an edit can go wrong: comments lost, a following key
swallowed, the list emptied, a half-written file left behind.
"""

from __future__ import annotations

import pytest
import yaml

from rotem_agent import senders


def _file(tmp_path, text):
    path = tmp_path / "mailbox.yaml"
    path.write_text(text, encoding="utf-8")
    return path


BASIC = "mailbox: me@corp.com\nallowed_senders:\n  - a@x.com\n"

COMMENTED = (
    "# the boundary, do not widen without asking\n"
    "#\n"
    "mailbox: me@corp.com\n"
    "allowed_senders:\n"
    "  - a@x.com\n"
    "\n"
    "# trailing note\n"
)


def test_reading_the_listed_addresses(tmp_path):
    assert senders.read(_file(tmp_path, BASIC)) == ["a@x.com"]


def test_reading_an_inline_list(tmp_path):
    path = _file(tmp_path, "allowed_senders: [a@x.com, b@y.com]\n")
    assert senders.read(path) == ["a@x.com", "b@y.com"]


def test_a_missing_key_reads_as_empty(tmp_path):
    assert senders.read(_file(tmp_path, "mailbox: me@corp.com\n")) == []


def test_a_missing_file_is_reported_in_words(tmp_path):
    with pytest.raises(senders.SenderError, match="חסר"):
        senders.read(tmp_path / "nope.yaml")


def test_adding_appends_and_still_parses(tmp_path):
    path = _file(tmp_path, BASIC)
    change = senders.add("b@y.com", path)

    assert change.senders == ["a@x.com", "b@y.com"]
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "mailbox": "me@corp.com",
        "allowed_senders": ["a@x.com", "b@y.com"],
    }


def test_comments_and_the_mailbox_line_survive_an_edit(tmp_path):
    """A dashboard that ate the explanatory comments would make the file
    harder to audit than it was before."""
    path = _file(tmp_path, COMMENTED)
    senders.add("b@y.com", path)
    after = path.read_text(encoding="utf-8")

    assert "# the boundary, do not widen without asking" in after
    assert "# trailing note" in after
    assert "mailbox: me@corp.com" in after


def test_a_following_key_is_not_swallowed(tmp_path):
    path = _file(tmp_path, "allowed_senders:\n  - a@x.com\nmailbox: me@corp.com\n")
    senders.add("b@y.com", path)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["mailbox"] == "me@corp.com"


def test_an_inline_empty_list_becomes_a_valid_block(tmp_path):
    path = _file(tmp_path, "mailbox: me@corp.com\nallowed_senders: []\n")
    senders.add("b@y.com", path)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["allowed_senders"] == ["b@y.com"]


def test_the_existing_indent_is_kept(tmp_path):
    path = _file(tmp_path, "allowed_senders:\n    - a@x.com\n")
    senders.add("b@y.com", path)
    assert "    - b@y.com" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "Rotem Fargon", "rotem@", "@example.com", "rotem@example", "a b@x.com",
     "one@x.com, two@x.com", "<script>@x.com"],
)
def test_a_bad_address_is_refused(tmp_path, bad):
    path = _file(tmp_path, BASIC)
    with pytest.raises(senders.SenderError):
        senders.add(bad, path)
    assert senders.read(path) == ["a@x.com"]


def test_angle_brackets_from_a_paste_are_tolerated(tmp_path):
    path = _file(tmp_path, BASIC)
    assert senders.add("<b@y.com>", path).address == "b@y.com"


def test_a_duplicate_is_refused_regardless_of_case(tmp_path):
    path = _file(tmp_path, BASIC)
    with pytest.raises(senders.SenderError, match="כבר"):
        senders.add("A@X.COM", path)


def test_removing_takes_it_out(tmp_path):
    path = _file(tmp_path, "allowed_senders:\n  - a@x.com\n  - b@y.com\n")
    assert senders.remove("b@y.com", path).senders == ["a@x.com"]
    assert senders.read(path) == ["a@x.com"]


def test_removing_ignores_case(tmp_path):
    path = _file(tmp_path, "allowed_senders:\n  - a@x.com\n  - b@y.com\n")
    senders.remove("B@Y.com", path)
    assert senders.read(path) == ["a@x.com"]


def test_removing_something_absent_says_so(tmp_path):
    path = _file(tmp_path, BASIC)
    with pytest.raises(senders.SenderError, match="אינה ברשימה"):
        senders.remove("nobody@x.com", path)


def test_the_last_address_cannot_be_removed(tmp_path):
    """An empty list makes load_mailbox_config raise, and a running watcher
    then keeps its previous list: the page would show nobody while the agent
    carried on drafting."""
    path = _file(tmp_path, BASIC)
    with pytest.raises(senders.SenderError, match="לכבות"):
        senders.remove("a@x.com", path)
    assert senders.read(path) == ["a@x.com"]


def test_the_written_file_is_what_load_mailbox_config_accepts(tmp_path):
    """The two sides of the boundary must agree on the format."""
    from rotem_agent.outlook.com import load_mailbox_config

    path = _file(tmp_path, COMMENTED)
    senders.add("b@y.com", path)

    config = load_mailbox_config(path)
    assert config.mailbox == "me@corp.com"
    assert config.allows("b@y.com")
    assert not config.allows("stranger@x.com")


def test_windows_line_endings_are_preserved(tmp_path):
    """She edits this file in Notepad; an edit should not also rewrite every line."""
    path = tmp_path / "mailbox.yaml"
    path.write_bytes(b"mailbox: me@corp.com\r\nallowed_senders:\r\n  - a@x.com\r\n")

    senders.add("b@y.com", path)

    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert senders.read(path) == ["a@x.com", "b@y.com"]


def test_unix_line_endings_stay_unix(tmp_path):
    path = tmp_path / "mailbox.yaml"
    path.write_bytes(b"allowed_senders:\n  - a@x.com\n")

    senders.add("b@y.com", path)

    assert b"\r\n" not in path.read_bytes()


def test_a_failed_write_leaves_no_temporary_file_behind(tmp_path, monkeypatch):
    path = _file(tmp_path, BASIC)
    monkeypatch.setattr(senders.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("nope")))

    with pytest.raises(OSError):
        senders.add("b@y.com", path)

    assert list(tmp_path.iterdir()) == [path]
    assert senders.read(path) == ["a@x.com"]
