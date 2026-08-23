"""Telling a draft that was used from one that was discarded.

The distinction only means something if 'we have not looked' is kept separate
from 'she did not send it'. Collapsing the two would report every draft as
discarded on a machine that has never scanned Sent Items.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rotem_agent.outcomes import Outcomes, load, refresh, save

DRAFTED = "2026-08-22T10:00:00+00:00"


def _outcomes(**conversations):
    return Outcomes(
        refreshed_at="2026-08-22T12:00:00+00:00",
        conversations=dict(conversations),
    )


def test_unrefreshed_is_unknown_not_unsent():
    assert Outcomes().was_sent("conv-1", DRAFTED) is None


def test_a_conversation_with_no_sent_reply_counts_as_not_sent():
    assert _outcomes(other="2026-08-22T11:00:00+00:00").was_sent("conv-1", DRAFTED) is False


def test_a_reply_sent_after_the_draft_counts_as_sent():
    assert _outcomes(**{"conv-1": "2026-08-22T11:00:00+00:00"}).was_sent("conv-1", DRAFTED) is True


def test_a_reply_sent_before_the_draft_does_not_count():
    """That is the firm's earlier message in the thread, not use of this draft."""
    assert _outcomes(**{"conv-1": "2026-08-22T09:00:00+00:00"}).was_sent("conv-1", DRAFTED) is False


def test_a_message_with_no_conversation_id_is_unknown():
    assert _outcomes(**{"conv-1": DRAFTED}).was_sent(None, DRAFTED) is None


def test_a_missing_store_reads_as_unknown(tmp_path):
    assert load(tmp_path / "outcomes.json").known is False


def test_a_corrupt_store_reads_as_unknown_rather_than_raising(tmp_path):
    path = tmp_path / "outcomes.json"
    path.write_text("{not json", encoding="utf-8")
    assert load(path).known is False


def test_saving_and_loading_round_trips(tmp_path):
    path = tmp_path / "outcomes.json"
    save(_outcomes(**{"conv-1": DRAFTED}), path)
    restored = load(path)
    assert restored.known
    assert restored.conversations == {"conv-1": DRAFTED}


class _Box:
    def __init__(self, sent):
        self.sent = sent
        self.since = None

    def sent_conversations(self, since):
        self.since = since
        return self.sent


def test_refresh_records_when_each_conversation_was_last_answered():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    box = _Box({"conv-1": datetime(2026, 8, 22, 11, 0, tzinfo=timezone.utc)})

    result = refresh(box, days=30, now=now)

    assert result.conversations["conv-1"].startswith("2026-08-22T11:00")
    assert result.refreshed_at.startswith("2026-08-22T12:00")


def test_refresh_only_looks_back_the_window(tmp_path):
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    box = _Box({})
    refresh(box, days=7, now=now)
    assert box.since == now - timedelta(days=7)


def test_a_naive_timestamp_from_outlook_is_treated_as_utc():
    """COM hands back both kinds depending on version, and neither may crash."""
    box = _Box({"conv-1": datetime(2026, 8, 22, 11, 0)})
    result = refresh(box, now=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc))
    assert result.conversations["conv-1"].startswith("2026-08-22T11:00")
