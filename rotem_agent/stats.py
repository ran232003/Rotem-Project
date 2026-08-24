"""The numbers behind the dashboard.

Two sources, counted apart on purpose. Emails answered comes from the ledger,
which records replies drafted into the mailbox. Spend comes from the usage log,
which meters every model call including transcriptions and document audits that
never produced a reply. Adding them together would produce a per-email cost that
is wrong in the direction that flatters the agent.

Windows are local days. The logs are UTC, and a lawyer looking at 'today' at
nine in the morning means her today. The all-time window has no start at all
rather than a sentinel date, so nothing predating an arbitrary epoch can drop
out of a total whose whole point is that it leaves nothing out.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from rotem_agent.outcomes import Outcomes
from rotem_agent.pricing import PriceList
from rotem_agent.usage import UsageRecord


@dataclass(frozen=True)
class Window:
    label: str
    answered: int = 0
    sent: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_ils: float | None = None
    unpriced: int = 0


@dataclass(frozen=True)
class Row:
    at: str
    sender: str
    subject: str
    cost_usd: float | None = None
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    sent: bool | None = None


def build(
    *,
    entries: list[dict],
    records: list[UsageRecord],
    prices: PriceList,
    outcomes: Outcomes,
    now: datetime | None = None,
    recent_days: int = 7,
    recent_limit: int = 200,
) -> dict:
    moment = (now or datetime.now(timezone.utc)).astimezone()
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    starts: dict[str, datetime | None] = {
        "today": midnight,
        "week": midnight - timedelta(days=6),
        "month": midnight - timedelta(days=29),
        "all": None,
    }

    cost_by_key = _cost_by_key(records, prices)

    windows = {
        name: _window(name, start, entries, records, prices, outcomes)
        for name, start in starts.items()
    }

    # The table covers the same span as the seven-day card, so the row count and
    # that card's figure agree. Two lists of "recent drafts" disagreeing by a few
    # rows is the kind of thing that costs an afternoon to explain.
    cutoff = midnight - timedelta(days=recent_days - 1)
    rows = []
    truncated = False
    for entry in sorted(entries, key=lambda e: str(e.get("drafted_at", "")), reverse=True):
        when = _parse(entry.get("drafted_at"))
        if when is None or when < cutoff:
            continue
        if len(rows) >= recent_limit:
            truncated = True
            break
        rows.append(
            Row(
                at=str(entry.get("drafted_at", "")),
                sender=str(entry.get("sender", "")),
                subject=str(entry.get("subject", "")),
                cost_usd=cost_by_key.get(str(entry.get("key", ""))),
                ok=bool(entry.get("ok", True)),
                problems=[str(p) for p in entry.get("problems", [])],
                sent=outcomes.was_sent(entry.get("conversation_id"), str(entry.get("drafted_at", ""))),
            )
        )

    return {
        "windows": {name: asdict(window) for name, window in windows.items()},
        "recent": [asdict(row) for row in rows],
        "recent_days": recent_days,
        "recent_truncated": truncated,
        "outcomes_known": outcomes.known,
        "outcomes_refreshed_at": outcomes.refreshed_at,
        "currency_note": None if prices.usd_to_ils else "Set usd_to_ils in config/pricing.yaml to also show shekels.",
    }


def _window(
    label: str,
    start: datetime | None,
    entries: list[dict],
    records: list[UsageRecord],
    prices: PriceList,
    outcomes: Outcomes,
) -> Window:
    answered = 0
    sent = 0
    sent_known = outcomes.known
    for entry in entries:
        when = _parse(entry.get("drafted_at"))
        if when is None or (start is not None and when < start):
            continue
        answered += 1
        if outcomes.was_sent(entry.get("conversation_id"), str(entry.get("drafted_at", ""))):
            sent += 1

    input_tokens = output_tokens = unpriced = 0
    cost = 0.0
    for record in records:
        when = _parse(record.at)
        if when is None or (start is not None and when < start):
            continue
        input_tokens += record.input_tokens
        output_tokens += record.billed_output_tokens
        amount = record.cost_usd(prices)
        if amount is None:
            unpriced += 1
        else:
            cost += amount

    return Window(
        label=label,
        answered=answered,
        sent=sent if sent_known else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
        cost_ils=None if prices.in_ils(cost) is None else round(prices.in_ils(cost), 2),
        unpriced=unpriced,
    )


def _cost_by_key(records: list[UsageRecord], prices: PriceList) -> dict[str, float]:
    """A draft is more than one model call, so costs are summed per message."""
    totals: dict[str, float] = {}
    for record in records:
        key = (record.key or "").strip()
        if not key:
            continue
        amount = record.cost_usd(prices)
        if amount is None:
            continue
        totals[key] = totals.get(key, 0.0) + amount
    return totals


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        return moment.astimezone()
    except (OSError, OverflowError, ValueError):
        # Windows refuses to localise a timestamp before 1970. Left in UTC
        # rather than dropped: it is still an ordered, comparable moment, and a
        # stray value in the ledger should not cost the page that reads it.
        return moment
