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


def test_forbidden_wording_reaches_the_draft_verification():
    """The phrase list has to fire through drafting, not only in its own unit."""
    problems, _ = _verify(
        "שלום רב, אין מה לדאוג, הבקשה שהגשנו תאושר על ידי הרשות בהקדם.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "advisory",
        FIRM,
    )
    assert any("אין מה לדאוג" in p for p in problems)


def test_a_properly_hedged_draft_is_not_caught_by_the_phrase_list():
    problems, warnings = _verify(
        "שלום רב, הגשנו את הבקשה. לא ניתן לקבוע בוודאות מה תחליט הרשות, "
        "ועצם ההגשה אינה מחייבת אותה לאשר.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "advisory",
        FIRM,
    )
    assert not any("Forbidden wording" in item for item in [*problems, *warnings])


def test_the_internal_note_may_say_what_the_draft_may_not():
    """An internal note should be free to record that nothing is guaranteed."""
    problems, _ = _verify(
        "שלום רב, הגשנו את הבקשה ואנו ממתינים למענה הרשות בעניין זה.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(next_action="להסביר ללקוח שאין מה לדאוג בשלב זה"),
        "advisory",
        FIRM,
    )
    assert not any("Forbidden wording" in p for p in problems)


def test_a_deferring_template_makes_unanswered_asks_expected():
    """The firm's intake templates withhold a route on purpose."""
    from rotem_agent.templates import Template

    problems, warnings = _verify(
        "שלום רב, תודה על פנייתך. כדי שנוכל לבחון את העניין נבקש להשיב על השאלות הבאות.",
        [Answer(ask="מה אפשר לעשות?", answered=False, excerpt="")],
        _asks("מה אפשר לעשות?"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "advisory",
        FIRM,
        template=Template(slug="t", title="t", body="גוף", genre="intake_questions"),
    )
    assert not any("reported unanswered" in p for p in problems)
    assert any("deferred" in w for w in warnings)


def test_without_a_template_an_unanswered_ask_is_still_a_problem():
    problems, _ = _verify(
        "שלום רב, תודה על פנייתך ואנו בודקים את העניין מול התיק בעניין זה.",
        [Answer(ask="מה אפשר לעשות?", answered=False, excerpt="")],
        _asks("מה אפשר לעשות?"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "advisory",
        FIRM,
    )
    assert any("reported unanswered" in p for p in problems)


def test_an_unfilled_template_slot_is_a_problem():
    """It reads as a finished sentence to everyone except the client."""
    problems, _ = _verify(
        "שלום רב, בהמשך לפנייתך נבקש להשלים את החומר עד יום [תאריך] כדי להתקדם.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "advisory",
        FIRM,
    )
    assert any("[תאריך]" in p for p in problems)


def test_the_agents_own_placeholder_is_not_a_template_slot():
    """[[...]] is the deliberate signal to the lawyer and must survive."""
    problems, _ = _verify(
        "שלום רב, נעדכן אותך עד [[להשלמה: תאריך מענה]] בהמשך לפנייתך בעניין זה.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "advisory",
        FIRM,
    )
    assert not any("slot" in p for p in problems)


def test_a_signoff_is_flagged_because_outlook_appends_one():
    _, warnings = _verify(
        "שלום רב, קיבלנו את פנייתך ואנו בודקים את החומר בעניין זה.\n\nבברכה,",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "advisory",
        FIRM,
    )
    assert any("sign off twice" in w for w in warnings)


def test_the_word_in_a_sentence_is_not_a_signoff():
    """'בברכה' occurs in ordinary Hebrew; only a line of its own is a sign-off."""
    _, warnings = _verify(
        "שלום רב, קיבלנו את פנייתך בברכה רבה ואנו בודקים את החומר בעניין זה.",
        [Answer(ask="a", answered=True, excerpt="x")],
        _asks("a"),
        _email("שאלה ארוכה דיה כדי לזהות שפה עברית בהודעה הנכנסת הזו"),
        _note(),
        "advisory",
        FIRM,
    )
    assert not any("sign off twice" in w for w in warnings)


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
