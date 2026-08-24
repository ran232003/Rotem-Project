"""The date before which mail is not the agent's business.

Turning the agent on should not produce a reply to every old thread in the
mailbox, so a fixed floor sits underneath the rolling backlog window. The
interesting cases are the timezone (the day is meant in local time), the
interaction between the two limits, and what a mistyped date does.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from rotem_agent.config import ConfigError
from rotem_agent.doctor import FAIL, OK, WARN, _start_date_check
from rotem_agent.outlook.com import load_mailbox_config, parse_start_date
from rotem_agent.state import DraftLedger
from rotem_agent.watch import backlog_cutoff, select_pending
from tests.test_watch import _message

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ parsing


def test_a_yaml_date_is_read_as_local_midnight():
    """YAML gives a date object; the day is meant where she is, not in UTC."""
    parsed = parse_start_date(date(2026, 8, 20))
    assert parsed == datetime(2026, 8, 20).astimezone(timezone.utc)
    assert parsed.astimezone().strftime("%Y-%m-%d %H:%M") == "2026-08-20 00:00"


@pytest.mark.parametrize(
    "written", ["2026-08-20", "20.08.2026", "20/08/2026", "2026/08/20", "  2026-08-20  "]
)
def test_the_ways_a_person_might_write_it(written):
    assert parse_start_date(written).astimezone().strftime("%d.%m.%Y") == "20.08.2026"


def test_a_time_given_explicitly_is_honoured():
    """Only a bare date is assumed to mean midnight."""
    parsed = parse_start_date(datetime(2026, 8, 20, 17, 45))
    assert parsed.astimezone().strftime("%d.%m.%Y %H:%M") == "20.08.2026 17:45"


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_no_date_means_no_floor(missing):
    assert parse_start_date(missing) is None


@pytest.mark.parametrize("bad", ["last tuesday", "20-08", "2026-13-40", "soon", "08.2026"])
def test_a_date_it_cannot_read_is_refused_by_name(bad):
    with pytest.raises(ConfigError, match="start_date"):
        parse_start_date(bad)


# ------------------------------------------------------------------ the cutoff


def test_the_floor_wins_when_it_is_later_than_the_window():
    """A seven day window would reach back to the 17th; the floor stops it."""
    floor = parse_start_date("2026-08-20")
    assert backlog_cutoff(7, NOW, floor=floor) == floor


def test_the_window_wins_when_it_is_later_than_the_floor():
    """Neither limit may be widened by the other."""
    floor = parse_start_date("2026-01-01")
    assert backlog_cutoff(7, NOW, floor=floor) == NOW - timedelta(days=7)


def test_a_floor_still_applies_when_the_window_is_switched_off():
    floor = parse_start_date("2026-08-20")
    assert backlog_cutoff(-1, NOW, floor=floor) == floor


def test_without_either_there_is_no_cutoff():
    assert backlog_cutoff(-1, NOW, floor=None) is None


def test_the_old_two_argument_behaviour_is_unchanged():
    assert backlog_cutoff(7, NOW) == NOW - timedelta(days=7)


# ------------------------------------------------------------------ selection


def _ledger(tmp_path):
    return DraftLedger(tmp_path / "ledger.json")


def test_mail_from_before_the_date_is_not_drafted(tmp_path):
    """The point of the whole feature."""
    cutoff = backlog_cutoff(30, NOW, floor=parse_start_date("2026-08-20"))
    before = _message("an old thread", minutes_ago=8 * 24 * 60)  # the 16th
    after = _message("a new enquiry", minutes_ago=60)

    chosen = select_pending([before, after], _ledger(tmp_path), cutoff=cutoff, max_items=10)

    assert [m.subject for m in chosen] == ["a new enquiry"]


def test_mail_on_the_day_itself_is_included(tmp_path):
    """Local midnight, so something at 09:00 on the 20th counts."""
    floor = parse_start_date("2026-08-20")
    on_the_day = _message("that morning")
    object.__setattr__(on_the_day, "received", floor + timedelta(hours=9))

    chosen = select_pending(
        [on_the_day], _ledger(tmp_path), cutoff=backlog_cutoff(30, NOW, floor=floor), max_items=10
    )
    assert len(chosen) == 1


def test_mail_minutes_before_the_day_is_excluded(tmp_path):
    floor = parse_start_date("2026-08-20")
    just_before = _message("the night before")
    object.__setattr__(just_before, "received", floor - timedelta(minutes=5))

    chosen = select_pending(
        [just_before], _ledger(tmp_path), cutoff=backlog_cutoff(30, NOW, floor=floor), max_items=10
    )
    assert chosen == []


# ------------------------------------------------------------------ config file


def _config(tmp_path, body):
    path = tmp_path / "mailbox.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_config_file_carries_the_date(tmp_path):
    path = _config(
        tmp_path,
        "mailbox: me@corp.com\nallowed_senders:\n  - a@x.com\nstart_date: 2026-08-20\n",
    )
    assert load_mailbox_config(path).start_date.astimezone().strftime("%d.%m.%Y") == "20.08.2026"


def test_a_config_without_the_date_still_loads(tmp_path):
    """It stays optional, so an existing install is not broken by the upgrade."""
    path = _config(tmp_path, "mailbox: me@corp.com\nallowed_senders:\n  - a@x.com\n")
    assert load_mailbox_config(path).start_date is None


def test_an_unreadable_date_stops_the_config_loading(tmp_path):
    path = _config(
        tmp_path,
        "mailbox: me@corp.com\nallowed_senders:\n  - a@x.com\nstart_date: whenever\n",
    )
    with pytest.raises(ConfigError, match="start_date"):
        load_mailbox_config(path)


# ------------------------------------------------------------------ doctor


def test_doctor_reports_a_configured_date(tmp_path):
    check = _start_date_check("2026-08-20", tmp_path / "mailbox.yaml")
    assert check.status == OK
    assert "20.08.2026" in check.detail


def test_doctor_warns_when_no_date_is_set(tmp_path):
    assert _start_date_check(None, tmp_path / "mailbox.yaml").status == WARN


def test_doctor_fails_a_date_it_cannot_read(tmp_path):
    assert _start_date_check("nonsense", tmp_path / "mailbox.yaml").status == FAIL


def test_doctor_fails_a_date_in_the_future(tmp_path):
    """Nothing would ever be drafted, which is worth catching at setup."""
    ahead = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    check = _start_date_check(ahead, tmp_path / "mailbox.yaml")
    assert check.status == FAIL
    assert "future" in check.detail
