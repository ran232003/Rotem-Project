"""Metering, pricing and the spend log.

The cost of a draft may end up on a client bill, so the arithmetic and the
handling of an unknown price are worth pinning down.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from rotem_agent.llm.base import LlmResponse, LlmUsage
from rotem_agent.llm.metering import MeteredClient
from rotem_agent.pricing import (
    ModelPrice,
    PriceList,
    format_money,
    format_usd,
    load_prices,
)
from rotem_agent.usage import UsageLog, UsageRecord, cutoff, from_report, group, totals

PRICES = PriceList(models={"test-model": ModelPrice(input_per_million=1.0, output_per_million=10.0)})


class _FakeClient:
    """Reports a different usage on each call, so a sum cannot pass by accident."""

    def __init__(self, usages: list[LlmUsage | None]) -> None:
        self._usages = list(usages)
        self.calls = 0

    @property
    def model(self) -> str:
        return "test-model"

    def complete_json(self, *, system, user, schema, temperature=0.2) -> LlmResponse:
        usage = self._usages[min(self.calls, len(self._usages) - 1)]
        self.calls += 1
        return LlmResponse(data={"ok": True}, model="test-model", usage=usage)


def _call(client) -> None:
    client.complete_json(system="s", user="u", schema={}, temperature=0.0)


def test_the_meter_sums_every_call_not_just_the_last():
    """A draft costs two calls; reporting only the reply understated the bill."""
    inner = _FakeClient([LlmUsage(100, 20), LlmUsage(4000, 1500)])
    meter = MeteredClient(inner)

    _call(meter.labelled("asks"))
    _call(meter.labelled("draft"))

    assert meter.usage.input_tokens == 4100
    assert meter.usage.output_tokens == 1520
    assert [c.purpose for c in meter.calls] == ["asks", "draft"]


def test_labelled_views_share_one_tally():
    inner = _FakeClient([LlmUsage(10, 1)])
    meter = MeteredClient(inner)
    asks = meter.labelled("asks")
    _call(asks)
    assert len(meter.calls) == 1


def test_reasoning_tokens_are_billed_as_output():
    usage = LlmUsage(input_tokens=100, output_tokens=200, thinking_tokens=300)
    assert usage.billed_output_tokens == 500


def test_the_meter_survives_a_provider_that_reports_no_usage():
    meter = MeteredClient(_FakeClient([None]))
    _call(meter)
    assert meter.usage == LlmUsage(0, 0, 0, 0)


def test_no_calls_means_no_usage_rather_than_zero():
    assert MeteredClient(_FakeClient([])).usage is None


def test_cost_is_tokens_times_the_rate():
    assert PRICES.cost_usd("test-model", 1_000_000, 0) == pytest.approx(1.0)
    assert PRICES.cost_usd("test-model", 0, 1_000_000) == pytest.approx(10.0)
    assert PRICES.cost_usd("test-model", 500_000, 100_000) == pytest.approx(1.5)


def test_cached_input_is_charged_at_the_cache_rate():
    """Cached tokens are part of the input count, not an extra on top of it."""
    prices = PriceList(
        models={"cached": ModelPrice(input_per_million=1.0, output_per_million=0.0,
                                     cached_input_per_million=0.1)}
    )
    # Half of a million input tokens served from cache: 500k at $1 plus 500k at
    # $0.10 per million.
    assert prices.cost_usd("cached", 1_000_000, 0, 500_000) == pytest.approx(0.55)
    assert prices.cost_usd("cached", 1_000_000, 0, 0) == pytest.approx(1.0)


def test_without_a_cache_rate_cached_tokens_cost_full_price():
    """Overstating the bill is the safe direction for a missing rate."""
    assert PRICES.cost_usd("test-model", 1_000_000, 0, 400_000) == pytest.approx(1.0)


def test_more_cached_tokens_than_input_cannot_produce_a_credit():
    prices = PriceList(
        models={"cached": ModelPrice(1.0, 0.0, cached_input_per_million=0.1)}
    )
    assert prices.cost_usd("cached", 1000, 0, 99_999) == pytest.approx(0.0001)


def test_shekels_appear_only_when_a_rate_is_configured():
    assert "\u20aa" not in format_money(PRICES, 1.0)
    with_rate = PriceList(models=PRICES.models, usd_to_ils=3.7)
    assert "\u20aa3.70" in format_money(with_rate, 1.0)


def test_an_unpriced_model_is_unknown_and_not_free():
    """A plausible wrong number is worse than admitting the price is unknown."""
    assert PRICES.cost_usd("some-new-model", 1_000_000, 1_000_000) is None
    assert format_usd(None) == "cost unknown"


def test_a_null_price_in_the_file_stays_unknown(tmp_path):
    path = tmp_path / "pricing.yaml"
    path.write_text(
        "models:\n  half-filled:\n    input: 0.30\n    output: null\n"
        "  complete:\n    input: 0.10\n    output: 0.40\n",
        encoding="utf-8",
    )
    prices = load_prices(path)
    assert prices.price_for("half-filled") is None
    assert prices.price_for("complete") == ModelPrice(0.10, 0.40)


def test_the_shipped_price_file_covers_the_configured_model():
    """The configured model going unpriced is the mistake worth catching."""
    prices = load_prices()
    assert prices.price_for("gemini-3.6-flash") is not None


def test_a_missing_price_file_does_not_raise(tmp_path):
    """Cost reporting must never be able to stop the agent drafting."""
    assert load_prices(tmp_path / "absent.yaml").models == {}


def test_the_models_prefix_is_tolerated():
    assert PRICES.price_for("models/test-model") is not None


def test_totals_count_unpriced_drafts_apart():
    records = [
        UsageRecord(at="2026-08-22T10:00:00+00:00", command="c", model="test-model",
                    input_tokens=1_000_000, output_tokens=0),
        UsageRecord(at="2026-08-22T11:00:00+00:00", command="c", model="mystery-model",
                    input_tokens=1_000_000, output_tokens=0),
    ]
    result = totals(records, PRICES)
    assert result.drafts == 2
    assert result.unpriced == 1
    assert result.cost_usd == pytest.approx(1.0)
    # The average is over what could be priced, not over everything.
    assert result.average_usd == pytest.approx(1.0)


def test_reasoning_tokens_reach_the_cost():
    record = UsageRecord(
        at="2026-08-22T10:00:00+00:00", command="c", model="test-model",
        input_tokens=0, output_tokens=500_000, thinking_tokens=500_000,
    )
    assert record.cost_usd(PRICES) == pytest.approx(10.0)


def test_the_log_round_trips_hebrew_and_appends(tmp_path):
    log = UsageLog(tmp_path / "usage.jsonl")
    log.record(UsageRecord(at="2026-08-22T10:00:00+00:00", command="outlook-watch",
                           model="test-model", subject="דחוף - מכתב מרשות האוכלוסין",
                           matter="mike-test", input_tokens=10))
    log.record(UsageRecord(at="2026-08-22T11:00:00+00:00", command="outlook-watch",
                           model="test-model", subject="עוד הודעה", input_tokens=20))

    records = log.read()
    assert len(records) == 2
    assert records[0].subject == "דחוף - מכתב מרשות האוכלוסין"
    assert records[0].matter == "mike-test"


def test_a_truncated_final_line_is_skipped_not_fatal(tmp_path):
    """A killed run can leave half a line; the rest of the history still reads."""
    path = tmp_path / "usage.jsonl"
    path.write_text(
        '{"at": "2026-08-22T10:00:00+00:00", "command": "c", "model": "test-model"}\n'
        '{"at": "2026-08-22T11:00:00+00:00", "comm',
        encoding="utf-8",
    )
    assert len(UsageLog(path).read()) == 1


def test_reading_an_absent_log_is_empty(tmp_path):
    assert UsageLog(tmp_path / "nothing.jsonl").read() == []


def test_records_outside_the_window_are_dropped(tmp_path):
    log = UsageLog(tmp_path / "usage.jsonl")
    log.record(UsageRecord(at="2020-01-01T00:00:00+00:00", command="c", model="test-model"))
    assert log.read() != []
    assert log.read(since=cutoff(30)) == []


def test_grouping_labels_a_draft_with_no_matter():
    records = [UsageRecord(at="2026-08-22T10:00:00+00:00", command="c", model="m")]
    assert "(no matter)" in group(records, "matter")


@dataclass
class _Call:
    purpose: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0


@dataclass
class _Report:
    subject: str = "נושא"
    model: str = "test-model"
    usage: LlmUsage | None = None
    calls: list = None
    seconds: float = 12.5
    ok: bool = True


def test_a_record_carries_the_per_call_breakdown():
    report = _Report(
        usage=LlmUsage(4100, 1520, 300),
        calls=[_Call("asks", 100, 20), _Call("draft", 4000, 1500, 300)],
    )
    record = from_report(report, command="outlook-watch", matter="mike-test")
    assert record.input_tokens == 4100
    assert record.thinking_tokens == 300
    assert [c["purpose"] for c in record.calls] == ["asks", "draft"]
    assert record.seconds == 12.5


def test_a_report_without_usage_records_zeroes_rather_than_failing():
    record = from_report(_Report(usage=None, calls=[]), command="draft")
    assert record.input_tokens == 0
