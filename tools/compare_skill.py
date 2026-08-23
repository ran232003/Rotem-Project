"""Compare a skill folder against ours, ignoring formatting.

A skill re-exported by another tool comes back reflowed, relinked and refenced,
so a line diff is almost entirely noise. What matters is whether any rule
changed, so this normalises whitespace and markdown decoration and compares the
sentences that remain.
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

OURS = Path(__file__).resolve().parents[1] / "skills"

_FRONTMATTER = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_DECORATION = re.compile(r"[`*_#>|]|```\w*")


def sentences(text: str) -> list[str]:
    text = _FRONTMATTER.sub("", text)
    text = _LINK.sub(r"\1", text)          # keep the label, drop the target
    text = _DECORATION.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.:!?])\s+|\s*\n\s*", text)
    return [p.strip(" -") for p in parts if len(p.strip(" -")) > 3]


def compare(ours: Path, theirs: Path) -> bool:
    a = sentences(ours.read_text(encoding="utf-8")) if ours.exists() else []
    b = sentences(theirs.read_text(encoding="utf-8")) if theirs.exists() else []

    only_theirs = [s for s in b if s not in a]
    only_ours = [s for s in a if s not in b]

    # Near-matches are reflow or a reworded clause, not a new rule.
    reworded: list[tuple[str, str]] = []
    genuinely_new: list[str] = []
    for item in only_theirs:
        match = difflib.get_close_matches(item, only_ours, n=1, cutoff=0.75)
        if match:
            reworded.append((match[0], item))
        else:
            genuinely_new.append(item)
    dropped = [
        s for s in only_ours if not difflib.get_close_matches(s, only_theirs, n=1, cutoff=0.75)
    ]

    name = theirs.name if theirs.exists() else ours.name
    if not genuinely_new and not dropped:
        print(f"== {name}: same rules ({len(reworded)} reworded/reflowed)")
        return False

    print(f"== {name}")
    for item in genuinely_new:
        print(f"  THEIRS ONLY: {item}")
    for item in dropped:
        print(f"  OURS ONLY  : {item}")
    return True


def main(their_root: Path, skill: str) -> int:
    ours = OURS / skill
    files = sorted({p.name for p in (ours / "references").glob("*.md")} |
                   {p.name for p in (their_root / "references").glob("*.md")})

    changed = compare(ours / "SKILL.md", their_root / "SKILL.md")
    for name in files:
        changed |= compare(ours / "references" / name, their_root / "references" / name)

    extra = [
        p for p in their_root.rglob("*")
        if p.is_file() and p.name != "SKILL.md" and p.parent.name != "references"
    ]
    if extra:
        print("\nFiles in theirs with no counterpart here:")
        for path in extra:
            print(f"  {path.relative_to(their_root)}  ({path.stat().st_size} B)")
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "legal-client-email-intake"))
