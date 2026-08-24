"""Saying something when there is no console to say it in.

The stop icon deliberately runs without a window. A .bat console runs under the
OEM codepage, where Hebrew arrives as rubbish, and a message the lawyer cannot
read is worse than no message: she would be left guessing whether the agent
stopped. A Windows message box is Unicode all the way down, needs no dependency,
and is the one piece of UI certain to look normal on her machine.

Anywhere a box cannot be shown — another platform, a session with no desktop —
this falls back to printing, so nothing depends on the dialog existing.
"""

from __future__ import annotations

import os
import sys

TITLE = "סוכן הטיוטות"

_MB_OK = 0x0
_MB_YESNO = 0x4
_MB_ICONERROR = 0x10
_MB_ICONQUESTION = 0x20
_MB_ICONINFORMATION = 0x40
_MB_SETFOREGROUND = 0x10000
_IDYES = 6


def tell(text: str, *, title: str = TITLE, error: bool = False) -> None:
    icon = _MB_ICONERROR if error else _MB_ICONINFORMATION
    if _box(text, title, _MB_OK | icon) is None:
        print(text, file=sys.stderr if error else sys.stdout)


def ask(text: str, *, title: str = TITLE) -> bool:
    """A yes/no question.

    No is the answer when nobody can be asked. The only caller uses this to
    confirm killing the agent outright, so silence must not be taken for consent.
    """
    return _box(text, title, _MB_YESNO | _MB_ICONQUESTION) == _IDYES


def _box(text: str, title: str, flags: int) -> int | None:
    """The button pressed, or None if no box could be shown."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        return int(
            ctypes.windll.user32.MessageBoxW(
                None, str(text), str(title), flags | _MB_SETFOREGROUND
            )
        )
    except Exception:
        return None
