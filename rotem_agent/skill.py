"""Loading the firm's intake skill and its reference documents.

The skill is the authority on workflow, escalation, voice and source
discipline. It lives as markdown so the firm can edit it without touching code,
and the loader assembles it into one prompt section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from rotem_agent.config import PROJECT_ROOT, ConfigError

SKILLS_DIR = PROJECT_ROOT / "skills"
DEFAULT_SKILL = "legal-client-email-intake"

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Reference:
    """One reference document, optionally scoped to the matters it governs.

    A procedure that only bears on spousal-status files has no business in the
    prompt for an email about an invoice. It dilutes the instructions that do
    apply and pulls the reply toward its own subject.
    """

    title: str
    text: str
    applies_to: frozenset[str] = frozenset()

    def governs(self, category: str | None) -> bool:
        if not self.applies_to:
            return True
        # An unknown category means an unresolved matter, typically a first
        # enquiry from someone with no folder yet. Excluding a procedure there
        # would silently drop it from exactly the emails that open a case, so
        # dropping a reference requires positively knowing it does not apply.
        return category is None or category in self.applies_to


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    references: dict[str, Reference]

    def as_prompt_section(self, category: str | None = None) -> str:
        parts = [self.body.strip()]
        for title, reference in sorted(self.references.items()):
            if not reference.governs(category):
                continue
            parts.append(f"\n\n# Reference: {title}\n\n{reference.text.strip()}")
        return "".join(parts)


def load_skill(name: str = DEFAULT_SKILL, skills_dir: Path | None = None) -> Skill:
    root = (skills_dir or SKILLS_DIR) / name
    skill_file = root / "SKILL.md"
    if not skill_file.exists():
        raise ConfigError(f"Missing skill definition: {skill_file}")

    raw = skill_file.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if match:
        meta = yaml.safe_load(match.group(1)) or {}
        body = match.group(2)
    else:
        meta, body = {}, raw

    references = {}
    for path in sorted((root / "references").glob("*.md")):
        title = path.stem.replace("-", " ")
        references[title] = _load_reference(title, path)
    _check_references(body, root, references)

    return Skill(
        name=str(meta.get("name", name)),
        description=str(meta.get("description", "")),
        body=body,
        references=references,
    )


def _load_reference(title: str, path: Path) -> Reference:
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if not match:
        return Reference(title=title, text=raw)

    meta = yaml.safe_load(match.group(1)) or {}
    scope = meta.get("applies_to") or []
    if isinstance(scope, str):
        scope = [scope]
    return Reference(
        title=title,
        text=match.group(2),
        applies_to=frozenset(str(item).strip() for item in scope if str(item).strip()),
    )


def _check_references(body: str, root: Path, loaded: dict[str, Reference]) -> None:
    """A skill that points at a missing reference silently loses its rules."""
    cited = set(re.findall(r"references/([\w-]+\.md)", body))
    missing = sorted(name for name in cited if not (root / "references" / name).exists())
    if missing:
        raise ConfigError(
            f"Skill {root.name} cites reference files that do not exist: {', '.join(missing)}"
        )
    if not loaded:
        raise ConfigError(f"Skill {root.name} has no reference documents.")
