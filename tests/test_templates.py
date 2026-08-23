from __future__ import annotations

import pytest

from rotem_agent.templates import (
    Template,
    as_prompt_section,
    choose,
    load_templates,
)


@pytest.fixture(scope="module")
def library() -> list[Template]:
    """The real library, so a bad frontmatter edit fails the suite."""
    return load_templates()


def _pick(library, text, **kwargs):
    return choose(library, text, **kwargs)


# ------------------------------------------------------------- the real library


def test_the_library_loads(library):
    assert len(library) >= 9
    assert all(t.body.strip() for t in library)


def test_every_template_declares_a_genre(library):
    unfinished = [t.slug for t in library if not t.genre]
    assert not unfinished, f"frontmatter still says TODO: {unfinished}"


def test_no_template_teaches_a_signoff(library):
    """Outlook appends the signature, so an exemplar must not end with one."""
    offenders = [
        t.slug
        for t in library
        if any(
            line.strip().rstrip(",") in ("בברכה", "בכבוד רב")
            for line in t.body.splitlines()
        )
    ]
    assert not offenders, f"these still carry a sign-off: {offenders}"


def test_exactly_one_fallback_exists(library):
    assert sum(1 for t in library if t.fallback) == 1


def test_every_supplied_template_defers_answers(library):
    """All nine are intake or acknowledgement, so none answers a legal question."""
    assert all(t.defers_answers for t in library)


def test_an_explicit_flag_overrides_the_genre():
    answering = Template(slug="t", title="t", body="גוף", genre="intake_questions", defers=False)
    assert not answering.defers_answers
    withholding = Template(slug="t", title="t", body="גוף", genre="substantive", defers=True)
    assert withholding.defers_answers


def test_an_unknown_genre_does_not_defer_by_default():
    assert not Template(slug="t", title="t", body="גוף", genre="substantive").defers_answers


def test_placeholders_are_detected(library):
    onboarding = next(t for t in library if t.slug.startswith("תיק-המעמד"))
    assert "[תאריך]" in onboarding.placeholders


# ----------------------------------------------------------------- selection


@pytest.mark.parametrize(
    "text,client_type,category,expected_start",
    [
        (
            "קיבלתי זימון וסירוב כניסה בשדה התעופה, הטיסה מחר",
            "existing_client",
            "entry_refusal",
            "פנייתך-התקבלה",
        ),
        (
            "אני ובן זוגי רוצים להסדיר את המעמד שלו בישראל",
            "potential_client",
            "status_spousal",
            "המשך-בדיקת-פנייתך-בנושא",
        ),
        (
            "תוכלו לשלוח לי את רשימת המסמכים הנדרשים?",
            "potential_client",
            None,
            "המשך-בדיקת-פנייתך",
        ),
        (
            "אנחנו חברה קבלנית ומעוניינים בהעסקת עובדים זרים והקצאה",
            "potential_client",
            "foreign_expert",
            "מידע-ראשוני",
        ),
        (
            "לא קיבלתי מענה כבר שבועיים ואין התקדמות בתיק",
            "existing_client",
            None,
            "התייחסות-לפנייתך",
        ),
        (
            "אפשר לשוחח עם עורכת הדין בטלפון?",
            "existing_client",
            "admin",
            "קבלת-פנייתך",
        ),
    ],
)
def test_selection(library, text, client_type, category, expected_start):
    choice = _pick(library, text, client_type=client_type, category=category)
    assert choice.ok
    assert choice.template.slug.startswith(expected_start), choice.template.slug


def test_the_category_splits_the_two_onboarding_templates(library):
    """Both are genre 'onboarding'; only the category tells them apart."""
    text = "חתמנו על הסכם ההתקשרות, מה השלב הבא?"
    individual = _pick(library, text, client_type="existing_client", category="status_spousal")
    corporate = _pick(library, text, client_type="existing_client", category="foreign_expert")
    assert individual.template.slug != corporate.template.slug
    assert "עובדים-זרים" in corporate.template.slug


def test_an_unrecognised_email_falls_back(library):
    choice = _pick(library, "תודה רבה", client_type="potential_client")
    assert choice.ok
    assert choice.template.fallback
    assert "no signal matched" in choice.reason


def test_an_existing_client_is_not_offered_a_first_contact_template(library):
    """The fallback is scoped to a potential client, so this must find nothing."""
    choice = _pick(library, "תודה רבה", client_type="existing_client", category="asylum")
    assert not choice.ok
    assert "no template" in choice.reason


def test_selection_survives_an_empty_library():
    assert not choose([], "כל טקסט", client_type="potential_client").ok


def test_an_ongoing_matter_does_not_get_the_first_contact_template(library):
    """The regression this guard exists for.

    A referring agency writes from an address no matter.yaml lists, so the caller
    guesses "potential client". The first-contact template then tells the model to
    decline advising until intake, and a substantive reply to a live matter turns
    into a refusal to answer. Drafting overrides the guess when the firm has
    already replied in the thread; here that override is asserted directly.
    """
    text = "בהמשך לשיחתנו בעניין אשרת חוזר, כמה זמן כדאי להמתין למענה הרשות?"
    as_new = choose(library, text, client_type="potential_client", category="reentry_visa")
    as_existing = choose(library, text, client_type="existing_client", category="reentry_visa")

    assert as_new.template is not None and as_new.template.fallback
    assert as_existing.template is None or not as_existing.template.fallback


# ------------------------------------------------- Hebrew morphology in signals


def test_a_signal_reaches_an_attached_possessive():
    """זוג must fire on זוגי, which is how a client writes about their partner."""
    template = Template(slug="t", title="t", body="גוף", signals=("זוג",))
    assert choose([template], "בן זוגי נמצא בחו\"ל").ok


def test_a_signal_reaches_a_definite_article():
    template = Template(slug="t", title="t", body="גוף", signals=("מעמד",))
    assert choose([template], "להסדיר את המעמד").ok


def test_a_multi_word_signal_needs_all_its_words():
    template = Template(slug="t", title="t", body="גוף", signals=("רשימת מסמכים",))
    assert choose([template], "שלחו לי את רשימת המסמכים").ok
    assert not choose([template], "שלחו לי מסמכים").ok


def test_a_short_signal_is_not_matched_as_a_prefix():
    """צו must not fire on צוות, or every staffing email becomes an emergency."""
    template = Template(slug="t", title="t", body="גוף", signals=("צו",))
    assert not choose([template], "הצוות שלכם מעולה").ok
    assert choose([template], "קיבלתי צו").ok


# ------------------------------------------------------------------ the prompt


def test_the_prompt_section_carries_the_body_and_the_rules(library):
    choice = _pick(
        library,
        "קיבלתי זימון וסירוב כניסה בשדה התעופה",
        client_type="existing_client",
        category="entry_refusal",
    )
    section = as_prompt_section(choice)
    assert "אין להשיב לרשות" in section  # the template's own instruction survived
    assert "Never leave a bracket in the draft" in section
    assert "Drop any question the incoming email has already answered" in section


def test_no_choice_produces_no_section():
    assert as_prompt_section(choose([], "טקסט")) == ""


def test_an_oversized_template_is_truncated(tmp_path):
    (tmp_path / "big.md").write_text(
        "---\ntitle: big\ngenre: x\n---\n" + "א" * 20_000, encoding="utf-8"
    )
    loaded = load_templates(tmp_path)
    assert len(loaded[0].body) <= 6000


def test_a_malformed_template_does_not_lose_the_others(tmp_path):
    (tmp_path / "good.md").write_text(
        "---\ntitle: good\ngenre: g\nsignals:\n  - מעמד\n---\nגוף ההודעה", encoding="utf-8"
    )
    (tmp_path / "bad.md").write_text("---\n: : broken: [\n---\nגוף", encoding="utf-8")
    (tmp_path / "empty.md").write_text("---\ntitle: e\n---\n\n", encoding="utf-8")
    loaded = load_templates(tmp_path)
    assert [t.slug for t in loaded] == ["good"]


def test_a_missing_directory_is_not_fatal(tmp_path):
    assert load_templates(tmp_path / "absent") == []


def test_todo_frontmatter_is_treated_as_unset(tmp_path):
    (tmp_path / "stub.md").write_text(
        "---\ntitle: stub\ngenre: TODO\nclient_type: TODO\n---\nגוף", encoding="utf-8"
    )
    template = load_templates(tmp_path)[0]
    assert template.client_types == frozenset()
    assert template.suits("anyone", "any_category")
