"""Survey a folder of real messages: structure, voice, and phrase-check calibration.

Three questions, all of which need real correspondence to answer.

Does the parser cope? Every message here was produced by a real client, mail
client and signature block, which is a harder test than any fixture.

What does the firm's voice actually look like? The voice reference was written
from a single thread. Nine give openings, closings and hedges with counts behind
them.

And does the new phrase check agree with the lawyer? If Rotem's own sent mail
trips the forbidden-phrase list, the list is wrong, not the mail. That is the
calibration this tool exists for, and it is worth more than any invented test.

Prints aggregates and short fragments only. Nothing is written to the repository.

    python -m tools.survey_corpus "C:\\path\\to\\folder"
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from rotem_agent.config import load_boilerplate, load_firm
from rotem_agent.mailparse.parser import parse_eml
from rotem_agent.phrases import load_policy

# Openers and closers are the two places a house style is most visible.
OPENERS = [
    "שלום רב",
    "שלום",
    "בהמשך לשיחתנו",
    "בהמשך לפנייתך",
    "בהמשך למייל",
    "תודה על",
    "קיבלתי את",
    "קיבלנו את",
    "היי",
    "בוקר טוב",
    "ערב טוב",
]
CLOSERS = [
    "בכבוד רב",
    "בברכה",
    "בהצלחה",
    "לרשותך",
    "לרשותכם",
    "אני כאן לכל שאלה",
    "נשמח לעמוד לרשותך",
    "תודה",
    "יום טוב",
    "שבת שלום",
]
HEDGES = [
    "אינה מחייבת",
    "אין באמור",
    "שיקול דעת",
    "אין לצאת",
    "בכתב",
    "יתואם בנפרד",
    "אין באפשרותנו",
    "ייתכן",
    "עשוי",
    "יש להביא בחשבון",
    "מומלץ",
    "אנו ממתינים",
    "טרם",
    "כפוף ל",
    "לא ניתן להתחייב",
]
FIRST_PERSON_PLURAL = ["אנו", "אנחנו", "הגשנו", "נעדכן", "נמתין", "בדקנו", "פנינו", "נפעל"]


_REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w.-]+\.\w+"), "[מייל]"),
    (re.compile(r"(?:\+?972|0)(?:[-\s]?\d){8,9}"), "[טלפון]"),
    (re.compile(r"\b\d{9}\b"), "[ת.ז.]"),
    (re.compile(r"\bhttps?://\S+"), "[קישור]"),
    # A greeting is the one place a client's name is reliably positioned.
    (re.compile(r"(שלום רב|שלום|היי)[ \t]+([^\n,،.]{1,40})"), r"\1 [שם]"),
]


def redact(text: str) -> str:
    """Enough to keep names, numbers and addresses out of a transcript.

    Not a guarantee. A name in the middle of a sentence survives this, so the
    output is still privileged and belongs nowhere near the repository.
    """
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def main(folder: Path, dump: bool = False) -> int:
    firm = load_firm()
    boilerplate = load_boilerplate()
    policy = load_policy()

    files = sorted(folder.glob("*.eml"))
    if not files:
        print(f"no .eml files in {folder}")
        return 1

    openers, closers, hedges, plural = Counter(), Counter(), Counter(), Counter()
    phrase_hits: list[tuple[str, str, str, str]] = []
    lengths: list[int] = []
    firm_messages = 0

    print(f"{len(files)} message(s) in {folder}\n")
    for path in files:
        try:
            email = parse_eml(path, boilerplate)
        except Exception as exc:  # noqa: BLE001 - a survey must not stop on one file
            print(f"  PARSE FAILED  {path.name}: {exc}")
            continue

        sender = email.from_.email if email.from_ else "?"
        print(
            f"  new {len(email.latest_body):>5}ch  trail {len(email.quoted_chain):>2}  "
            f"attach {len(email.real_attachments)}(+{len(email.signature_assets)} sig)  "
            f"from {sender[:34]:34}  {email.subject[:40]}"
        )

        # Only text the firm itself wrote is evidence of the firm's voice.
        for block in _firm_written(email, firm):
            if dump:
                print("  " + "-" * 70)
                for line in redact(block).splitlines():
                    print(f"  | {line}")
                print("  " + "-" * 70)
            firm_messages += 1
            lengths.append(len(block))
            _tally(block, OPENERS, openers, head=180)
            _tally(block, CLOSERS, closers, tail=220)
            _tally(block, HEDGES, hedges)
            _tally(block, FIRST_PERSON_PLURAL, plural)
            for entry, fragment in policy.check(block):
                phrase_hits.append((path.name, entry.phrase, entry.severity, fragment))

    print(f"\n{firm_messages} block(s) of firm-written text")
    if lengths:
        lengths.sort()
        print(
            f"length: median {lengths[len(lengths) // 2]} chars, "
            f"shortest {lengths[0]}, longest {lengths[-1]}"
        )

    _report("Openings", openers)
    _report("Closings", closers)
    _report("Hedges and limits", hedges)
    _report("First person plural", plural)

    print("\n=== Phrase-check calibration ===")
    if not phrase_hits:
        print("  No forbidden phrase appears in the firm's own sent mail.")
        print("  The list agrees with the lawyer's actual practice.")
    else:
        print("  The firm's own mail trips the list. Each of these is either a")
        print("  phrase to remove from the list, or one to keep with severity lowered:\n")
        for name, phrase, severity, fragment in phrase_hits:
            print(f"  [{severity}] {phrase}  ({name[:40]})")
            print(f"      {fragment}")
    return 0


def _firm_written(email, firm) -> list[str]:
    """The new body when the firm sent it, plus any firm message in the trail."""
    blocks: list[str] = []
    if email.latest_body.strip() and email.from_ and _is_firm(email.from_.email, firm):
        blocks.append(email.latest_body)
    for message in email.quoted_chain:
        if not message.body.strip():
            continue
        addresses = re.findall(r"[\w.+-]+@[\w.-]+", message.from_ or "")
        if any(_is_firm(a, firm) for a in addresses) or (
            firm.lawyer_name and firm.lawyer_name in (message.from_ or "")
        ):
            blocks.append(message.body)
    return blocks


def _is_firm(address: str, firm) -> bool:
    return bool(address) and firm.is_own_address(address)


def _tally(
    text: str, needles: list[str], counter: Counter, head: int = 0, tail: int = 0
) -> None:
    region = text[:head] if head else text[-tail:] if tail else text
    for needle in needles:
        if needle in region:
            counter[needle] += 1


def _report(title: str, counter: Counter) -> None:
    print(f"\n=== {title} ===")
    if not counter:
        print("  none found")
        return
    for needle, count in counter.most_common():
        print(f"  {count:>3}  {needle}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dump"]
    raise SystemExit(main(Path(args[0] if args else "."), dump="--dump" in sys.argv))
