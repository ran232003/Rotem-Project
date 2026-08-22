from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from bs4 import BeautifulSoup

from rotem_agent.config import BoilerplateRules, load_boilerplate
from rotem_agent.mailparse.boilerplate import strip_boilerplate
from rotem_agent.mailparse.quotes import QuotedMessage, parse_quoted_chain, split_quotes


@dataclass(frozen=True)
class Party:
    name: str
    email: str

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>" if self.name else self.email


@dataclass(frozen=True)
class Attachment:
    filename: str | None
    content_type: str
    size: int
    content_id: str | None
    disposition: str | None

    @property
    def is_signature_asset(self) -> bool:
        """True for logos embedded in a signature block.

        In the sample thread a 78 KB inline PNG makes up half the message and
        sets X-MS-Has-Attach, but it carries no case information. Treating it as
        an attachment would fill the store with logos and pay OCR to read them.
        """
        return self.content_type.startswith("image/") and (
            self.content_id is not None or self.disposition == "inline"
        )


@dataclass(frozen=True)
class ParsedEmail:
    message_id: str | None
    in_reply_to: str | None
    references: list[str]
    subject: str
    date: str | None
    from_: Party | None
    to: list[Party]
    cc: list[Party]
    latest_body: str
    quoted_chain: list[QuotedMessage]
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def real_attachments(self) -> list[Attachment]:
        return [a for a in self.attachments if not a.is_signature_asset]

    @property
    def signature_assets(self) -> list[Attachment]:
        return [a for a in self.attachments if a.is_signature_asset]

    @property
    def participants(self) -> list[Party]:
        seen: dict[str, Party] = {}
        for party in ([self.from_] if self.from_ else []) + self.to + self.cc:
            seen.setdefault(party.email.lower(), party)
        return list(seen.values())

    def context_text(self) -> str:
        """Everything the draft is allowed to treat as grounded fact."""
        parts = [self.subject, self.latest_body]
        parts.extend(message.body for message in self.quoted_chain)
        return "\n\n".join(part for part in parts if part)


def parse_eml(path: str | Path, rules: BoilerplateRules | None = None) -> ParsedEmail:
    with Path(path).open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    return parse_message(message, rules)


def parse_message(message: EmailMessage, rules: BoilerplateRules | None = None) -> ParsedEmail:
    rules = rules or load_boilerplate()

    raw_body = _extract_body(message)
    latest, trail = split_quotes(raw_body)

    return ParsedEmail(
        message_id=_header(message, "Message-ID"),
        in_reply_to=_header(message, "In-Reply-To"),
        references=(_header(message, "References") or "").split(),
        subject=_header(message, "Subject") or "",
        date=_header(message, "Date"),
        from_=next(iter(_parties(message, "From")), None),
        to=_parties(message, "To"),
        cc=_parties(message, "Cc"),
        latest_body=strip_boilerplate(latest, rules),
        quoted_chain=[
            QuotedMessage(
                from_=m.from_,
                sent=m.sent,
                to=m.to,
                subject=m.subject,
                body=strip_boilerplate(m.body, rules),
            )
            for m in parse_quoted_chain(trail)
        ],
        attachments=_attachments(message),
    )


def _header(message: EmailMessage, name: str) -> str | None:
    value = message[name]
    return str(value).strip() if value is not None else None


def _parties(message: EmailMessage, name: str) -> list[Party]:
    header = message[name]
    if header is None:
        return []
    addresses = getattr(header, "addresses", None)
    if not addresses:
        return [Party(name="", email=str(header).strip())]
    return [
        Party(name=(a.display_name or "").strip(), email=(a.addr_spec or "").strip())
        for a in addresses
        if a.addr_spec
    ]


def _extract_body(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, ValueError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        return _html_to_text(content)
    return content


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _attachments(message: EmailMessage) -> list[Attachment]:
    found = []
    for part in message.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        content_id = part.get("Content-ID")
        found.append(
            Attachment(
                filename=part.get_filename(),
                content_type=part.get_content_type(),
                size=len(payload),
                content_id=content_id.strip() if content_id else None,
                disposition=part.get_content_disposition(),
            )
        )
    return found
