from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rotem_agent.outlook.com import FoundMessage
from rotem_agent.state import DraftLedger, LedgerEntry, message_key
from rotem_agent.watch import (
    WatchOptions,
    as_datetime,
    backlog_cutoff,
    key_for,
    run_cycle,
    select_pending,
    watch,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _message(subject: str, *, minutes_ago: int = 0, message_id: str | None = None,
             conversation_id: str = "conv-1") -> FoundMessage:
    return FoundMessage(
        item=object(),
        folder_path="\\\\me@corp.com\\Inbox",
        received=NOW - timedelta(minutes=minutes_ago),
        subject=subject,
        sender="client@gmail.com",
        conversation_id=conversation_id,
        message_id=message_id,
    )


def _ledger(tmp_path) -> DraftLedger:
    return DraftLedger(tmp_path / "ledger.json")


def _entry(key: str) -> LedgerEntry:
    return LedgerEntry(
        key=key,
        message_id=key,
        conversation_id="conv-1",
        sender="client@gmail.com",
        subject="subject",
        received=NOW.isoformat(),
        drafted_at=NOW.isoformat(),
        model="test-model",
        source_policy="advisory",
        draft_entry_id="ENTRY",
        ok=True,
    )


def test_ledger_round_trips_through_the_file(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record(_entry("<a@example.com>"))
    assert "<a@example.com>" in _ledger(tmp_path)


def test_ledger_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json", encoding="utf-8")
    ledger = DraftLedger(path)
    assert len(ledger) == 0
    assert path.with_suffix(".corrupt").exists()


def test_forget_makes_a_message_eligible_again(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record(_entry("<a@example.com>"))
    assert ledger.forget("<a@example.com>") is True
    assert ledger.forget("<a@example.com>") is False
    assert len(ledger) == 0


def test_message_key_prefers_the_internet_message_id():
    assert message_key("<a@example.com>", "conv", "2026") == "<a@example.com>"


def test_message_key_falls_back_per_message_not_per_thread():
    """Two messages in one thread must not collapse to a single key."""
    first = message_key(None, "conv-1", "2026-08-22T10:00:00")
    second = message_key(None, "conv-1", "2026-08-22T11:00:00")
    assert first != second


def test_already_drafted_messages_are_skipped(tmp_path):
    ledger = _ledger(tmp_path)
    answered = _message("answered", message_id="<a@example.com>")
    fresh = _message("fresh", message_id="<b@example.com>")
    ledger.record(_entry(key_for(answered)))

    pending = select_pending([answered, fresh], ledger, cutoff=None, max_items=10)
    assert [m.subject for m in pending] == ["fresh"]


def test_force_redrafts_an_answered_message(tmp_path):
    ledger = _ledger(tmp_path)
    answered = _message("answered", message_id="<a@example.com>")
    ledger.record(_entry(key_for(answered)))

    pending = select_pending([answered], ledger, cutoff=None, max_items=10, force=True)
    assert len(pending) == 1


def test_backlog_cutoff_excludes_old_mail(tmp_path):
    ledger = _ledger(tmp_path)
    old = _message("old", minutes_ago=60 * 24 * 30, message_id="<old@example.com>")
    recent = _message("recent", minutes_ago=5, message_id="<new@example.com>")

    pending = select_pending(
        [old, recent], ledger, cutoff=backlog_cutoff(7, NOW), max_items=10
    )
    assert [m.subject for m in pending] == ["recent"]


def test_negative_backlog_days_means_no_cutoff():
    assert backlog_cutoff(-1) is None


def test_pending_is_oldest_first_and_capped(tmp_path):
    ledger = _ledger(tmp_path)
    messages = [
        _message("third", minutes_ago=1, message_id="<3@x.com>"),
        _message("first", minutes_ago=30, message_id="<1@x.com>"),
        _message("second", minutes_ago=10, message_id="<2@x.com>"),
    ]
    pending = select_pending(messages, ledger, cutoff=None, max_items=2)
    assert [m.subject for m in pending] == ["first", "second"]


def test_as_datetime_assumes_utc_for_naive_values():
    assert as_datetime(datetime(2026, 8, 22, 12, 0)).tzinfo is timezone.utc
    assert as_datetime(None) is None
    assert as_datetime("not a date") is None


class _QuietBox:
    """A mailbox with nothing in it, so a cycle is a no-op."""

    def __init__(self):
        self.cycles = 0

    def messages_from(self, sender, limit=50):
        self.cycles += 1
        return []


def test_a_stop_asked_for_up_front_means_no_cycle_runs(tmp_path):
    box = _QuietBox()
    watch(box, _ledger(tmp_path), ["client@gmail.com"], lambda **k: None,
          WatchOptions(), log=lambda m: None, sleep=lambda s: None,
          should_stop=lambda: True)
    assert box.cycles == 0


def test_a_stop_during_the_wait_ends_the_loop(tmp_path):
    """The current message finishes; the next one is never started."""
    box = _QuietBox()
    stopped = {"yes": False}

    def sleep(_seconds):
        stopped["yes"] = True

    watch(box, _ledger(tmp_path), ["client@gmail.com"], lambda **k: None,
          WatchOptions(interval_seconds=5), log=lambda m: None, sleep=sleep,
          should_stop=lambda: stopped["yes"])

    assert box.cycles == 1


def test_the_wait_is_sliced_so_a_stop_is_not_a_minute_late(tmp_path):
    """A single sixty second sleep would make the off button look broken."""
    slices = []
    box = _QuietBox()

    watch(box, _ledger(tmp_path), ["client@gmail.com"], lambda **k: None,
          WatchOptions(interval_seconds=5), log=lambda m: None,
          sleep=slices.append, should_stop=lambda: False, max_cycles=1)

    assert slices == []  # max_cycles exits before waiting

    watch(box, _ledger(tmp_path), ["client@gmail.com"], lambda **k: None,
          WatchOptions(interval_seconds=5), log=lambda m: None,
          sleep=slices.append, should_stop=lambda: False, max_cycles=2)

    assert max(slices) <= 1.0
    assert sum(slices) == 5.0


def test_without_a_stop_it_runs_every_requested_cycle(tmp_path):
    box = _QuietBox()
    watch(box, _ledger(tmp_path), ["client@gmail.com"], lambda **k: None,
          WatchOptions(interval_seconds=1), log=lambda m: None, sleep=lambda s: None,
          should_stop=lambda: False, max_cycles=3)
    assert box.cycles == 3


class _NamingBox:
    """Records which addresses each cycle asked about."""

    def __init__(self):
        self.asked = []

    def messages_from(self, sender, limit=50):
        self.asked.append(sender)
        return []


def test_a_fixed_list_is_still_accepted(tmp_path):
    box = _NamingBox()
    run_cycle(box, _ledger(tmp_path), ["a@x.com", "b@x.com"], lambda **k: None,
              WatchOptions(), log=lambda m: None)
    assert box.asked == ["a@x.com", "b@x.com"]


def test_an_address_added_mid_run_is_picked_up_without_a_restart(tmp_path):
    """The whole point: she should not have to stop the agent to add a client."""
    box = _NamingBox()
    listed = ["a@x.com"]

    watch(box, _ledger(tmp_path), lambda: listed, lambda **k: None,
          WatchOptions(interval_seconds=1), log=lambda m: None,
          sleep=lambda s: listed.append("b@x.com") if len(listed) == 1 else None,
          should_stop=lambda: False, max_cycles=2)

    assert box.asked == ["a@x.com", "a@x.com", "b@x.com"]


def test_a_removed_address_stops_being_read(tmp_path):
    box = _NamingBox()
    listed = ["a@x.com", "b@x.com"]

    watch(box, _ledger(tmp_path), lambda: listed, lambda **k: None,
          WatchOptions(interval_seconds=1), log=lambda m: None,
          sleep=lambda s: listed.remove("b@x.com") if "b@x.com" in listed else None,
          should_stop=lambda: False, max_cycles=2)

    assert box.asked == ["a@x.com", "b@x.com", "a@x.com"]
