"""The per-draft spend record.

One JSON object per line, appended and never rewritten. A draft that crashes
half way through cannot corrupt an earlier record, and the file stays readable
by anything that can read a line, which matters for a record that may end up
supporting a disbursement on a client bill.

Only token counts are stored here. Money is worked out on read, from
config/pricing.yaml, so a corrected price fixes the whole history.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rotem_agent.logs import LOG_DIR
from rotem_agent.pricing import PriceList


@dataclass(frozen=True)
class UsageRecord:
    at: str
    command: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    seconds: float = 0.0
    calls: list[dict] = field(default_factory=list)
    sender: str = ""
    subject: str = ""
    matter: str = ""
    ok: bool = True
    key: str = ""

    @property
    def billed_output_tokens(self) -> int:
        return self.output_tokens + self.thinking_tokens

    def cost_usd(self, prices: PriceList) -> float | None:
        return prices.cost_usd(
            self.model, self.input_tokens, self.billed_output_tokens, self.cached_tokens
        )


class UsageLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or LOG_DIR / "usage.jsonl"

    def record(self, entry: UsageRecord) -> None:
        """Failure to write must never lose a draft that already exists."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except OSError:
            pass

    def read(self, since: datetime | None = None) -> list[UsageRecord]:
        if not self.path.exists():
            return []
        records: list[UsageRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                # A truncated final line is expected if a run was killed mid
                # write. Skipping it beats refusing to report anything.
                continue
            if not isinstance(data, dict):
                continue
            record = _from_dict(data)
            if since is not None and not _at_or_after(record.at, since):
                continue
            records.append(record)
        return records


@dataclass(frozen=True)
class Totals:
    # Not all records are drafts. Transcribing a scan and running a document
    # audit are metered here too, so counting them as drafts would report a
    # per-draft average over things that never produced a reply.
    records: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    unpriced: int = 0

    @property
    def billed_output_tokens(self) -> int:
        return self.output_tokens + self.thinking_tokens

    @property
    def priced(self) -> int:
        return self.records - self.unpriced

    @property
    def average_usd(self) -> float | None:
        return self.cost_usd / self.priced if self.priced else None


def totals(records: list[UsageRecord], prices: PriceList) -> Totals:
    """Unpriced drafts are counted apart rather than treated as free."""
    cost = 0.0
    unpriced = 0
    for record in records:
        amount = record.cost_usd(prices)
        if amount is None:
            unpriced += 1
        else:
            cost += amount
    return Totals(
        records=len(records),
        input_tokens=sum(r.input_tokens for r in records),
        output_tokens=sum(r.output_tokens for r in records),
        thinking_tokens=sum(r.thinking_tokens for r in records),
        cached_tokens=sum(r.cached_tokens for r in records),
        seconds=sum(r.seconds for r in records),
        cost_usd=cost,
        unpriced=unpriced,
    )


def group(records: list[UsageRecord], key: str) -> dict[str, list[UsageRecord]]:
    grouped: dict[str, list[UsageRecord]] = {}
    for record in records:
        grouped.setdefault(_group_key(record, key), []).append(record)
    return grouped


def from_report(
    report,
    *,
    command: str,
    sender: str = "",
    subject: str = "",
    matter: str = "",
    key: str = "",
) -> UsageRecord:
    usage = getattr(report, "usage", None)
    return UsageRecord(
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        command=command,
        model=getattr(report, "model", "") or "",
        input_tokens=(usage.input_tokens or 0) if usage else 0,
        output_tokens=(usage.output_tokens or 0) if usage else 0,
        thinking_tokens=(usage.thinking_tokens or 0) if usage else 0,
        cached_tokens=(usage.cached_tokens or 0) if usage else 0,
        seconds=float(getattr(report, "seconds", 0.0) or 0.0),
        calls=[
            {
                "purpose": call.purpose,
                "in": call.input_tokens,
                "out": call.output_tokens,
                "thinking": call.thinking_tokens,
                "cached": getattr(call, "cached_tokens", 0),
            }
            for call in getattr(report, "calls", []) or []
        ],
        sender=sender,
        subject=subject,
        matter=matter,
        ok=bool(getattr(report, "ok", True)),
        key=key,
    )


def cutoff(days: int | None) -> datetime | None:
    if days is None or days < 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def _group_key(record: UsageRecord, key: str) -> str:
    if key == "day":
        return record.at[:10] or "unknown"
    if key == "model":
        return record.model or "unknown"
    if key == "matter":
        return record.matter or "(no matter)"
    if key == "sender":
        return record.sender or "unknown"
    return "all"


def _from_dict(data: dict) -> UsageRecord:
    def integer(key: str) -> int:
        try:
            return int(data.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    calls = data.get("calls")
    return UsageRecord(
        at=str(data.get("at", "")),
        command=str(data.get("command", "")),
        model=str(data.get("model", "")),
        input_tokens=integer("input_tokens"),
        output_tokens=integer("output_tokens"),
        thinking_tokens=integer("thinking_tokens"),
        cached_tokens=integer("cached_tokens"),
        seconds=float(data.get("seconds") or 0.0),
        calls=calls if isinstance(calls, list) else [],
        sender=str(data.get("sender", "")),
        subject=str(data.get("subject", "")),
        matter=str(data.get("matter", "")),
        ok=bool(data.get("ok", True)),
        key=str(data.get("key", "")),
    )


def _at_or_after(stamp: str, moment: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return True  # Keep anything unparseable rather than hiding spend.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= moment
