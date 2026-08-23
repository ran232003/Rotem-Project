from __future__ import annotations

import pytest

from rotem_agent.phrases import Forbidden, PhrasePolicy, load_policy, normalise


@pytest.fixture(scope="module")
def policy() -> PhrasePolicy:
    """The real config, so an edit that breaks the list fails the suite."""
    return load_policy()


def _phrases(policy: PhrasePolicy, text: str) -> list[str]:
    return [entry.phrase for entry, _ in policy.check(text)]


# ------------------------------------------------------- the firm's actual list

def test_the_configured_list_loads(policy):
    assert policy.phrases, "forbidden_phrases.yaml produced nothing"
    assert "אין מה לדאוג" in {e.phrase for e in policy.phrases}
    assert policy.negators


def test_an_assurance_is_caught_and_held_back(policy):
    hits = policy.check("שלום אנה, אין מה לדאוג, הבקשה תאושר.")
    assert [e.phrase for e, _ in hits] == ["אין מה לדאוג"]
    assert hits[0][0].severity == "problem"
    assert "אין מה לדאוג" in hits[0][1]


def test_a_promise_is_caught_through_its_inflection(policy):
    """מובטחת and יובטח are the same promise; a substring match gets both."""
    assert "מובטח" in _phrases(policy, "האישור מובטחת לך בתוך שבועיים.")
    assert "מובטח" in _phrases(policy, "התוצאה ומובטח שהרשות תאשר.")


def test_a_reproach_is_reported_without_holding_the_draft(policy):
    hits = policy.check("כפי שכבר הסברנו, ההליך אורך זמן.")
    assert [e.severity for e, _ in hits] == ["warning"]


def test_a_clean_hebrew_draft_passes(policy):
    text = (
        "שלום אנה,\n\nבהמשך לפנייתך, הגשנו את הבקשה ביום 12.08.2026. "
        "עצם הגשת הבקשה אינה מחייבת את הרשות לאשר אותה.\n\nבכבוד רב,"
    )
    assert policy.check(text) == []


# --------------------------------------------------------------------- negation

def test_certainty_is_allowed_when_it_is_being_denied(policy):
    """'לא ניתן לקבוע בוודאות' is the hedging the firm requires, not a breach."""
    assert _phrases(policy, "לא ניתן לקבוע בוודאות מה תחליט הרשות.") == []


def test_certainty_asserted_is_still_caught(policy):
    assert "בוודאות" in _phrases(policy, "אנו יכולים לומר בוודאות שהבקשה תאושר.")


def test_a_negator_inside_another_word_does_not_excuse_an_assurance(policy):
    """מלא contains לא. Reading that as negation would silence the check."""
    assert "בוודאות" in _phrases(policy, "התיק מלא ואנו קובעים בוודאות שהכל יאושר.")


def test_a_prefixed_negator_still_negates(policy):
    assert _phrases(policy, "ולא ניתן לדעת בוודאות מה יוחלט.") == []


def test_a_legal_opinion_disclaimed_is_allowed(policy):
    assert _phrases(policy, "אין באמור לעיל חוות דעת משפטית.") == []


def test_a_preliminary_view_called_a_legal_opinion_is_flagged(policy):
    hits = policy.check("מצורפת חוות דעת משפטית בעניינך.")
    assert [e.phrase for e, _ in hits] == ["חוות דעת משפטית"]


def test_a_distant_negator_does_not_reach(policy):
    """A denial in an earlier clause must not excuse an assurance in this one."""
    text = "לא הגשנו את הבקשה בשלב זה, וכפי שנמסר לך בעבר בפגישה, התוצאה בוודאות חיובית."
    assert "בוודאות" in _phrases(policy, text)


def test_a_negator_in_the_previous_clause_does_not_negate(policy):
    """The comma matters: the certainty here is asserted, not denied."""
    hits = _phrases(policy, "אין מה לדאוג, הבקשה תאושר בוודאות בתוך שבועיים.")
    assert "בוודאות" in hits
    assert "אין מה לדאוג" in hits


def test_negation_survives_a_comma_free_clause(policy):
    assert _phrases(policy, "בשלב זה איננו יכולים לומר בוודאות מה יוחלט.") == []


def test_a_negator_in_a_previous_paragraph_does_not_negate(policy):
    assert "בוודאות" in _phrases(policy, "לא הגשנו עדיין.\n\nהתוצאה בוודאות חיובית")


def test_a_soft_wrap_does_not_end_the_clause(policy):
    """Hebrew drafts wrap mid-sentence, so one newline cannot be a clause break."""
    assert _phrases(policy, "לא ניתן לקבוע\nבוודאות מה יוחלט") == []


# ---------------------------------------------------------------- normalisation

def test_a_phrase_broken_across_a_line_wrap_is_still_found(policy):
    assert "אין מה לדאוג" in _phrases(policy, "שלום,\nאין מה\nלדאוג בכלל.")


def test_bidi_marks_and_vowel_points_do_not_hide_a_phrase(policy):
    assert "אין מה לדאוג" in _phrases(policy, "\u200fאֵין מה לדאוג\u200e")


def test_normalise_leaves_ordinary_text_intact():
    assert normalise("שלום  עולם") == "שלום עולם"
    assert normalise("") == ""


def test_curly_quotes_are_folded():
    assert normalise("\u201cמובטח\u201d") == '"מובטח"'


# -------------------------------------------------------------------- robustness

def test_a_missing_config_does_not_stop_drafting(tmp_path):
    broken = load_policy(tmp_path / "absent.yaml")
    assert broken.phrases == []
    assert broken.check("אין מה לדאוג") == []


def test_a_malformed_entry_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "phrases.yaml"
    path.write_text(
        "phrases:\n"
        "  - 12345\n"
        "  - phrase: ''\n"
        "  - phrase: מובטח\n"
        "    severity: nonsense\n"
        "negation_window: not-a-number\n",
        encoding="utf-8",
    )
    loaded = load_policy(path)
    assert [e.phrase for e in loaded.phrases] == ["מובטח"]
    # An unrecognised severity must not silently become a blocking problem.
    assert loaded.phrases[0].severity == "warning"
    assert loaded.negation_window == 40


def test_a_bare_string_entry_is_accepted(tmp_path):
    path = tmp_path / "phrases.yaml"
    path.write_text("phrases:\n  - אין בעיה\n", encoding="utf-8")
    assert load_policy(path).check("אין בעיה כלל")


def test_each_phrase_is_reported_once(tmp_path):
    policy = PhrasePolicy(phrases=[Forbidden(phrase="מובטח", severity="problem")])
    assert len(policy.check("מובטח, מובטח, ושוב מובטח")) == 1
