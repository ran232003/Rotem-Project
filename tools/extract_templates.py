"""Turn a folder of the firm's template messages into the template library.

Run once per batch Rotem sends. It writes one markdown file per message with a
frontmatter stub, which then needs editing by hand: only a person can say which
matter categories a template governs and which words in an incoming email should
select it.

Both sign-offs are stripped. The templates close with "בברכה, רותם פרגון ושות׳"
and Outlook then appends a second signature, so her sent mail signs twice. Drafts
omit the sign-off and let Outlook supply it, so the exemplars must not teach the
model to write one.

    python -m tools.extract_templates "C:\\path\\to\\folder" [--force]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from rotem_agent.config import load_boilerplate
from rotem_agent.mailparse.parser import parse_eml

OUT_DIR = Path(__file__).resolve().parents[1] / "templates"

# Her sign-off, her firm name and the appended Outlook signature. These arrive
# interleaved with blank lines and repeat twice, which is why they are matched
# per line from the end rather than as one block.
_CLOSING_LINE = re.compile(
    r"^\s*(?:בברכה|בכבוד רב|בברכת\s|תודה\s*$|רותם פרגון|משרד עורכי דין|עו[\"״']ד\b)",
)

# A closing line is always short. Requiring that stops a real sentence which
# happens to name the firm from being eaten off the end of a template.
MAX_CLOSING_LINE = 60

# Written by hand into each file afterwards; here only so the stub is valid.
STUB = """---
title: {title}
genre: TODO
client_type: TODO
applies_to: []
signals: []
---

"""


def slugify(subject: str) -> str:
    """A filename from a Hebrew subject, without transliterating it."""
    cleaned = re.sub(r"[^\w\u0590-\u05FF\s-]", "", subject).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned[:60] or "template"


def strip_signoff(text: str) -> str:
    lines = text.splitlines()
    while lines:
        last = lines[-1]
        if not last.strip():
            lines.pop()
            continue
        if len(last.strip()) <= MAX_CLOSING_LINE and _CLOSING_LINE.match(last):
            lines.pop()
            continue
        break
    return "\n".join(lines).rstrip()


def main(folder: Path, force: bool = False) -> int:
    files = sorted(folder.glob("*.eml"))
    if not files:
        print(f"no .eml files in {folder}")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    boilerplate = load_boilerplate()
    written = skipped = 0

    for path in files:
        email = parse_eml(path, boilerplate)
        body = strip_signoff(email.latest_body).strip()
        if not body:
            print(f"  empty after stripping, skipped: {path.name}")
            continue

        target = OUT_DIR / f"{slugify(email.subject)}.md"
        if target.exists() and not force:
            print(f"  exists, left alone: {target.name}")
            skipped += 1
            continue

        target.write_text(
            STUB.format(title=email.subject.replace('"', "'")) + body + "\n",
            encoding="utf-8",
        )
        print(f"  wrote {target.name}  ({len(body)} chars)")
        written += 1

    print(f"\n{written} written, {skipped} left alone, into {OUT_DIR}")
    if written:
        print("Now edit each file's frontmatter: genre, client_type, applies_to, signals.")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(main(Path(args[0]) if args else Path("."), "--force" in sys.argv))
