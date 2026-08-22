from rotem_agent.mailparse.quotes import parse_quoted_chain, split_quotes


def test_splits_on_english_outlook_header():
    text = (
        "Thanks, please advise.\n\n"
        "From: Rotem <rotem@law-fr.co.il>\nSent: Thursday\nSubject: x\n\nOld body"
    )
    latest, trail = split_quotes(text)
    assert latest == "Thanks, please advise."
    assert "Old body" in trail


def test_splits_on_hebrew_outlook_header():
    text = "תודה רבה,\n\nמאת: רותם פרגון\nנשלח: יום חמישי\nנושא: עדכון\n\nגוף ההודעה הקודמת"
    latest, trail = split_quotes(text)
    assert latest == "תודה רבה,"
    assert "גוף ההודעה הקודמת" in trail


def test_splits_on_underscore_divider():
    text = "New content here\n" + "_" * 32 + "\nDisclaimer text"
    latest, trail = split_quotes(text)
    assert latest == "New content here"
    assert "Disclaimer" in trail


def test_no_marker_returns_empty_trail():
    latest, trail = split_quotes("Just a short note.")
    assert latest == "Just a short note."
    assert trail == ""


def test_chain_drops_preamble_before_first_attribution():
    trail = (
        "Confidentiality notice nobody reads.\n\n"
        "From: Rotem Fargon <rotem@law-fr.co.il>\n"
        "Sent: Thursday, June 18, 2026 5:51 PM\n"
        "To: David Cohen <david@example-relocation.test>\n"
        "Subject: summary\n\n"
        "The actual previous message."
    )
    chain = parse_quoted_chain(trail)
    assert len(chain) == 1
    assert chain[0].from_ == "Rotem Fargon <rotem@law-fr.co.il>"
    assert chain[0].subject == "summary"
    assert chain[0].body == "The actual previous message."
    assert "Confidentiality" not in chain[0].body


def test_chain_splits_multiple_quoted_messages():
    trail = (
        "From: A <a@x.com>\nSent: Monday\n\nFirst reply.\n\n"
        "מאת: B <b@x.com>\nנשלח: יום ראשון\n\nההודעה המקורית."
    )
    chain = parse_quoted_chain(trail)
    assert len(chain) == 2
    assert chain[0].body == "First reply."
    assert chain[1].body == "ההודעה המקורית."
