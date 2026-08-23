"""Which drafts were used, recorded away from the process that asks.

The ledger records what the agent wrote. Whether the lawyer sent anything on
that thread afterwards is the only measure of whether a draft was worth writing,
and it lives in Sent Items.

Reading it is deliberately not done by whatever wants the answer. Outlook is
reached over COM, which is bound to the thread that initialised it, so a web
request handler calling into it is a threading fault waiting to happen. A
refresh therefore runs as its own short-lived process and leaves the result
here, and everything else reads this file.

That makes the answer a snapshot rather than live, which is why it carries the
time it was taken.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rotem_agent.state import STATE_DIR

STORE = STATE_DIR / "outcomes.json"

DEFAULT_DAYS = 30


@dataclass(frozen=True)
class Outcomes:
    refreshed_at: str | None = None
    window_days: int = DEFAULT_DAYS
    conversations: dict[str, str] = field(default_factory=dict)

    @property
    def known(self) -> bool:
        return self.refreshed_at is not None

    def was_sent(self, conversation_id: str | None, drafted_at: str) -> bool | None:
        """True, False, or None when we simply have not looked yet.

        None is not False. Reporting an unrefreshed store as 'not sent' would
        show every draft as discarded and invite exactly the wrong conclusion
        about whether the agent is useful.
        """
        if not self.known:
            return None
        if not conversation_id:
            return None
        sent_at = self.conversations.get(conversation_id)
        if sent_at is None:
            return False
        drafted = _parse(drafted_at)
        sent = _parse(sent_at)
        if drafted is None or sent is None:
            return None
        # A message sent before the draft existed is the client's own thread
        # activity, or our earlier reply, not use of this draft.
        return sent >= drafted


def load(path: Path | None = None) -> Outcomes:
    """Never raises. A missing or damaged file means unknown, not broken."""
    target = path or STORE
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Outcomes()
    if not isinstance(data, dict):
        return Outcomes()
    conversations = data.get("conversations")
    return Outcomes(
        refreshed_at=data.get("refreshed_at"),
        window_days=int(data.get("window_days") or DEFAULT_DAYS),
        conversations=conversations if isinstance(conversations, dict) else {},
    )


def save(outcomes: Outcomes, path: Path | None = None) -> None:
    target = path or STORE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "refreshed_at": outcomes.refreshed_at,
        "window_days": outcomes.window_days,
        "conversations": outcomes.conversations,
    }
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)


def refresh(box: Any, *, days: int = DEFAULT_DAYS, now: datetime | None = None) -> Outcomes:
    """Walk Sent Items once and record when each conversation was last replied to."""
    moment = now or datetime.now(timezone.utc)
    since = moment - timedelta(days=days)
    raw = box.sent_conversations(since)
    conversations = {}
    for conversation_id, when in raw.items():
        stamp = _iso(when)
        if stamp:
            conversations[str(conversation_id)] = stamp
    return Outcomes(
        refreshed_at=moment.isoformat(timespec="seconds"),
        window_days=days,
        conversations=conversations,
    )


def _iso(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    try:
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (AttributeError, ValueError, OSError):
        return None


def _parse(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
