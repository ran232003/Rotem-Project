"""Parser tests run against a synthetic fixture, never against real client mail.

The fixture mirrors the structure of a genuine Exchange Online thread the firm
received, with all people and case details fabricated. Regenerate it with
`python tools/make_fixture.py`. Real correspondence stays in samples/, which is
git-ignored, and is used only for manual runs.
"""

from pathlib import Path

import pytest

from rotem_agent.analysis.questions import detect_expected_count, heuristic_asks
from rotem_agent.config import load_firm
from rotem_agent.mailparse.parser import parse_eml

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_thread.eml"


@pytest.fixture(scope="module")
def email():
    if not FIXTURE.exists():
        pytest.fail(f"Fixture missing. Run: python tools/make_fixture.py ({FIXTURE})")
    return parse_eml(FIXTURE)


def test_decodes_rfc2047_hebrew_subject(email):
    assert "אשרת חוזר" in email.subject


def test_decodes_rfc2047_hebrew_display_name(email):
    assert any("משרד עורכי דין" in party.name for party in email.to)


def test_mail_addressed_to_two_firm_mailboxes(email):
    """Both mailboxes receive it, which is why deduplication is needed."""
    firm = load_firm()
    assert sum(firm.is_own_address(p.email) for p in email.to) == 2


def test_client_is_not_the_sender(email):
    """The agency sends, the client is only on CC. Sender-keyed folders misfile this."""
    firm = load_firm()
    assert not firm.is_own_address(email.from_.email)
    assert email.cc and not any(firm.is_own_address(p.email) for p in email.cc)
    assert email.from_.email not in {p.email for p in email.cc}


def test_inline_signature_logo_is_not_treated_as_an_attachment(email):
    assert email.real_attachments == []
    assert [a.filename for a in email.signature_assets] == ["image001.png"]


def test_quoted_chain_recovers_the_firms_previous_reply(email):
    firm = load_firm()
    assert email.quoted_chain
    previous = email.quoted_chain[0]
    assert any(firm.is_own_address(a) for a in [previous.from_.split("<")[-1].strip(">")])
    assert "אשרת חוזר" in previous.body


def test_boilerplate_disclaimer_and_phone_block_are_stripped(email):
    assert "intended recipient" not in email.latest_body
    assert "Tel:" not in email.latest_body
    assert "[cid:" not in email.latest_body


def test_sender_name_survives_boilerplate_stripping(email):
    """Who wrote it is useful; their fax number is not."""
    assert "David Cohen" in email.latest_body


def test_detects_the_explicitly_requested_answer_count(email):
    assert detect_expected_count(email.latest_body) == 4


def test_finds_both_questions_and_action_requests(email):
    asks = heuristic_asks(email.latest_body)
    assert any("הגבילי" in ask.text for ask in asks)
    assert any(ask.kind == "question" for ask in asks)


def test_context_text_includes_the_quoted_history(email):
    context = email.context_text()
    assert "45" in context, "grounding checks rely on quoted history being in scope"
