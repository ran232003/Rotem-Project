"""Separating a new message from the quoted trail beneath it.

This has to be bilingual. Correspondents on an English Outlook produce
``From:/Sent:/To:/Subject:`` headers while the firm's Hebrew Outlook produces
``מאת:/נשלח:/אל:/נושא:``, and both appear inside a single thread.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FLAGS = re.MULTILINE

# An Outlook attribution block: a From-style line followed within a few lines
# by a Sent/Date-style line. Requiring the pair avoids matching a stray
# "From:" that happens to appear in prose.
_EN_HEADER = re.compile(
    r"^[ \t]*From:[ \t]*\S.*(?:\r?\n.*){0,4}?\r?\n[ \t]*(?:Sent|Date):[ \t]*\S",
    _FLAGS,
)
_HE_HEADER = re.compile(
    r"^[ \t]*מאת:[ \t]*\S.*(?:\r?\n.*){0,4}?\r?\n[ \t]*(?:נשלח|תאריך):[ \t]*\S",
    _FLAGS,
)

_SEPARATORS = [
    _EN_HEADER,
    _HE_HEADER,
    re.compile(r"^[ \t]*-{2,}\s*Original Message\s*-{2,}", _FLAGS | re.IGNORECASE),
    re.compile(r"^[ \t]*-{2,}\s*הודעה מקורית\s*-{2,}", _FLAGS),
    re.compile(r"^_{20,}[ \t]*$", _FLAGS),
    re.compile(r"^[ \t]*On\b.{5,160}?\bwrote:[ \t]*$", _FLAGS),
    re.compile(r"^[ \t]*בתאריך\b.{5,160}?\bכתב", _FLAGS),
    re.compile(r"^[ \t]*>", _FLAGS),
]

_HEADER_LINE = re.compile(
    r"^[ \t]*(From|Sent|Date|To|Cc|Subject|מאת|נשלח|תאריך|אל|עותק|נושא)[ \t]*:[ \t]*(.*)$"
)

_FIELD_ALIASES = {
    "from": "from_",
    "מאת": "from_",
    "sent": "sent",
    "date": "sent",
    "נשלח": "sent",
    "תאריך": "sent",
    "to": "to",
    "אל": "to",
    "cc": "cc",
    "עותק": "cc",
    "subject": "subject",
    "נושא": "subject",
}


@dataclass(frozen=True)
class QuotedMessage:
    from_: str | None
    sent: str | None
    to: str | None
    subject: str | None
    body: str


def split_quotes(text: str) -> tuple[str, str]:
    """Return (latest message, quoted trail). The trail may be empty."""
    normalised = text.replace("\r\n", "\n")
    starts = [m.start() for pattern in _SEPARATORS if (m := pattern.search(normalised))]
    if not starts:
        return normalised.strip(), ""
    cut = min(starts)
    return normalised[:cut].strip(), normalised[cut:].strip()


def parse_quoted_chain(trail: str) -> list[QuotedMessage]:
    """Split a quoted trail into the individual messages it contains.

    In Phase 0 this is how a single .eml yields thread history: the trail holds
    the lawyer's own previous reply, which serves as both context and a style
    example.
    """
    if not trail.strip():
        return []

    normalised = trail.replace("\r\n", "\n")
    boundaries = sorted(
        {m.start() for pattern in (_EN_HEADER, _HE_HEADER) for m in pattern.finditer(normalised)}
    )
    if not boundaries:
        body = _strip_quote_markers(normalised)
        return [QuotedMessage(None, None, None, None, body)] if body.strip() else []

    # Text before the first attribution block is the sender's own signature or
    # disclaimer, not a quoted message.
    messages = []
    for index, start in enumerate(boundaries):
        end = boundaries[index + 1] if index + 1 < len(boundaries) else len(normalised)
        messages.append(_parse_block(normalised[start:end]))
    return messages


def _parse_block(block: str) -> QuotedMessage:
    fields: dict[str, str] = {}
    lines = block.split("\n")
    body_start = 0

    for index, line in enumerate(lines):
        match = _HEADER_LINE.match(line)
        if match:
            key = _FIELD_ALIASES.get(match.group(1).lower())
            if key and key not in fields:
                fields[key] = match.group(2).strip()
            body_start = index + 1
            continue
        if not line.strip():
            if len(fields) >= 2:
                body_start = index + 1
                break
            continue
        if len(fields) >= 2:
            break

    body = _strip_quote_markers("\n".join(lines[body_start:]))
    return QuotedMessage(
        from_=fields.get("from_"),
        sent=fields.get("sent"),
        to=fields.get("to"),
        subject=fields.get("subject"),
        body=body,
    )


def _strip_quote_markers(text: str) -> str:
    lines = [re.sub(r"^[ \t]*>+[ \t]?", "", line) for line in text.split("\n")]
    return "\n".join(lines).strip()
