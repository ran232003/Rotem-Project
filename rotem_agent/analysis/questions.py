"""Working out everything the sender expects an answer to.

"Asks" covers questions and explicit requests alike. The distinction matters:
the sample thread's first numbered item is "אנא הגבילי המתנה זו בזמן מעשי",
a demand rather than a question, and a reply that ignores it has failed just as
badly as one that skips a question mark.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from typing import Any

from rotem_agent.llm.base import LlmClient

_HEBREW_NUMBERS = {
    "אחת": 1,
    "שתי": 2,
    "שתיים": 2,
    "שלוש": 3,
    "שלושת": 3,
    "ארבע": 4,
    "ארבעת": 4,
    "חמש": 5,
    "חמישה": 5,
    "שש": 6,
    "שבע": 7,
    "שמונה": 8,
    "תשע": 9,
    "עשר": 10,
}

_EXPECTED_COUNT = re.compile(
    r"(?:על\s+)?(\d{1,2}|" + "|".join(_HEBREW_NUMBERS) + r")\s+(?:ה)?שאלות"
)
_QUESTION_SENTENCE = re.compile(r"([^\n?]{3,300}\?)")
_LIST_ITEM = re.compile(r"^[ \t]*(?:\d{1,2}[.)]|[-*•])[ \t]+(.{3,300})$", re.MULTILINE)
_IMPERATIVE = re.compile(r"^[ \t]*(?:אנא|נא|אבקש|בבקשה|עני|ענו|השיבי|השיבו)\b.{3,300}$", re.MULTILINE)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "asks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": ["question", "request"]},
                },
                "required": ["text", "kind"],
            },
        }
    },
    "required": ["asks"],
}

_SYSTEM = """אתה עוזר משפטי המנתח דואר אלקטרוני נכנס למשרד עורכי דין בישראל.
המשימה: לזהות כל דבר שהשולח מצפה לקבל עליו מענה.

כללים:
- כלול שאלות מפורשות וגם בקשות לפעולה (למשל "אנא הגבילי את ההמתנה בזמן").
- אל תכלול ברכות, חתימות, כותרות משפטיות או טקסט מצוטט מהודעות קודמות.
- שמור על הניסוח המקורי בעברית, בקצרה.
- kind = "question" לשאלה, kind = "request" לבקשה לפעולה.
- אל תמציא פריטים שאינם בהודעה."""


@dataclass(frozen=True)
class Ask:
    text: str
    kind: str


@dataclass(frozen=True)
class AskSet:
    asks: list[Ask]
    expected_count: int | None
    heuristic_count: int
    heuristic_only: list[Ask] = dataclasses_field(default_factory=list)

    @property
    def count_mismatch(self) -> bool:
        return self.expected_count is not None and self.expected_count != len(self.asks)


def detect_expected_count(text: str) -> int | None:
    """Catch a sender stating how many answers they want, e.g. "ענו לנו על 4 השאלות".

    Cheap and unusually valuable, because HTML ordered lists collapse to a
    repeated "1." in the plain-text alternative, so the visible numbering
    cannot be trusted.
    """
    match = _EXPECTED_COUNT.search(text)
    if not match:
        return None
    token = match.group(1)
    return int(token) if token.isdigit() else _HEBREW_NUMBERS.get(token)


def heuristic_asks(text: str) -> list[Ask]:
    found: list[Ask] = []
    for match in _QUESTION_SENTENCE.finditer(text):
        found.append(Ask(text=match.group(1).strip(), kind="question"))
    for pattern in (_LIST_ITEM, _IMPERATIVE):
        for match in pattern.finditer(text):
            item = (match.group(1) if pattern is _LIST_ITEM else match.group(0)).strip()
            found.append(Ask(text=item, kind="question" if "?" in item else "request"))
    return _dedupe(found)


def extract_asks(text: str, llm: LlmClient | None = None) -> AskSet:
    """Regexes recall aggressively; the model decides what is actually an ask.

    The two passes are deliberately not merged. The regexes over-split a single
    question into fragments ("כמה זמן כדאי לנו להמתין? חודש? חצי שנה?" is one
    ask, not four), so unioning them would inflate the list and make the
    coverage check fire on every email. Instead the model's list is
    authoritative and anything the regexes found but the model dropped is
    reported separately for review.
    """
    heuristic = heuristic_asks(text)
    expected = detect_expected_count(text)

    if llm is None:
        return AskSet(asks=heuristic, expected_count=expected, heuristic_count=len(heuristic))

    response = llm.complete_json(system=_SYSTEM, user=text, schema=_SCHEMA, temperature=0.0)
    model_asks = _dedupe(
        [
            Ask(
                text=str(item.get("text", "")).strip(),
                kind="request" if item.get("kind") == "request" else "question",
            )
            for item in response.data.get("asks", [])
            if str(item.get("text", "")).strip()
        ]
    )

    return AskSet(
        asks=model_asks,
        expected_count=expected,
        heuristic_count=len(heuristic),
        heuristic_only=[a for a in heuristic if not _covered_by(a, model_asks)],
    )


def _covered_by(candidate: Ask, asks: list[Ask]) -> bool:
    tokens = _tokens(candidate.text)
    if not tokens:
        return True
    return any(len(tokens & _tokens(ask.text)) / len(tokens) >= 0.6 for ask in asks if ask.text)


def _tokens(text: str) -> set[str]:
    return {word for word in re.split(r"[^\w\u0590-\u05FF]+", text) if len(word) > 1}


def _dedupe(asks: list[Ask]) -> list[Ask]:
    seen: dict[str, Ask] = {}
    for ask in asks:
        key = _normalise(ask.text)
        if not key:
            continue
        existing = seen.get(key)
        if existing is None:
            seen[key] = ask
        elif existing.kind == "request" and ask.kind == "question":
            seen[key] = ask
    return list(seen.values())


def _normalise(text: str) -> str:
    return re.sub(r"[\s\"'׳״.,;:?!()\[\]-]+", "", text)
