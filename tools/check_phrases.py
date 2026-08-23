"""Run the forbidden-phrase list over sample Hebrew and show what it decides.

Editing config/forbidden_phrases.yaml changes what the agent refuses to send, and
the failure mode of a phrase list is a false positive that trains the reviewer to
ignore it. This prints the verdict on a handful of sentences so an edit can be
checked before it reaches a client draft.

    python -m tools.check_phrases                 # the built-in samples
    python -m tools.check_phrases "some text"     # your own
"""

from __future__ import annotations

import sys

from rotem_agent.phrases import load_policy

SAMPLES = [
    ("assurance", "שלום אנה,\n\nאין מה לדאוג, הבקשה תאושר בוודאות בתוך שבועיים."),
    (
        "hedged",
        "שלום אנה,\n\nהגשנו את הבקשה. לא ניתן לקבוע בוודאות מה תחליט הרשות,\n"
        "ועצם ההגשה אינה מחייבת אותה לאשר.",
    ),
    ("reproach", "שלום אנה,\n\nכפי שכבר הסברנו, ההליך אורך זמן."),
    ("disclaimed", "אין באמור לעיל חוות דעת משפטית."),
    ("promise", "שלום אנה,\n\nבהמשך לפנייתך, אין בעיה להגיש את הבקשה החודש."),
    ("inflected", "האישור מובטחת לך."),
    ("negator inside a word", "התיק מלא ואנו קובעים בוודאות שהכל יאושר."),
]


def main(argv: list[str]) -> int:
    policy = load_policy()
    print(f"{len(policy.phrases)} phrase(s) from {policy.source}")
    print(f"negators: {', '.join(policy.negators)}  window: {policy.negation_window}\n")

    samples = [("argument", " ".join(argv))] if argv else SAMPLES
    worst = 0
    for label, text in samples:
        hits = policy.check(text)
        if not hits:
            print(f"  clean    {label}")
            continue
        for entry, fragment in hits:
            worst = max(worst, 2 if entry.severity == "problem" else 1)
            print(f"  {entry.severity:8} {label}: {entry.phrase}")
            print(f"           {fragment}")
    return 0 if not argv else worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
