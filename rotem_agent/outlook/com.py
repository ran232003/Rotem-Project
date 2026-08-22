from __future__ import annotations

import dataclasses
import html
import mimetypes
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from pathlib import Path
from typing import Any, Iterator

from rotem_agent.config import (
    CONFIG_DIR,
    BoilerplateRules,
    ConfigError,
    load_boilerplate,
    read_yaml,
)
from rotem_agent.mailparse.parser import Attachment, ParsedEmail, parse_message

OL_MAIL_ITEM = 43
OL_FOLDER_INBOX = 6
OL_FOLDER_SENT = 5
OL_FOLDER_DRAFTS = 16
OL_FOLDER_DELETED = 3
OL_TO, OL_CC = 1, 2

_PROP = "http://schemas.microsoft.com/mapi/proptag/"
PR_SENDER_EMAIL = f"{_PROP}0x0C1F001F"
PR_SENDER_SMTP = f"{_PROP}0x5D01001F"
PR_SENT_REPRESENTING_SMTP = f"{_PROP}0x5D02001F"
PR_SMTP_ADDRESS = f"{_PROP}0x39FE001F"
PR_INTERNET_MESSAGE_ID = f"{_PROP}0x1035001F"
PR_IN_REPLY_TO_ID = f"{_PROP}0x1042001F"
PR_INTERNET_REFERENCES = f"{_PROP}0x1039001F"
PR_ATTACH_CONTENT_ID = f"{_PROP}0x3712001F"

AGENT_CATEGORY = "AI draft"


class OutlookError(RuntimeError):
    pass


@dataclass(frozen=True)
class MailboxConfig:
    """Which mailbox to read and, critically, whose mail may be touched.

    The allowlist is a hard boundary, not a convenience. This runs against a
    corporate mailbox holding thousands of unrelated messages, so every read
    path checks membership before returning an item.
    """

    mailbox: str
    allowed_senders: list[str]

    def allows(self, address: str | None) -> bool:
        if not address:
            return False
        return address.strip().lower() in {a.strip().lower() for a in self.allowed_senders}


def load_mailbox_config(path: Path | None = None) -> MailboxConfig:
    target = path or CONFIG_DIR / "mailbox.yaml"
    if not target.exists():
        raise ConfigError(
            f"Missing {target}. Copy config/mailbox.example.yaml to config/mailbox.yaml "
            "and set your mailbox plus the senders the agent may read."
        )
    data = read_yaml(target)
    senders = [str(s) for s in data.get("allowed_senders", []) if str(s).strip()]
    if not senders:
        raise ConfigError(f"{target} has no allowed_senders; refusing to scan the whole mailbox.")
    return MailboxConfig(mailbox=str(data.get("mailbox", "")).strip(), allowed_senders=senders)


@dataclass
class FoundMessage:
    """A matched Outlook item plus the folder it came from."""

    item: Any
    folder_path: str
    received: Any
    subject: str
    sender: str
    conversation_id: str | None


class OutlookMailbox:
    def __init__(self, config: MailboxConfig, rules: BoilerplateRules | None = None) -> None:
        self._config = config
        self._rules = rules or load_boilerplate()
        self._app: Any = None
        self._ns: Any = None

    # ------------------------------------------------------------------ connect

    def connect(self) -> None:
        try:
            import win32com.client
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise OutlookError("pywin32 is not installed. Run: pip install pywin32") from exc
        try:
            self._app = win32com.client.Dispatch("Outlook.Application")
            self._ns = self._app.GetNamespace("MAPI")
        except Exception as exc:  # pragma: no cover - environment dependent
            raise OutlookError(
                "Cannot reach Outlook over COM. Open classic Outlook for Windows and retry."
            ) from exc

    @property
    def namespace(self) -> Any:
        if self._ns is None:
            self.connect()
        return self._ns

    def account_addresses(self) -> list[str]:
        return [str(a.SmtpAddress) for a in self.namespace.Accounts]

    def folder(self, kind: int) -> Any:
        return self.namespace.GetDefaultFolder(kind)

    # ------------------------------------------------------------------- search

    def messages_from(self, address: str, limit: int = 20) -> list[FoundMessage]:
        """Every message from `address`, searched across the whole primary store.

        Mail from an external address is often filed by a rule rather than left
        in the Inbox, so restricting to the Inbox alone misses threads.
        """
        if not self._config.allows(address):
            raise OutlookError(
                f"{address} is not in allowed_senders; refusing to read it. "
                "Add it to config/mailbox.yaml if this is intended."
            )

        found: list[FoundMessage] = []
        for folder in self._walk_folders():
            for item in self._restrict_by_sender(folder, address):
                found.append(
                    FoundMessage(
                        item=item,
                        folder_path=str(_safe(lambda: folder.FolderPath, "?")),
                        received=_safe(lambda: item.ReceivedTime, None),
                        subject=str(_safe(lambda: item.Subject, "")),
                        sender=_sender_address(item) or "",
                        conversation_id=_safe(lambda: str(item.ConversationID), None),
                    )
                )
                if len(found) >= limit:
                    break
            if len(found) >= limit:
                break

        found.sort(key=lambda m: str(m.received or ""), reverse=True)
        return found

    def _walk_folders(self) -> Iterator[Any]:
        """Inbox first, then the rest of the primary store, skipping Deleted Items."""
        inbox = self.folder(OL_FOLDER_INBOX)
        yield inbox
        deleted_id = _safe(lambda: self.folder(OL_FOLDER_DELETED).EntryID, None)
        root = _safe(lambda: inbox.Parent, None)
        if root is None:
            return
        yield from _descend(root, skip_ids={_safe(lambda: inbox.EntryID, None), deleted_id})

    def _restrict_by_sender(self, folder: Any, address: str) -> list[Any]:
        """Use a server-side restriction; a manual walk of 6,000+ items is far too slow."""
        items = _safe(lambda: folder.Items, None)
        if items is None:
            return []
        for prop in (PR_SENDER_SMTP, PR_SENDER_EMAIL, PR_SENT_REPRESENTING_SMTP):
            query = f'@SQL="{prop}" = \'{address}\''
            try:
                restricted = items.Restrict(query)
                hits = [i for i in restricted if _safe(lambda: i.Class, None) == OL_MAIL_ITEM]
            except Exception:
                continue
            if hits:
                return hits
        return []

    # -------------------------------------------------------------------- parse

    def to_parsed_email(self, item: Any) -> ParsedEmail:
        """Reuse the .eml pipeline by rebuilding the item as a MIME message.

        Quote splitting, boilerplate stripping and HTML flattening already work
        and are tested; duplicating them against the COM object model would mean
        two code paths that drift apart.
        """
        message = EmailMessage()
        message["Subject"] = str(_safe(lambda: item.Subject, "") or "")

        sender = _sender_address(item) or ""
        sender_name = str(_safe(lambda: item.SenderName, "") or "")
        if sender:
            message["From"] = formataddr((sender_name, sender))

        for header, kind in (("To", OL_TO), ("Cc", OL_CC)):
            people = _recipients(item, kind)
            if people:
                message[header] = ", ".join(formataddr(p) for p in people)

        sent_at = _safe(lambda: item.ReceivedTime, None) or _safe(lambda: item.SentOn, None)
        if sent_at is not None:
            try:
                message["Date"] = format_datetime(sent_at)
            except (TypeError, ValueError):
                pass

        for header, prop in (
            ("Message-ID", PR_INTERNET_MESSAGE_ID),
            ("In-Reply-To", PR_IN_REPLY_TO_ID),
            ("References", PR_INTERNET_REFERENCES),
        ):
            value = _prop(item, prop)
            if value:
                message[header] = value

        body = str(_safe(lambda: item.HTMLBody, "") or "")
        if body.strip():
            message.set_content(body, subtype="html")
        else:
            message.set_content(str(_safe(lambda: item.Body, "") or ""))

        parsed = parse_message(message, self._rules)
        return dataclasses.replace(parsed, attachments=_attachments(item))

    # ------------------------------------------------------------------- drafts

    def create_reply_draft(self, item: Any, body_text: str, *, save: bool = True) -> Any:
        """Create a threaded reply in Drafts. Never sends."""
        reply = item.Reply()
        reply.HTMLBody = rtl_html(body_text) + str(_safe(lambda: reply.HTMLBody, "") or "")
        _tag(reply)
        if save:
            reply.Save()
        return reply

    def create_new_draft(
        self, to: str, subject: str, body_text: str, *, save: bool = True
    ) -> Any:
        """A standalone draft, for eyeballing rendering without touching a real thread."""
        mail = self.namespace.Application.CreateItem(0)  # olMailItem
        mail.To = to
        mail.Subject = subject
        mail.HTMLBody = rtl_html(body_text)
        _tag(mail)
        if save:
            mail.Save()
        return mail


def rtl_html(text: str) -> str:
    """Wrap the Hebrew draft so Outlook renders it right-to-left.

    Without an explicit dir attribute Outlook infers direction per paragraph,
    which strands punctuation and any Latin words on the wrong side.
    """
    blocks = [b for b in re.split(r"\n{2,}", text.strip()) if b.strip()]
    paragraphs = "".join(
        f'<p style="margin:0 0 10pt 0">{html.escape(b).replace(chr(10), "<br>")}</p>'
        for b in blocks
    )
    return (
        '<div dir="rtl" style="text-align:right;font-family:Arial,sans-serif;font-size:11pt">'
        f"{paragraphs}</div>"
    )


def _tag(mail: Any) -> None:
    """Mark the draft as machine-written so it is obvious in the folder list."""
    try:
        existing = str(mail.Categories or "")
        if AGENT_CATEGORY not in existing:
            mail.Categories = f"{existing}, {AGENT_CATEGORY}".strip(", ")
    except Exception:
        pass


def _descend(folder: Any, skip_ids: set[str | None], depth: int = 0) -> Iterator[Any]:
    if depth > 6:
        return
    for child in _safe(lambda: folder.Folders, []) or []:
        if _safe(lambda: child.EntryID, None) in skip_ids:
            continue
        if _safe(lambda: child.DefaultItemType, None) == 0:  # olMailItem folders only
            yield child
        yield from _descend(child, skip_ids, depth + 1)


def _sender_address(item: Any) -> str | None:
    """Resolve the sender to SMTP.

    Exchange senders expose a long X.500 DN in SenderEmailAddress, so the SMTP
    properties are tried first and the DN is only a last resort.
    """
    for prop in (PR_SENDER_SMTP, PR_SENT_REPRESENTING_SMTP):
        value = _prop(item, prop)
        if value and "@" in value:
            return value
    if str(_safe(lambda: item.SenderEmailAddressType, "") or "").upper() == "EX":
        resolved = _safe(
            lambda: item.Sender.GetExchangeUser().PrimarySmtpAddress, None
        )
        if resolved:
            return str(resolved)
    raw = _safe(lambda: item.SenderEmailAddress, None)
    return str(raw) if raw and "@" in str(raw) else None


def _recipients(item: Any, kind: int) -> list[tuple[str, str]]:
    people: list[tuple[str, str]] = []
    for recipient in _safe(lambda: item.Recipients, []) or []:
        if _safe(lambda: recipient.Type, None) != kind:
            continue
        address = _prop(recipient, PR_SMTP_ADDRESS)
        if not address:
            address = _safe(
                lambda: recipient.AddressEntry.GetExchangeUser().PrimarySmtpAddress, None
            )
        if not address:
            address = _safe(lambda: recipient.Address, None)
        if address and "@" in str(address):
            people.append((str(_safe(lambda: recipient.Name, "") or ""), str(address)))
    return people


def _attachments(item: Any) -> list[Attachment]:
    found: list[Attachment] = []
    for attachment in _safe(lambda: item.Attachments, []) or []:
        name = str(_safe(lambda: attachment.FileName, "") or "")
        content_id = _prop(attachment, PR_ATTACH_CONTENT_ID)
        guessed = mimetypes.guess_type(name)[0] or "application/octet-stream"
        found.append(
            Attachment(
                filename=name or None,
                content_type=guessed,
                size=int(_safe(lambda: attachment.Size, 0) or 0),
                content_id=content_id,
                disposition="inline" if content_id else "attachment",
            )
        )
    return found


def _prop(obj: Any, tag: str) -> str | None:
    try:
        value = obj.PropertyAccessor.GetProperty(tag)
    except Exception:
        return None
    text = str(value).strip() if value is not None else ""
    return text or None


def _safe(getter: Any, default: Any) -> Any:
    """COM raises for absent or blocked properties; treat that as missing data."""
    try:
        return getter()
    except Exception:
        return default
