"""The figures the lawyer reads off the dashboard.

Two of these matter more than the rest. Cost must cover every metered call, not
only the ones that produced a reply, or the per-email figure flatters the agent.
And a draft costs more than one model call, so a cost shown per message has to
be a sum.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rotem_agent.outcomes import Outcomes
from rotem_agent.pricing import ModelPrice, PriceList
from rotem_agent.stats import build
from rotem_agent.usage import UsageRecord

NOW = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)
PRICES = PriceList(models={"m": ModelPrice(input_per_million=1.0, output_per_million=1.0)})


def _ago(hours=0, days=0):
    return (NOW - timedelta(hours=hours, days=days)).isoformat(timespec="seconds")


def _entry(key="k1", hours=1, days=0, conversation="conv-1", ok=True, problems=None):
    return {
        "key": key,
        "conversation_id": conversation,
        "sender": "client@example.com",
        "subject": "subject",
        "drafted_at": _ago(hours=hours, days=days),
        "ok": ok,
        "problems": problems or [],
    }


def _record(key="k1", hours=1, days=0, model="m", inp=1_000_000, out=0):
    return UsageRecord(
        at=_ago(hours=hours, days=days), command="outlook-watch", model=model,
        input_tokens=inp, output_tokens=out, key=key,
    )


def _build(entries=None, records=None, outcomes=None, prices=PRICES, **kwargs):
    return build(
        entries=entries or [],
        records=records or [],
        prices=prices,
        outcomes=outcomes or Outcomes(),
        now=NOW,
        **kwargs,
    )


def test_today_counts_only_what_was_drafted_today():
    result = _build(entries=[_entry(key="a", hours=1), _entry(key="b", hours=40)])
    assert result["windows"]["today"]["answered"] == 1
    assert result["windows"]["week"]["answered"] == 2


def test_a_draft_outside_every_window_is_not_counted():
    result = _build(entries=[_entry(hours=24 * 45)])
    assert result["windows"]["month"]["answered"] == 0


def test_cost_covers_calls_that_never_produced_a_reply():
    """Transcription and audits are metered too and belong in the total."""
    records = [_record(key="k1"), _record(key="", inp=2_000_000)]
    result = _build(entries=[_entry()], records=records)
    assert result["windows"]["today"]["cost_usd"] == 3.0


def test_the_cost_shown_against_a_message_sums_its_calls():
    """Extracting the asks and writing the reply are two calls, one draft."""
    records = [_record(key="k1", inp=1_000_000), _record(key="k1", inp=500_000)]
    result = _build(entries=[_entry(key="k1")], records=records)
    assert result["recent"][0]["cost_usd"] == 1.5


def test_a_model_with_no_price_is_counted_apart_rather_than_as_free():
    result = _build(records=[_record(model="unknown")])
    assert result["windows"]["today"]["unpriced"] == 1
    assert result["windows"]["today"]["cost_usd"] == 0.0


def test_sent_is_unknown_until_sent_items_has_been_read():
    result = _build(entries=[_entry()])
    assert result["windows"]["today"]["sent"] is None
    assert result["recent"][0]["sent"] is None
    assert result["outcomes_known"] is False


def test_sent_is_counted_once_sent_items_has_been_read():
    outcomes = Outcomes(refreshed_at=_ago(), conversations={"conv-1": _ago(hours=0)})
    result = _build(entries=[_entry(conversation="conv-1")], outcomes=outcomes)
    assert result["windows"]["today"]["sent"] == 1
    assert result["recent"][0]["sent"] is True


def test_a_draft_she_ignored_is_reported_as_not_sent():
    outcomes = Outcomes(refreshed_at=_ago(), conversations={})
    result = _build(entries=[_entry(conversation="conv-9")], outcomes=outcomes)
    assert result["windows"]["today"]["sent"] == 0
    assert result["recent"][0]["sent"] is False


def test_recent_drafts_are_newest_first():
    entries = [_entry(key="old", hours=5), _entry(key="new", hours=1)]
    result = _build(entries=entries)
    assert [r["at"] for r in result["recent"]] == [_ago(hours=1), _ago(hours=5)]


def test_a_flagged_draft_carries_its_problems():
    result = _build(entries=[_entry(ok=False, problems=["unanswered question"])])
    assert result["recent"][0]["ok"] is False
    assert result["recent"][0]["problems"] == ["unanswered question"]


# --------------------------------------------------------------- the all-time total


def test_the_all_time_total_includes_spend_older_than_every_window():
    """The point of the figure is that nothing falls out of it."""
    records = [_record(hours=1), _record(days=400)]
    result = _build(records=records)

    assert result["windows"]["month"]["cost_usd"] == 1.0
    assert result["windows"]["all"]["cost_usd"] == 2.0


def test_the_all_time_total_counts_old_drafts_too():
    result = _build(entries=[_entry(key="a", hours=1), _entry(key="b", days=400)])
    assert result["windows"]["all"]["answered"] == 2


def test_a_timestamp_before_1970_does_not_take_the_page_down():
    """Windows refuses to localise one, which used to raise OSError out of the
    status endpoint and blank the whole dashboard rather than one row."""
    old = _entry(key="ancient")
    old["drafted_at"] = "1969-07-20T20:17:00+00:00"
    result = _build(entries=[old])

    assert result["windows"]["all"]["answered"] == 1
    assert result["windows"]["today"]["answered"] == 0
    assert result["recent"] == []


def test_an_unparseable_timestamp_is_left_out_rather_than_guessed():
    broken = _entry(key="broken")
    broken["drafted_at"] = "sometime last week"
    result = _build(entries=[broken])

    assert result["windows"]["all"]["answered"] == 0
    assert result["recent"] == []


# ------------------------------------------------------------------- the table


def test_the_table_covers_the_same_seven_days_as_the_week_card():
    """Two lists of 'recent drafts' disagreeing by a row costs an afternoon."""
    entries = [_entry(key="a", hours=1), _entry(key="b", days=3), _entry(key="c", days=20)]
    result = _build(entries=entries)

    assert len(result["recent"]) == result["windows"]["week"]["answered"] == 2
    assert result["recent_days"] == 7


def test_everything_inside_the_window_is_returned_not_just_a_screenful():
    """The page pages through these, so cutting the list here would hide rows
    behind a control that claimed to reach them."""
    entries = [_entry(key=f"k{n}", hours=n + 1) for n in range(34)]
    result = _build(entries=entries)

    assert len(result["recent"]) == 34
    assert result["recent_truncated"] is False


def test_an_implausible_pile_of_drafts_is_capped_and_says_so():
    entries = [_entry(key=f"k{n}", hours=n % 24 + 1) for n in range(30)]
    result = _build(entries=entries, recent_limit=10)

    assert len(result["recent"]) == 10
    assert result["recent_truncated"] is True


def test_the_capped_list_keeps_the_newest_rather_than_whatever_came_first():
    entries = [_entry(key="old", days=2), _entry(key="new", hours=1)]
    result = _build(entries=entries, recent_limit=1)

    assert [r["at"] for r in result["recent"]] == [_ago(hours=1)]


def test_the_window_can_be_widened():
    result = _build(entries=[_entry(key="a", days=20)], recent_days=30)
    assert len(result["recent"]) == 1
    assert result["recent_days"] == 30


def test_shekels_appear_only_when_a_rate_is_configured():
    without = _build(records=[_record()])
    assert without["windows"]["today"]["cost_ils"] is None

    priced = PriceList(models=PRICES.models, usd_to_ils=3.5)
    with_rate = _build(records=[_record()], prices=priced)
    assert with_rate["windows"]["today"]["cost_ils"] == 3.5
