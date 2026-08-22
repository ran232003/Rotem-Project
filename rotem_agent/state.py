from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rotem_agent.config import PROJECT_ROOT

STATE_DIR = PROJECT_ROOT / "state"


@dataclass(frozen=True)
class LedgerEntry:
    """One record of the agent having drafted a reply.

    Doubles as the audit trail: what was answered, by which model, under which
    source policy, and whether the verification checks passed.
    """

    key: str
    message_id: str | None
    conversation_id: str | None
    sender: str
    subject: str
    received: str
    drafted_at: str
    model: str
    source_policy: str
    draft_entry_id: str | None
    ok: bool
    problems: list[str] = field(default_factory=list)


def message_key(message_id: str | None, conversation_id: str | None, received: str) -> str:
    """Identify a message so it is never answered twice.

    The Internet Message-ID is the only stable identifier here: an Outlook
    EntryID changes when an item moves between folders or stores, which would
    make a filed message look new. Conversation plus timestamp is the fallback,
    keyed per message rather than per thread so a genuine follow-up in a thread
    we already answered is still picked up.
    """
    if message_id:
        return message_id.strip()
    return f"conv:{(conversation_id or '?').strip()}:{received}"


class DraftLedger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or STATE_DIR / "ledger.json"
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt ledger must not stop the agent, but silently treating
            # every message as new would spray duplicate drafts, so move it
            # aside and make the loss visible.
            self.path.replace(self.path.with_suffix(".corrupt"))
            return
        self._entries = data.get("entries", {}) if isinstance(data, dict) else {}

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def record(self, entry: LedgerEntry) -> None:
        self._entries[entry.key] = asdict(entry)
        self._flush()

    def forget(self, key: str) -> bool:
        if key not in self._entries:
            return False
        del self._entries[key]
        self._flush()
        return True

    def entries(self) -> list[dict]:
        return sorted(self._entries.values(), key=lambda e: e.get("drafted_at", ""), reverse=True)

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": self._entries}
        # Write and rename so an interrupted run cannot leave a half-written
        # ledger, which would look corrupt on the next start.
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
