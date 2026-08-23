from rotem_agent.mailparse.quotes import parse_quoted_chain, split_quotes, strip_bidi

# The exact shape Gmail produced in a real Hebrew reply, invisible bidi controls
# and all. The name and address are separate runs, so the attribution wraps over
# three lines and the confirming "כתב:" never appears on the opening line.
GMAIL_HEBREW_REPLY = (
    'שלום עו"ד רותם,\n\n'
    "יש לי כמה שאלות חדשות:\n\n"
    "האם המכתב מהמעסיק החדש מספיק טוב?\n\n"
    "מחכה לאישורכם, מריאן\n\n"
    "\u202bבתאריך שבת, 22 באוג׳ 2026 ב-12:31 מאת \u202aRotem Fargon\u202c\u200f <\u202a\n"
    "rotem@law-fr.co.il\n"
    "\u202c\u200f>:\u202c\n\n"
    "שלום מריאן,\n\n"
    "1. משמעות המכתב: המכתב מבוסס על דיווח שנתקבל ברשות.\n\n"
    "2. מצב אשרת העבודה: האשרה עדיין לא בוטלה.\n"
)


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


def test_splits_a_real_gmail_hebrew_reply():
    """The client writes from Gmail, so this is the case that actually matters."""
    latest, trail = split_quotes(GMAIL_HEBREW_REPLY)

    assert latest.startswith('שלום עו"ד רותם,')
    assert latest.endswith("מחכה לאישורכם, מריאן")
    # Our own previous reply must not be mistaken for newly written text.
    assert "משמעות המכתב" not in latest
    assert "משמעות המכתב" in trail


def test_the_quoted_previous_reply_does_not_inflate_the_new_body():
    """Left unsplit, every round of a thread costs more and pollutes coverage."""
    latest, _ = split_quotes(GMAIL_HEBREW_REPLY)
    assert len(latest) < len(GMAIL_HEBREW_REPLY) / 2


def test_bidi_controls_are_removed_from_the_body():
    latest, _ = split_quotes("\u202bשלום,\u202c\n\nתודה")
    assert "\u202b" not in latest and "\u202c" not in latest


def test_a_date_in_prose_is_not_a_quote_boundary():
    """"בתאריך" opens both an attribution and an ordinary Hebrew sentence."""
    text = "בתאריך 5 במאי קיבלתי מכתב מאת הרשות ולא הבנתי אותו.\n\nאשמח לעזרה."
    latest, trail = split_quotes(text)
    assert trail == ""
    assert "אשמח לעזרה" in latest


def test_gmail_english_attribution_may_wrap():
    text = (
        "Thanks for the update.\n\n"
        "On Sat, 22 Aug 2026 at 12:31, Rotem Fargon\n"
        "<rotem@law-fr.co.il> wrote:\n\n"
        "Previous message body."
    )
    latest, trail = split_quotes(text)
    assert latest == "Thanks for the update."
    assert "Previous message body." in trail


def test_strip_bidi_leaves_ordinary_text_alone():
    assert strip_bidi("שלום mixed 123") == "שלום mixed 123"


def test_chain_splits_multiple_quoted_messages():
    trail = (
        "From: A <a@x.com>\nSent: Monday\n\nFirst reply.\n\n"
        "מאת: B <b@x.com>\nנשלח: יום ראשון\n\nההודעה המקורית."
    )
    chain = parse_quoted_chain(trail)
    assert len(chain) == 2
    assert chain[0].body == "First reply."
    assert chain[1].body == "ההודעה המקורית."
