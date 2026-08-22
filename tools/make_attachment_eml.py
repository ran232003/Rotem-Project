"""Build a test .eml with a readable attachment.

Lets the attachment path be exercised end to end without waiting for real mail
or involving Outlook. Written to out/, which is git-ignored.

    python tools/make_attachment_eml.py
    python -m rotem_agent.cli draft out/attachment_test.eml
"""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

# Resolved from this file rather than imported, so the script runs standalone
# from any working directory without the package on sys.path.
OUT_DIR = Path(__file__).resolve().parents[1] / "out"

SENDER = "mike232003@gmail.com"
RECIPIENT = "rotem@law-fr.co.il"

BODY = """רותם שלום,

מצורף המכתב שקיבלנו מרשות האוכלוסין.

1. מה מספר התיק שלנו ומה המועד האחרון להשלמת המסמכים?
2. כמה זמן צפוי לקחת הטיפול בבקשה?

אנא ענו על שתי השאלות.

תודה,
מייק
"""

ATTACHMENT = """רשות האוכלוסין וההגירה — מסמך בדיקה סינתטי

מספר תיק: 771904
תאריך המכתב: 03.08.2026

הבקשה נקלטה ונמצאת בטיפול. יש להשלים את המסמכים החסרים עד ליום 17.09.2026.
זמן הטיפול הממוצע בבקשות מסוג זה בלשכה זו הוא 30 ימי עבודה ממועד השלמת
כל המסמכים.

לא ניתן להאריך את המועד להשלמת המסמכים אלא מטעמים מיוחדים שיירשמו.
"""


def main() -> None:
    message = EmailMessage()
    message["Subject"] = "שאלות בעניין המכתב מרשות האוכלוסין"
    message["From"] = f"Mike Test <{SENDER}>"
    message["To"] = f"Rotem Fargon | Adv <{RECIPIENT}>"
    message["Date"] = "Sat, 22 Aug 2026 10:40:00 +0300"
    message["Message-ID"] = "<attachment-test@example.test>"
    message.set_content(BODY)
    message.add_attachment(
        ATTACHMENT.encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename="ministry-notice.txt",
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = Path(OUT_DIR) / "attachment_test.eml"
    target.write_bytes(message.as_bytes())
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
