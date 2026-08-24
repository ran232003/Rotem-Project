from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Sequence

from rotem_agent.control import stop_requested
from rotem_agent.logs import logger
from rotem_agent.outlook.com import FoundMessage, OutlookMailbox
from rotem_agent.state import DraftLedger, LedgerEntry, message_key, utc_now

# How long a stop can take to be noticed while the watcher is idle between
# polls. Short enough that the button feels immediate, long enough not to spin.
_STOP_POLL_SECONDS = 1.0


# The allowlist is resolved once per cycle rather than held, so adding a client
# to config/mailbox.yaml takes effect without stopping the agent.
Senders = Sequence[str] | Callable[[], Sequence[str]]


@dataclass(frozen=True)
class WatchOptions:
    save: bool = False
    interval_seconds: int = 60
    backlog_days: int = 7
    start_date: datetime | None = None
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


def backlog_cutoff(
    days: int, now: datetime | None = None, floor: datetime | None = None
) -> datetime | None:
    """The oldest message worth drafting: the later of two limits.

    `days` is a rolling window, without which a first run against a mailbox
    holding years of history would draft a reply to everything in it. `floor` is
    a fixed date from configuration — when the agent started work, before which
    old threads are not its business no matter how wide the window is.

    Whichever is later wins, so neither limit can be widened by the other.
    """
    rolling = None if days < 0 else (now or datetime.now(timezone.utc)) - timedelta(days=days)
    if rolling is None:
        return floor
    if floor is None:
        return rolling
    return max(rolling, floor)


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


def resolve_senders(senders: Senders) -> list[str]:
    return list(senders() if callable(senders) else senders)


def run_cycle(
    box: OutlookMailbox,
    ledger: DraftLedger,
    senders: Senders,
    draft_fn: Callable[..., object],
    options: WatchOptions,
    log: Callable[[str], None] = print,
    retrieve_fn: Callable[[object, FoundMessage], tuple[list, list]] | None = None,
    emit_fn: Callable[[object, FoundMessage], None] | None = None,
) -> list[LedgerEntry]:
    """One pass: find unanswered mail from the allowed senders and draft it."""
    ledger.reload()
    matches: list[FoundMessage] = []
    for sender in resolve_senders(senders):
        matches.extend(box.messages_from(sender, limit=50))

    pending = select_pending(
        matches,
        ledger,
        cutoff=backlog_cutoff(options.backlog_days, floor=options.start_date),
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
    senders: Senders,
    draft_fn: Callable[..., object],
    options: WatchOptions,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
    retrieve_fn: Callable[[object, FoundMessage], tuple[list, list]] | None = None,
    emit_fn: Callable[[object, FoundMessage], None] | None = None,
    should_stop: Callable[[], bool] = stop_requested,
) -> int:
    """Poll until interrupted or asked to stop. Returns the drafts created.

    The stop request is honoured between messages rather than during one.
    Interrupting a draft would leave a partly written reply in Outlook and a
    model call whose spend was never recorded.
    """
    total = 0
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        if should_stop():
            log("  stop requested; finishing.")
            break
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
        if not _wait(sleep, options.interval_seconds, should_stop):
            log("  stop requested; finishing.")
            break
    return total


def _wait(sleep: Callable[[float], None], seconds: float, should_stop: Callable[[], bool]) -> bool:
    """Sleep in slices so a stop is acted on promptly, not a minute later.

    Returns False when a stop was requested during the wait.
    """
    remaining = float(seconds)
    while remaining > 0:
        if should_stop():
            return False
        slice_seconds = min(_STOP_POLL_SECONDS, remaining)
        sleep(slice_seconds)
        remaining -= slice_seconds
    return not should_stop()


def _entry_id(draft: object) -> str | None:
    try:
        return str(draft.EntryID)  # type: ignore[attr-defined]
    except Exception:
        return None
