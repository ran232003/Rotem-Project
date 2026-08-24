"""Editing config/mailbox.yaml: the allowlist, and the mailbox it declares.

This file is the agent's only boundary on whose mail it will read, so it is
edited rather than rewritten: the comments and the layout are left alone and
only the line being changed is touched. A dashboard that quietly ate the
explanatory comments would make the file harder to trust for the person who has
to audit it later.

Two invariants hold whatever the caller asks for. The write is atomic, so a
crash mid-save cannot truncate the boundary to something wider than intended.
And the list is never emptied, because `load_mailbox_config` rejects an empty
list and a running watcher would then keep its previous list: the page would
show nobody while the agent carried on drafting. Stopping is what the switch is
for.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rotem_agent.config import CONFIG_DIR
from rotem_agent.logs import logger

MAILBOX_YAML = CONFIG_DIR / "mailbox.yaml"

# Deliberately not RFC 5322. This guards against a typo or a pasted display
# name reaching a file that decides what the agent may read, and anything
# stricter rejects addresses that exist.
_ADDRESS = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[A-Za-z]{2,}$")

_KEY = re.compile(r"^allowed_senders\s*:(?P<inline>.*)$", re.IGNORECASE)
_ITEM = re.compile(r"^(\s*)-\s*(.+?)\s*$")
# Case-sensitive, unlike the list above: YAML keys are, so a `Mailbox:` line is
# not what `load_mailbox_config` reads and must not be reported as though it were.
_MAILBOX = re.compile(r"^mailbox\s*:(?P<value>.*)$")


class SenderError(RuntimeError):
    """Something the user should be told, in words they can act on."""


@dataclass(frozen=True)
class Change:
    address: str
    senders: list[str]


def normalise(address: str) -> str:
    return (address or "").strip().strip("<>").strip()


def validate(address: str) -> str:
    clean = normalise(address)
    if not clean:
        raise SenderError("לא הוזנה כתובת.")
    if not _ADDRESS.match(clean):
        raise SenderError(f"{clean} אינה כתובת דוא״ל תקינה.")
    return clean


def read_mailbox(path: Path | None = None) -> str:
    """The single address the `mailbox:` line declares, or empty."""
    for line in _lines(path or MAILBOX_YAML):
        match = _MAILBOX.match(line)
        if match:
            return normalise(match.group("value").split("#")[0])
    return ""


def set_mailbox(address: str, allowed: list[str] | None, path: Path | None = None) -> str:
    """Replace the declared mailbox, refusing anything Outlook is not signed in to.

    There is only ever one, so this changes the value rather than adding to a
    list. `allowed` is the set of addresses Outlook actually has: the field is
    a claim about reality checked by `doctor`, and letting the page write a
    claim that is already known to be false would only produce a startup warning
    nobody connects to the edit that caused it.

    Pass None for `allowed` to skip the check; an empty list means Outlook could
    not be asked, which is refused rather than treated as "nothing is valid".
    """
    target = path or MAILBOX_YAML
    clean = validate(address)

    if allowed is not None:
        if not allowed:
            raise SenderError(
                "לא ניתן לבדוק מול אאוטלוק עכשיו. יש לוודא שאאוטלוק פתוח ולנסות שוב."
            )
        if not any(clean.lower() == known.strip().lower() for known in allowed):
            joined = ", ".join(allowed)
            raise SenderError(
                f"אאוטלוק במחשב הזה אינו מחובר ל־{clean}. "
                f"הכתובות הזמינות: {joined}."
            )

    lines = _lines(target)
    for index, line in enumerate(lines):
        match = _MAILBOX.match(line)
        if match:
            value = match.group("value")
            note = value[value.index("#") :].strip() if "#" in value else ""
            lines[index] = f"mailbox: {clean}" + (f"  {note}" if note else "")
            break
    else:
        raise SenderError(f"לא נמצאה שורת mailbox בקובץ {target}")

    _replace(target, "\n".join(lines) + "\n", _newline(target))
    logger().info("mailbox: set to %s", clean)
    return clean


def start_date(path: Path | None = None):
    """The configured floor on how far back the agent may look, or None.

    Read through the same loader the watcher uses, so the page cannot disagree
    with the agent about what the file says.
    """
    from rotem_agent.outlook.com import load_mailbox_config

    try:
        return load_mailbox_config(path or MAILBOX_YAML).start_date
    except Exception as exc:
        raise SenderError(str(exc)) from exc


def read(path: Path | None = None) -> list[str]:
    """The addresses currently listed, in file order."""
    lines = _lines(path or MAILBOX_YAML)
    block = _block(lines)
    if block is None:
        return []

    if block.inline:
        found = [normalise(part) for part in block.inline.strip().strip("[]").split(",")]
    else:
        found = [
            normalise(match.group(2))
            for match in (_ITEM.match(line) for line in lines[block.start + 1 : block.end])
            if match
        ]
    return [address for address in found if address]


def add(address: str, path: Path | None = None) -> Change:
    target = path or MAILBOX_YAML
    clean = validate(address)
    current = read(target)
    if any(clean.lower() == existing.lower() for existing in current):
        raise SenderError(f"{clean} כבר נמצאת ברשימה.")
    updated = current + [clean]
    _write(target, updated)
    logger().info("allowlist: added %s (%d total)", clean, len(updated))
    return Change(address=clean, senders=updated)


def remove(address: str, path: Path | None = None) -> Change:
    target = path or MAILBOX_YAML
    clean = normalise(address)
    current = read(target)
    updated = [existing for existing in current if existing.lower() != clean.lower()]
    if len(updated) == len(current):
        raise SenderError(f"{clean} אינה ברשימה.")
    if not updated:
        raise SenderError(
            "לא ניתן להסיר את הכתובת האחרונה. כדי שהסוכן יפסיק לענות, יש לכבות אותו."
        )
    _write(target, updated)
    logger().info("allowlist: removed %s (%d left)", clean, len(updated))
    return Change(address=clean, senders=updated)


# --------------------------------------------------------------------- internals


def _lines(path: Path) -> list[str]:
    return _text(path).splitlines()


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SenderError(f"קובץ ההגדרות חסר: {path}") from exc
    except OSError as exc:
        raise SenderError(f"לא ניתן לקרוא את קובץ ההגדרות: {exc}") from exc


def _newline(path: Path) -> str:
    """Whatever the file already uses, so an edit is not also a line-ending change.

    She opens this in Notepad on Windows, and a diff of every line because the
    dashboard imposed Unix endings is noise in a file meant to be auditable.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return os.linesep
    return "\r\n" if raw.count(b"\r\n") >= raw.count(b"\n") - raw.count(b"\r\n") else "\n"


@dataclass(frozen=True)
class _Block:
    """Where the list lives in the file."""

    start: int  # the `allowed_senders:` line
    end: int  # one past its last item
    indent: str
    inline: str  # anything on the key line, as in `allowed_senders: []`


def _block(lines: list[str]) -> _Block | None:
    """The list ends at the first line that is neither an item nor blank.

    That is how a following top-level key such as `mailbox:`, or a trailing
    comment, survives an edit untouched.
    """
    for index, line in enumerate(lines):
        key = _KEY.match(line)
        if not key:
            continue
        inline = key.group("inline").strip()
        end = index + 1
        indent = "  "
        while end < len(lines):
            item = _ITEM.match(lines[end])
            if item:
                indent = item.group(1) or "  "
                end += 1
                continue
            if not lines[end].strip():
                # A blank line is part of the block only if an item follows;
                # otherwise it belongs to whatever comes next.
                lookahead = end
                while lookahead < len(lines) and not lines[lookahead].strip():
                    lookahead += 1
                if lookahead < len(lines) and _ITEM.match(lines[lookahead]):
                    end = lookahead
                    continue
            break
        return _Block(start=index, end=end, indent=indent, inline=inline)
    return None


def _write(path: Path, senders: list[str]) -> None:
    lines = _lines(path)
    block = _block(lines)
    if block is None:
        raise SenderError(f"לא נמצא allowed_senders בקובץ {path}")

    # An inline `allowed_senders: []` has to lose its value, or the items below
    # it would be appended to a key that already has one and the file would stop
    # parsing.
    key_line = "allowed_senders:" if block.inline else lines[block.start]

    rebuilt = (
        lines[: block.start]
        + [key_line]
        + [f"{block.indent}- {address}" for address in senders]
        + lines[block.end :]
    )
    _replace(path, "\n".join(rebuilt) + "\n", _newline(path))


def _replace(path: Path, text: str, newline: str = "\n") -> None:
    """Write via a temporary file in the same directory, then rename over.

    The watcher re-reads this file every pass, so a partial write is a window in
    which the boundary is whatever happened to be flushed.
    """
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline=newline,
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
