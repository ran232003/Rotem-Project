"""Generate the synthetic Outlook thread used by the test suite.

The tests must not contain real client data. This builds a message that mirrors
the structure of a genuine Exchange Online thread the firm received, with every
person and case detail fabricated:

- RFC 2047 base64 Hebrew subject and a Hebrew display name
- multipart/related wrapping multipart/alternative, both text parts base64
- an inline PNG with a Content-ID, referenced by cid: in the body, which is the
  signature logo that must never be treated as an attachment
- an English Outlook attribution block quoting a Hebrew message from the firm
- a numbered action request plus numbered questions, and an explicit statement
  of how many answers are expected
- a phone block and an English confidentiality notice to strip

Run: python tools/make_fixture.py
"""

from __future__ import annotations

import base64
from email.header import Header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic_thread.eml"

# 1x1 transparent PNG, standing in for a signature logo.
LOGO = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/58BAAX/Af9x/xUAAAAASUVORK5CYII="
)

INCOMING = """רותם שלום,

למרינה יש דרכון עד 09.2028, בכל מקרה היא תצטרך לצאת לחדש דרכון עד אז.

כתבת לנו: " בשלב זה נמשיך לפעול לקבלת מענה מהרשות ביחס לבקשת אשרת החוזר." – כמה זמן כדאי לנו להמתין? חודש? חודשיים? חצי שנה?

  1.  אנא הגבילי המתנה זו בזמן מעשי.

  1.  מה נכון?
  2.  מה היתרונות בסגירת בקשת המקלט?
  3.  האם בקשת המקלט חוסמת את הבקשה לאשרת חוזר?

ענו לנו בבקשה על 4 השאלות

תודה

David Cohen
Example Relocation Ltd.
Tel: +972-3-0000000
Fax: +972-3-0000001

________________________________
The information in this electronic message and any attachments is intended for
one or more specific individuals or entities, and may contain privileged
information. If you are not the intended recipient, any distribution of this
communication is strictly prohibited.

From: Rotem Fargon <rotem@law-fr.co.il>
Sent: Thursday, June 18, 2026 5:51 PM
To: David Cohen <david@example-relocation.test>
Cc: Rotem Fargon <rotem@law-fr.co.il>
Subject: סיכום שיחתנו בעניין אשרת חוזר והמשך ההליך של מרינה


דוד ומרינה שלום, בהמשך לשיחתנו כעת,

אבקש לסכם בקצרה את עיקרי הדברים.

כיום מרינה מחזיקה ברישיון מסוג ב/1 מכוח ההליך להסדרת מעמד על בסיס הקשר הזוגי, ובמקביל בקשת המקלט שלה עדיין פתוחה וטרם הוכרעה.

חשוב להבהיר כי עצם הגשת הבקשה אינה מחייבת את הרשות לאשר אותה, ואין לצאת מישראל לפני קבלת אישור מפורש ובכתב.

לכן חשוב להבין כי סגירת בקשת המקלט אינה מבטיחה אישור אשרת חוזר או כניסה חזרה לישראל. באחריותכם לעמוד בדרישות ובמועדים שייקבעו בעקבותיה. (45 ימים)

בברכת סופ"ש נעים ושקט

רותם פרגון, משרד עורכי דין.
[cid:logo@example]
"""

HTML = """<html dir="rtl"><body>
<p>רותם שלום,</p>
<ol><li>אנא הגבילי המתנה זו בזמן מעשי.</li></ol>
<ol><li>מה נכון?</li><li>מה היתרונות בסגירת בקשת המקלט?</li>
<li>האם בקשת המקלט חוסמת את הבקשה לאשרת חוזר?</li></ol>
<p>ענו לנו בבקשה על 4 השאלות</p>
<img src="cid:logo@example">
</body></html>
"""


SUBJECT = "RE: סיכום שיחתנו בעניין אשרת חוזר והמשך ההליך של מרינה"


def build() -> MIMEMultipart:
    # Outlook ships multipart/related at the top, wrapping multipart/alternative,
    # with the signature image as a sibling of the body. Built explicitly because
    # EmailMessage cannot express that nesting.
    root = MIMEMultipart("related", type="multipart/alternative")

    hebrew_display = Header("רותם פרגון | משרד עורכי דין", "utf-8").encode()
    root["From"] = "David Cohen <david@example-relocation.test>"
    root["To"] = (
        f"Rotem Fargon | Adv <rotem@law-fr.co.il>, {hebrew_display} <office3@law-fr.co.il>"
    )
    root["Cc"] = "yael.klein@example.test"
    root["Subject"] = Header(SUBJECT, "utf-8")
    root["Date"] = formatdate(localtime=False)
    root["Message-ID"] = make_msgid(domain="example-relocation.test")
    root["In-Reply-To"] = "<prior-message@law-fr.co.il>"
    root["References"] = "<prior-message@law-fr.co.il>"
    root["Thread-Topic"] = Header(SUBJECT, "utf-8")
    root["X-MS-Has-Attach"] = "yes"

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(INCOMING, "plain", "utf-8"))
    alternative.attach(MIMEText(HTML, "html", "utf-8"))
    root.attach(alternative)

    logo = MIMEImage(LOGO, "png")
    logo.add_header("Content-ID", "<logo@example>")
    logo.add_header("Content-Disposition", "inline", filename="image001.png")
    root.attach(logo)
    return root


def main() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_bytes(build().as_bytes())
    print(f"Wrote {FIXTURE} ({FIXTURE.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
