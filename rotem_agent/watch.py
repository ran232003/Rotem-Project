from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Sequence

from rotem_agent.logs import logger
from rotem_agent.outlook.com import FoundMessage, OutlookMailbox
from rotem_agent.state import DraftLedger, LedgerEntry, message_key, utc_now


@dataclass(frozen=True)
class WatchOptions:
    save: bool = False
    interval_seconds: int = 60
    backlog_days: int = 7
    max_per_cycle: int = 5
    source_policy: str = "advisory"
    force: bool = False


def as_datetime(value: object) -> datetime | None:
    """Normalise an Outlook timestamp to an aware UTC datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def backlog_cutoff(days: int, now: datetime | None = None) -> datetime | None:
    """Ignore anything older than `days`, or everything old when days is 0.

    Without this, first run against a mailbox with years of history would draft
    replies to every message it finds.
    """
    if days < 0:
        return None
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def select_pending(
    matches: Iterable[FoundMessage],
    ledger: DraftLedger,
    *,
    cutoff: datetime | None,
    max_items: int,
    force: bool = False,
) -> list[FoundMessage]:
    """Messages that still need a draft, oldest first.

    Chronological order matters: if two messages arrive in one thread, drafting
    the older one first means the newer draft quotes a trail that already
    reflects it.
    """
    pending: list[tuple[datetime | None, FoundMessage]] = []
    for match in matches:
        received = as_datetime(match.received)
        if cutoff is not None and received is not None and received < cutoff:
            continue
        if not force and key_for(match) in ledger:
            continue
        pending.append((received, match))

    pending.sort(key=lambda pair: pair[0] or datetime.min.replace(tzinfo=timezone.utc))
    return [match for _, match in pending[:max_items]]


def key_for(match: FoundMessage) -> str:
    return message_key(match.message_id, match.conversation_id, str(match.received or ""))


def run_cycle(
    box: OutlookMailbox,
    ledger: DraftLedger,
    senders: Sequence[str],
    draft_fn: Callable[..., object],
    options: WatchOptions,
    log: Callable[[str], None] = print,
    retrieve_fn: Callable[[object, FoundMessage], tuple[list, list]] | None = None,
    emit_fn: Callable[[object, FoundMessage], None] | None = None,
) -> list[LedgerEntry]:
    """One pass: find unanswered mail from the allowed senders and draft it."""
    matches: list[FoundMessage] = []
    for sender in senders:
        matches.extend(box.messages_from(sender, limit=50))

    pending = select_pending(
        matches,
        ledger,
        cutoff=backlog_cutoff(options.backlog_days),
        max_items=options.max_per_cycle,
        force=options.force,
    )
    if not pending:
        return []

    log(f"{len(pending)} message(s) to draft")
    written: list[LedgerEntry] = []
    for match in pending:
        log(f"  drafting: {match.subject}  [{match.received}]")
        email = box.to_parsed_email(match.item)
        excerpts, attachments = retrieve_fn(email, match) if retrieve_fn else ([], [])
        report = draft_fn(email, excerpts, attachments)
        # The internal note carries the warnings, unverified claims and approval
        # level. Writing a draft into the mailbox while discarding the analysis
        # would leave the reviewer with nothing to review against.
        if emit_fn:
            emit_fn(report, match)

        draft_entry_id = None
        if options.save:
            draft = box.create_reply_draft(match.item, report.draft_text, save=True)
            draft_entry_id = _entry_id(draft)

        entry = LedgerEntry(
            key=key_for(match),
            message_id=match.message_id,
            conversation_id=match.conversation_id,
            sender=match.sender,
            subject=match.subject,
            received=str(match.received or ""),
            drafted_at=utc_now(),
            model=getattr(report, "model", "") or "",
            source_policy=options.source_policy,
            draft_entry_id=draft_entry_id,
            ok=bool(getattr(report, "ok", False)),
            problems=list(getattr(report, "problems", []) or []),
        )
        # Record only after the draft exists, so a crash mid-draft leaves the
        # message pending rather than silently answered.
        ledger.record(entry)
        written.append(entry)
        log(
            f"    {'saved to Drafts' if options.save else 'dry run'}"
            f"{'' if entry.ok else '  (verification problems: ' + str(len(entry.problems)) + ')'}"
        )
    return written


def watch(
    box: OutlookMailbox,
    ledger: DraftLedger,
    senders: Sequence[str],
    draft_fn: Callable[..., object],
    options: WatchOptions,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
    retrieve_fn: Callable[[object, FoundMessage], tuple[list, list]] | None = None,
    emit_fn: Callable[[object, FoundMessage], None] | None = None,
) -> int:
    """Poll until interrupted. Returns the number of drafts created."""
    total = 0
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        cycle += 1
        try:
            total += len(
                run_cycle(
                    box, ledger, senders, draft_fn, options, log, retrieve_fn, emit_fn
                )
            )
        except Exception as exc:  # Outlook restarts and transient COM faults
            # The console gets the one-line version; the log gets the traceback,
            # which is the only thing that makes a COM fault diagnosable later.
            log(f"  cycle failed: {exc}")
            logger().exception("watch cycle %s failed", cycle)
            box.connect()
        if max_cycles is not None and cycle >= max_cycles:
            break
        sleep(options.interval_seconds)
    return total


def _entry_id(draft: object) -> str | None:
    try:
        return str(draft.EntryID)  # type: ignore[attr-defined]
    except Exception:
        return None
