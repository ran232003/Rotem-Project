"""A synthetic first-contact enquiry, to exercise template selection end to end.

The existing fixture is an ongoing matter with the firm's own replies in the
trail, which is exactly the case where no template applies. Testing that a
template is chosen and followed needs the opposite: a stranger writing in for the
first time, with no history.

Invented person, invented addresses. No client material.
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "out" / "enquiry.eml"

BODY = """שלום רב,

שמי דנה לוי ואני אזרחית ישראלית. בן זוגי, אנדריי, הוא אזרח אוקראינה ואנחנו
נשואים משנת 2021. הוא נמצא בישראל כרגע באשרת תייר שפגה לפני שבועיים.

אנחנו רוצים להסדיר את המעמד שלו בישראל. פנינו בעבר למשרד הפנים אבל קיבלנו
סירוב בשנת 2023, ומאז לא עשינו כלום.

מה אפשר לעשות במצב הזה? ואילו מסמכים נצטרך להביא?

תודה רבה,
דנה
"""


def main() -> int:
    message = EmailMessage()
    message["From"] = "Dana Levi <dana.levi@example.test>"
    message["To"] = "Rotem Fargon | Adv <rotem@law-fr.co.il>"
    message["Subject"] = "פנייה בנושא הסדרת מעמד לבן זוגי"
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain="example.test")
    message.set_content(BODY, subtype="plain", charset="utf-8")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(message.as_bytes())
    print(f"{OUT}  ({OUT.stat().st_size} bytes)")
    print("\nExpect: potential_client, status_spousal, and the status intake template.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
