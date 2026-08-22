from __future__ import annotations

import re

# Vowel points and cantillation. Legal PDFs occasionally carry them and they
# would otherwise split one word into several distinct terms.
_NIQQUD = re.compile(r"[\u0591-\u05C7]")

# Hebrew or Latin letters, optionally continuing through a slash, so that visa
# classes such as ב/1 and א/5 survive as single terms. Splitting them would make
# every visa class match every other one.
_TOKEN = re.compile(
    r"[A-Za-z\u05D0-\u05EA]+(?:[/\u05F3'][0-9A-Za-z\u05D0-\u05EA]+)*"
    r"|\d+(?:[./]\d+)*"
)

_FINALS = str.maketrans({"ם": "מ", "ן": "נ", "ץ": "צ", "ף": "פ", "ך": "כ"})

# Single-letter attached prefixes: and/the/in/to/from/that/as. Stripping these is
# lossy, so the stripped form is indexed alongside the surface form rather than
# replacing it, which keeps an exact match scoring higher than an inflected one.
_PREFIXES = "והבלמשכ"
_MIN_STEM = 3


def normalize(text: str) -> str:
    text = _NIQQUD.sub("", text)
    return text.replace("\u05f4", '"').replace("\u05f3", "'")


def tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN.finditer(normalize(text))]


def variants(token: str) -> list[str]:
    """The surface form plus the forms an inflected mention could take."""
    forms = [token]
    folded = token.translate(_FINALS)
    if folded != token:
        forms.append(folded)
    # Never strip a prefix from a visa class such as ב/1: the leading letter is
    # the class itself, not a preposition.
    if "/" not in token and len(token) > _MIN_STEM and token[0] in _PREFIXES:
        stem = token[1:]
        forms.append(stem)
        stem_folded = stem.translate(_FINALS)
        if stem_folded != stem:
            forms.append(stem_folded)
    return forms


def index_terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in tokens(text):
        terms.extend(variants(token))
    return terms
