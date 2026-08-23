"""Wording the firm does not use, checked against the draft the client reads.

The intake skill lists phrases to avoid, and the prompt passes that on. A prompt
is a request, though, and this is the class of rule a machine can settle by
looking at the text, so it is settled here instead.

Hebrew makes the matching less trivial than it looks. Attached prefixes mean a
banned word appears inside a longer one, which plain substring matching handles
correctly. Negation is the opposite problem: "בוודאות" as an assurance is exactly
what the firm forbids, while "לא ניתן לקבוע בוודאות" is the hedging it insists
on, and a checker that cannot tell them apart would train the reviewer to ignore
it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from rotem_agent.config import CONFIG_DIR, read_yaml

# Vowel points and cantillation. Present in quoted scripture and in the odd
# copied certificate, absent from anything typed in an office.
_NIQQUD = re.compile(r"[\u0591-\u05C7]")
_BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})

DEFAULT_NEGATION_WINDOW = 40


@dataclass(frozen=True)
class Forbidden:
    phrase: str
    severity: str = "warning"
    why: str = ""
    unless_negated: bool = False


@dataclass(frozen=True)
class PhrasePolicy:
    phrases: list[Forbidden] = field(default_factory=list)
    negators: list[str] = field(default_factory=list)
    negation_window: int = DEFAULT_NEGATION_WINDOW
    source: str = ""

    def check(self, text: str) -> list[tuple[Forbidden, str]]:
        """Every banned phrase present, with the fragment it was found in.

        The fragment goes to the reviewer because "this draft says מובטח" is not
        actionable on its own; the sentence around it is.
        """
        haystack = normalise(text)
        if not haystack:
            return []

        found: list[tuple[Forbidden, str]] = []
        for entry in self.phrases:
            needle = normalise(entry.phrase)
            if not needle:
                continue
            for match in re.finditer(re.escape(needle), haystack):
                if entry.unless_negated and self._negated(haystack, match.start()):
                    continue
                found.append((entry, _fragment(haystack, match.start(), len(needle))))
                break  # One report per phrase; the reviewer reads the draft anyway.
        return found

    def _negated(self, haystack: str, position: int) -> bool:
        window = _clause_before(haystack, position, self.negation_window)
        return any(
            _contains_word(window, normalise(negator))
            for negator in self.negators
            if negator.strip()
        )


def normalise(text: str) -> str:
    """Fold away everything that changes how a phrase looks but not what it says.

    A single newline becomes a space, because a phrase broken across a line wrap
    is still the phrase. A blank line is kept, because that is a paragraph break
    no phrase spans, and it is the only line ending that can be trusted to end a
    clause.
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFC", text).translate(_QUOTES)
    folded = _BIDI.sub("", folded)
    folded = _NIQQUD.sub("", folded)
    folded = re.sub(r"[^\S\n]*\n\s*\n\s*", "\n", folded)
    return re.sub(r"[^\S\n]+|(?<!\n)\n(?!\n)", " ", folded).strip()


def load_policy(path: Path | None = None) -> PhrasePolicy:
    """Never raises. A missing or broken list must not stop the agent drafting."""
    target = path or CONFIG_DIR / "forbidden_phrases.yaml"
    try:
        data = read_yaml(target)
    except Exception:  # noqa: BLE001 - a bad phrase list must not stop a draft
        return PhrasePolicy(source=f"{target} (unreadable)")
    if not isinstance(data, dict):
        return PhrasePolicy(source=f"{target} (not a mapping)")

    entries: list[Forbidden] = []
    for item in data.get("phrases") or []:
        if isinstance(item, str):
            entries.append(Forbidden(phrase=item))
            continue
        if not isinstance(item, dict):
            continue
        phrase = str(item.get("phrase", "")).strip()
        if not phrase:
            continue
        severity = str(item.get("severity", "warning")).strip().lower()
        entries.append(
            Forbidden(
                phrase=phrase,
                severity=severity if severity in ("problem", "warning") else "warning",
                why=str(item.get("why", "")).strip(),
                unless_negated=bool(item.get("unless_negated")),
            )
        )

    try:
        window = int(data.get("negation_window") or DEFAULT_NEGATION_WINDOW)
    except (TypeError, ValueError):
        window = DEFAULT_NEGATION_WINDOW

    return PhrasePolicy(
        phrases=entries,
        negators=[str(n).strip() for n in (data.get("negators") or []) if str(n).strip()],
        negation_window=max(0, window),
        source=str(target),
    )


_CLAUSE_BREAK = re.compile(r"[,;:.!?\u05be\u2013\u2014()\[\]\n]")


def _clause_before(haystack: str, position: int, window: int) -> str:
    """The text between the nearest clause break and the phrase.

    A negator only negates what follows it in the same breath. Reading across a
    comma makes "אין מה לדאוג, הבקשה תאושר בוודאות" look like hedged prose, when
    the certainty there is asserted rather than denied. Failing that way is the
    dangerous direction: it excuses an assurance instead of querying a caveat.
    """
    start = max(0, position - window)
    fragment = haystack[start:position]
    breaks = list(_CLAUSE_BREAK.finditer(fragment))
    return fragment[breaks[-1].end() :] if breaks else fragment


# Hebrew has no casing and no apostrophes to lean on, and a bare substring
# search for the negator לא finds it inside מלא, which would quietly excuse an
# assurance. A negator may only be preceded by a break or by one of the
# conjunctions that legitimately attach to it, as in ולא and שאין.
_ATTACHABLE_PREFIXES = "וש"


def _contains_word(window: str, negator: str) -> bool:
    if not negator:
        return False
    for match in re.finditer(re.escape(negator), window):
        before = window[match.start() - 1] if match.start() else ""
        if before and before not in _ATTACHABLE_PREFIXES and _is_hebrew_letter(before):
            continue
        after_index = match.end()
        after = window[after_index] if after_index < len(window) else ""
        if after and _is_hebrew_letter(after):
            continue
        return True
    return False


def _is_hebrew_letter(char: str) -> bool:
    return "\u05d0" <= char <= "\u05ea"


def _fragment(haystack: str, start: int, length: int, span: int = 45) -> str:
    left = max(0, start - span)
    right = min(len(haystack), start + length + span)
    piece = haystack[left:right]
    return ("…" if left > 0 else "") + piece + ("…" if right < len(haystack) else "")
