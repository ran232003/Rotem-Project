"""Unit tests for the guardrails, which must not depend on a live model call."""

from rotem_agent.analysis.questions import Ask, AskSet
from rotem_agent.config import Firm
from rotem_agent.drafting.composer import (
    Answer,
    InternalNote,
    _enforce_approval,
    _has_signature,
    _ungrounded_numbers,
    _verify,
)
from rotem_agent.mailparse.parser import ParsedEmail

FIRM = Firm(
    lawyer_name="רותם פרגון",
    firm_name="רותם פרגון, משרד עורכי דין",
    addresses=["rotem@law-fr.co.il"],
)


def _email(body: str, subject: str = "נושא") -> ParsedEmail:
    return ParsedEmail(
        message_id=None,
        in_reply_to=None,
        references=[],
        subject=subject,
        date=None,
        from_=None,
        to=[],
        cc=[],
        latest_body=body,
        quoted_chain=[],
    )


def _note(**overrides) -> InternalNote:
    base = dict(
        client_type="existing_client",
        matter_category="reentry_visa",
        urgency="routine",
        confidence="high",
        approval="lawyer_review",
        is_holding_reply=False,
        next_action="follow up",
    )
    return InternalNote(**{**base, **overrides})


def _asks(*texts: str) -> AskSet:
    return AskSet(
        asks=[Ask(text=t, kind="question") for t in texts],
        expected_count=None,
        heuristic_count=len(texts),
    )


class _Excerpt:
    def __init__(self, citation: str, text: str) -> None:
        self.citation = citation
        self.text = text


def test_substantive_advice_to_a_potential_client_is_flagged():
    """Detailed advice before an engagement letter creates an expectation of representation."""
    _, warnings = _verify(
        "שלום רב, לפי המכתב עליך להשלים את הרישום עד למועד הנקוב שם ולהגיש השגה.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(client_type="potential_client"),
        "advisory",
        FIRM,
    )
    assert any("engagement letter" in w for w in warnings)


def test_a_holding_reply_to_a_potential_client_is_not_flagged():
    _, warnings = _verify(
        "שלום רב, קיבלנו את פנייתך ונחזור אליך בהקדם לאחר בדיקה מסודרת של העניין.",
        [Answer(ask="a", answered=False, excerpt="")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(client_type="potential_client", is_holding_reply=True),
        "advisory",
        FIRM,
    )
    assert not any("engagement letter" in w for w in warnings)


def test_an_existing_client_is_not_flagged_for_engagement():
    _, warnings = _verify(
        "שלום רב, לפי המכתב עליך להשלים את הרישום עד למועד הנקוב שם ולהגיש השגה.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(client_type="existing_client"),
        "advisory",
        FIRM,
    )
    assert not any("engagement letter" in w for w in warnings)


def test_a_fabricated_document_citation_is_a_problem():
    """The model must not claim to have read a file it was never shown."""
    problems, _ = _verify(
        "שלום רב, בהתאם למסמכים בתיק הבקשה הוגשה כנדרש ואנו ממתינים למענה הרשות.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(sources_used=["ministry-letter.pdf#2"]),
        "advisory",
        FIRM,
        [_Excerpt("passport.pdf#0", "דרכון")],
    )
    assert any("never supplied" in p for p in problems)


def test_a_real_document_citation_passes():
    problems, _ = _verify(
        "שלום רב, בהתאם למסמכים בתיק הבקשה הוגשה כנדרש ואנו ממתינים למענה הרשות.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(sources_used=["passport.pdf#0"]),
        "advisory",
        FIRM,
        [_Excerpt("passport.pdf#0", "דרכון")],
    )
    assert not any("never supplied" in p for p in problems)


def test_a_number_from_a_client_document_counts_as_grounded():
    """Otherwise every real file number in the client's own papers gets flagged."""
    _, warnings = _verify(
        "שלום רב, מספר התיק שלך הוא 458822 ואנו ממתינים למענה הרשות בעניין זה.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "advisory",
        FIRM,
        [_Excerpt("ministry.pdf#1", "מספר תיק 458822 נפתח בלשכה")],
    )
    assert not any("do not appear" in w for w in warnings)


def test_ungrounded_numbers_ignores_list_markers_and_placeholders():
    draft = "1. נמתין 45 ימים.\n2. נעדכן עד [[להשלמה: 99]].\n3. תוך 7 שנים."
    assert _ungrounded_numbers(draft, "המתנה של 45 ימים") == ["7"]


def test_grounded_numbers_produce_no_finding():
    assert _ungrounded_numbers("תוקף עד 09.2028", "דרכון עד 09.2028") == []


def test_signature_detected_only_near_the_end():
    assert _has_signature("שלום\n\nבברכה,\nרותם פרגון", FIRM)
    assert not _has_signature("רותם פרגון ביקשה\n\nא\nב\nג\nד", FIRM)


def test_escalation_forces_principal_review():
    approval, warning = _enforce_approval(_note(escalation_triggers=["detention"]))
    assert approval == "principal_lawyer_review"
    assert "detention" in warning


def test_may_send_is_always_overridden():
    approval, warning = _enforce_approval(_note(approval="may_send"))
    assert approval == "lawyer_review"
    assert "overridden" in warning


def test_unverified_proposition_without_holding_reply_is_a_problem():
    problems, _ = _verify(
        "עמדתנו היא שהרשות מחויבת לאשר את הבקשה במלואה ובאופן מיידי.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("האם הרשות מחויבת לאשר?"),
        _note(unverified_propositions=["האם הרשות מחויבת"]),
        "strict",
        FIRM,
    )
    assert any("without a holding reply" in p for p in problems)


def test_same_proposition_is_allowed_under_advisory():
    problems, _ = _verify(
        "עמדתנו היא שהרשות אינה מחויבת לאשר את הבקשה, וההחלטה בשיקול דעתה.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("האם הרשות מחויבת לאשר את הבקשה שהגשנו?"),
        _note(unverified_propositions=["האם הרשות מחויבת"]),
        "advisory",
        FIRM,
    )
    assert problems == []


def test_holding_reply_downgrades_unanswered_asks_to_warnings():
    problems, warnings = _verify(
        "קיבלנו את פנייתך ונחזור אליך עם מענה מפורט בהקדם, לאחר בדיקת הנהלים.",
        [Answer(ask="a", answered=False, excerpt="")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(is_holding_reply=True, confidence="low"),
        "strict",
        FIRM,
    )
    assert problems == []
    assert any("deferred" in w for w in warnings)


def test_internal_note_leakage_is_a_problem():
    problems, _ = _verify(
        "INTERNAL — DO NOT SEND\nClient type: existing_client\nשלום רב, קיבלנו את פנייתך.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "strict",
        FIRM,
    )
    assert any("leaked" in p for p in problems)


def test_language_mismatch_is_a_problem():
    problems, _ = _verify(
        "Dear Ben, we received your message and will revert with a detailed reply shortly.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו ועוד מילים"),
        _note(),
        "strict",
        FIRM,
    )
    assert any("Language mismatch" in p for p in problems)
