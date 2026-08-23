"""The firm's own reply templates, and choosing which one fits an email.

Rotem's intake correspondence is templated, and the templates are good: the
diagnostic questions are the product of practice, the limits paragraphs are
carefully drawn, and the structure is consistent enough to recognise on sight. A
model asked to invent a reply from a style description will produce something
plausible and slightly off, every time. Handing it the firm's actual template for
the genre and asking it to adapt is both cheaper and closer to what she would
have written.

Selection has to happen before the drafting call, because the template goes into
the prompt for that call. That rules out using the model's own classification and
leaves what is already known by then: whether the sender resolves to an open
matter, that matter's category, and the words in the email itself. In practice
that is enough, and where it is not, the fallback template is the firm's general
first-contact reply, which is a safe thing to be wrong with.

Nothing here is authoritative about the law. A template is a form of words, and
every guardrail applies to the draft that comes out of it unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from rotem_agent.retrieval.hebrew import index_terms, tokens, variants

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# A template is an exemplar, not a cap. Anything much longer than the longest of
# Rotem's own would be a sign the library has been fed something else.
MAX_TEMPLATE_CHARS = 6000

# Below this, a signal must match a whole word. It stops a two-letter signal such
# as צו from firing on every word that happens to begin with those letters.
MIN_STEM_MATCH = 3

# Genres whose whole purpose is to withhold a substantive answer until the case
# has been examined. A reply built from one of these leaves the client's "what can
# be done?" unanswered on purpose, and the coverage check has to know that.
#
# Every template the firm has supplied so far is of such a genre, because they
# are all intake and acknowledgement. A template that does answer questions
# should set `defers_answers: false` explicitly.
DEFERRING_GENRES = frozenset(
    {
        "initial_enquiry",
        "intake_questions",
        "document_list_declined",
        "urgent_acknowledgement",
        "complaint",
        "call_request",
        "onboarding",
    }
)


@dataclass(frozen=True)
class Template:
    slug: str
    title: str
    body: str
    genre: str = ""
    client_types: frozenset[str] = frozenset()
    applies_to: frozenset[str] = frozenset()
    signals: tuple[str, ...] = ()
    fallback: bool = False
    notes: str = ""
    defers: bool | None = None

    @property
    def defers_answers(self) -> bool:
        """Whether this template withholds substantive answers on purpose."""
        if self.defers is not None:
            return self.defers
        return self.genre in DEFERRING_GENRES

    @property
    def placeholders(self) -> list[str]:
        """The bracketed slots a drafter is expected to fill or remove."""
        return sorted(set(re.findall(r"\[[^\]\n]{1,60}\]", self.body)))

    def suits(self, client_type: str | None, category: str | None) -> bool:
        if self.client_types and client_type and client_type not in self.client_types:
            return False
        if self.applies_to and category and category not in self.applies_to:
            return False
        return True


@dataclass
class Choice:
    """Which template was chosen, and enough of the reasoning to audit it."""

    template: Template | None
    score: float = 0.0
    matched: list[str] = field(default_factory=list)
    reason: str = ""
    runners_up: list[tuple[str, float]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.template is not None


def load_templates(directory: Path | None = None) -> list[Template]:
    """Never raises. A malformed template must not stop the agent drafting."""
    target = directory or TEMPLATES_DIR
    if not target.is_dir():
        return []

    templates: list[Template] = []
    for path in sorted(target.glob("*.md")):
        try:
            template = _parse(path)
        except Exception:  # noqa: BLE001 - one bad file must not lose the rest
            continue
        if template is not None:
            templates.append(template)
    return templates


def choose(
    templates: list[Template],
    email_text: str,
    *,
    client_type: str | None = None,
    category: str | None = None,
) -> Choice:
    eligible = [t for t in templates if t.suits(client_type, category)]
    if not eligible:
        return Choice(template=None, reason="no template fits this client type and category")

    terms = set(index_terms(email_text))
    scored: list[tuple[float, Template, list[str]]] = []
    for template in eligible:
        matched = [signal for signal in template.signals if _signal_present(signal, terms)]
        score = float(len(matched))
        # Being scoped to this category breaks a tie between templates that both
        # matched, but it is never itself a reason to choose one. Otherwise an
        # email saying only "thank you" selects the border-emergency reply purely
        # because the matter happens to be an entry refusal.
        if score and category and category in template.applies_to:
            score += 0.5
        scored.append((score, template, matched))

    scored.sort(key=lambda item: (-item[0], item[1].slug))
    best_score, best, matched = scored[0]
    runners_up = [(t.slug, s) for s, t, _ in scored[1:4]]

    if best_score <= 0:
        fallback = next((t for t in eligible if t.fallback), None)
        if fallback is None:
            return Choice(
                template=None,
                reason="no template matched and no fallback is eligible",
                runners_up=runners_up,
            )
        return Choice(
            template=fallback,
            score=0.0,
            reason="no signal matched; using the general first-contact template",
            runners_up=runners_up,
        )

    reason = f"matched {len(matched)} signal(s)"
    if category and category in best.applies_to:
        reason += f" and is scoped to {category}"
    # A tie means the signals do not separate them, which is worth surfacing
    # rather than resolving silently by filename.
    if len(scored) > 1 and scored[1][0] == best_score:
        reason += f"; tied with {scored[1][1].slug}, chose by name"
    return Choice(template=best, score=best_score, matched=matched, reason=reason,
                  runners_up=runners_up)


def as_prompt_section(choice: Choice) -> str:
    """The chosen template, framed so the model adapts rather than copies."""
    if not choice.ok or choice.template is None:
        return ""
    template = choice.template
    lines = [
        "## The firm's template for this kind of message",
        "",
        f"Title: {template.title}",
        f"Genre: {template.genre or 'unspecified'}",
        "",
        "This is the firm's own wording for this situation. Adapt it; do not",
        "invent a structure of your own.",
        "",
        "- Keep its order, its register, and its limits paragraph.",
        "- Keep the sentences that state what the firm cannot yet determine. Those",
        "  are deliberate and they are the firm's protection.",
        "- Replace every bracketed slot with the real fact, or drop the sentence if",
        "  the fact is unknown. Never leave a bracket in the draft.",
        "- Drop any question the incoming email has already answered. Asking a",
        "  client for what they have just told you is the commonest failure here.",
        "- Where the email asks something the template does not cover, answer it in",
        "  the template's voice rather than abandoning the template.",
        "- Do not carry over a number from the template unless it genuinely applies",
        "  to this client.",
        "",
        "```",
        template.body.strip(),
        "```",
    ]
    if template.notes:
        lines += ["", f"Note on this template: {template.notes.strip()}"]
    return "\n".join(lines)


def _signal_present(signal: str, terms: set[str]) -> bool:
    """Every word of the signal must appear, in some form the writer might use.

    Two subtleties, both learned from getting it wrong. `index_terms` expands one
    word into several candidate forms, so a signal matches when *any* of a word's
    forms is present, not when all of them are; requiring all demanded forms like
    "סמכים" that no writer would produce.

    And Hebrew attaches possessives, so "זוג" has to reach "זוגי" and "זוגתי".
    Nothing here does real morphology, so a stem that opens a word counts as that
    word, with a length floor so that short signals still need an exact hit.
    """
    words = tokens(signal)
    if not words:
        return False
    return all(any(form in terms for form in _forms(word)) or _stems(word, terms) for word in words)


def _forms(word: str) -> list[str]:
    return variants(word)


def _stems(word: str, terms: set[str]) -> bool:
    for form in variants(word):
        if len(form) < MIN_STEM_MATCH:
            continue
        if any(term.startswith(form) for term in terms):
            return True
    return False


def _parse(path: Path) -> Template | None:
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    meta: dict = {}
    body = raw
    if match:
        import yaml

        loaded = yaml.safe_load(match.group(1))
        meta = loaded if isinstance(loaded, dict) else {}
        body = raw[match.end() :]

    body = body.strip()
    if not body:
        return None
    if len(body) > MAX_TEMPLATE_CHARS:
        body = body[:MAX_TEMPLATE_CHARS]

    return Template(
        slug=path.stem,
        title=str(meta.get("title") or path.stem),
        body=body,
        genre=str(meta.get("genre") or ""),
        client_types=frozenset(_strings(meta.get("client_type"))),
        applies_to=frozenset(_strings(meta.get("applies_to"))),
        signals=tuple(_strings(meta.get("signals"))),
        fallback=bool(meta.get("fallback")),
        notes=str(meta.get("notes") or ""),
        defers=(
            bool(meta["defers_answers"]) if isinstance(meta.get("defers_answers"), bool) else None
        ),
    )


def _strings(value: object) -> list[str]:
    """Accept a scalar or a list, and treat TODO as unset."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        text = str(item).strip()
        if text and text != "TODO":
            out.append(text)
    return out
