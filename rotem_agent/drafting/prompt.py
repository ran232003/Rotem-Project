from __future__ import annotations

from typing import Any

from rotem_agent.analysis.questions import AskSet
from rotem_agent.config import Firm, GlossaryTerm
from rotem_agent.mailparse.parser import ParsedEmail
from rotem_agent.mailparse.quotes import QuotedMessage
from rotem_agent.skill import Skill

PLACEHOLDER_FORMAT = "[[להשלמה: ...]]"

CLIENT_TYPES = [
    "existing_client",
    "potential_client",
    "opposing_party",
    "authority",
    "vendor",
    "unknown",
]

# Mirrors the table in skills/legal-client-email-intake/references/matter-routing.md
MATTER_CATEGORIES = [
    "status_spousal",
    "asylum",
    "reentry_visa",
    "entry_refusal",
    "foreign_expert",
    "elderly_parent",
    "citizenship",
    "family",
    "inheritance",
    "admin",
    "not_a_matter",
]

APPROVAL_LEVELS = ["may_send", "lawyer_review", "principal_lawyer_review"]

DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "internal": {
            "type": "object",
            "properties": {
                "client_type": {"type": "string", "enum": CLIENT_TYPES},
                "matter_category": {"type": "string", "enum": MATTER_CATEGORIES},
                "urgency": {
                    "type": "string",
                    "enum": ["routine", "prompt", "urgent", "emergency"],
                },
                "key_facts": {"type": "array", "items": {"type": "string"}},
                "missing_facts": {"type": "array", "items": {"type": "string"}},
                "likely_sources": {"type": "array", "items": {"type": "string"}},
                "sources_used": {"type": "array", "items": {"type": "string"}},
                "unverified_propositions": {"type": "array", "items": {"type": "string"}},
                "escalation_triggers": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "approval": {"type": "string", "enum": APPROVAL_LEVELS},
                "is_holding_reply": {"type": "boolean"},
                "next_action": {"type": "string"},
            },
            "required": [
                "client_type",
                "matter_category",
                "urgency",
                "key_facts",
                "missing_facts",
                "likely_sources",
                "sources_used",
                "unverified_propositions",
                "escalation_triggers",
                "confidence",
                "approval",
                "is_holding_reply",
                "next_action",
            ],
        },
        "draft": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "language": {"type": "string", "enum": ["he", "en"]},
                "body": {"type": "string"},
            },
            "required": ["subject", "language", "body"],
        },
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ask": {"type": "string"},
                    "answered": {"type": "boolean"},
                    "excerpt": {"type": "string"},
                },
                "required": ["ask", "answered", "excerpt"],
            },
        },
        "placeholders": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["internal", "draft", "answers", "placeholders"],
}

_STRICT_POLICY = """## Source policy: strict (no verification tool available)

You have no access to gov.il, the Population and Immigration Authority website,
legislation or case law in this run. Therefore you cannot verify any legal or
procedural proposition.

Consequences, which are mandatory:
- List every proposition material to the answer under internal.unverified_propositions.
- If that list is not empty, set internal.confidence to "low", set
  internal.is_holding_reply to true, and produce a neutral holding reply as
  defined in the source verification reference.
- A holding reply is the correct output here, not a failure. Do not assert a
  legal position and then hedge it; that is the failure mode this policy exists
  to prevent."""

_ADVISORY_POLICY = """## Source policy: advisory

You may state a legal or procedural position where the thread itself supports
it, but you must list every proposition that would need an official source
under internal.unverified_propositions, and set internal.confidence honestly.
Do not cite a procedure number, version date or statutory reference you cannot
verify."""

_TEMPLATE = """You are drafting on behalf of {lawyer}, {firm}.

{skill}

# Terms of art

Use these exact terms rather than a paraphrase. In legal Hebrew a near-synonym
is a wrong answer. Do not, however, introduce a term whose procedure the source
material does not actually mention.

{glossary}

{policy}

# Placeholders

Where a fact is required but absent from the supplied context, write
{placeholder} describing what is missing. Never guess a date, a number of days,
a duration, an amount, a file number or a statutory reference.

# Document excerpts

Two kinds of document passage may be supplied, and the difference matters.

"מסמכים מתיק הלקוח" are passages retrieved from the client's existing file. They
are established facts about this matter.

"קבצים שצורפו להודעה זו" are passages from files attached to the email you are
answering. The sender has just provided them, so treat them as what the sender
asserts rather than as something the office has already checked. If such a file
answers a question, say so and confirm receipt; if it appears to conflict with
the client file, do not resolve the conflict yourself, note it in
internal.escalation_triggers and leave it for the lawyer.

Each excerpt carries an identifier such as `letter.pdf#3`. For every fact you
take from an excerpt, list that identifier in internal.sources_used. List only
identifiers that were actually supplied to you: never construct one, and never
name a document you were not shown. Retrieval returns the passages that looked
relevant, not necessarily ones that are, so an excerpt that does not bear on the
question should simply be left unused rather than worked into the reply.

# Output

Return JSON matching the provided schema. The internal object is the internal
note and is never sent. The draft object is the client-facing reply. Never put
internal analysis, the words "INTERNAL" or "DO NOT SEND", strategy, or
confidence levels into draft.body.

End draft.body with the last sentence of substance. Do not write a sign-off of
any kind: no "בברכה", no "בכבוד רב", no firm name and no lawyer name. Outlook
appends the real signature, so a sign-off here produces a message that signs off
twice.

Set draft.language to match the language of the incoming email. Write the
internal note fields in Hebrew regardless, since the lawyer reads them.

Format draft.body as an email, not as a paragraph of prose. Separate the
greeting, each numbered answer, any closing remark and the sign-off with a blank
line, using a real newline character in the JSON string. A reply that answers
several questions in one unbroken block is hard to read and hard to check."""


def build_system_prompt(
    firm: Firm,
    glossary: list[GlossaryTerm],
    skill: Skill,
    source_policy: str = "strict",
    matter_category: str | None = None,
) -> str:
    terms = "\n".join(f"- {t.he}" + (f" ({t.en})" if t.en else "") for t in glossary)
    return _TEMPLATE.format(
        lawyer=firm.lawyer_name,
        firm=firm.firm_name,
        skill=skill.as_prompt_section(matter_category),
        glossary=terms,
        policy=_STRICT_POLICY if source_policy == "strict" else _ADVISORY_POLICY,
        placeholder=PLACEHOLDER_FORMAT,
    )


def build_user_prompt(
    email: ParsedEmail,
    asks: AskSet,
    style_examples: list[QuotedMessage],
    excerpts: list[Any] | None = None,
    attachments: list[Any] | None = None,
    template_section: str = "",
) -> str:
    sections = [
        "## פרטי ההודעה הנכנסת",
        f"נושא: {email.subject}",
        f"מאת: {email.from_ or 'לא ידוע'}",
        f"אל: {', '.join(str(p) for p in email.to) or 'לא ידוע'}",
        f"עותק: {', '.join(str(p) for p in email.cc) or 'אין'}",
        f"תאריך: {email.date or 'לא ידוע'}",
        f"קבצים מצורפים: {', '.join(a.filename or '?' for a in email.real_attachments) or 'אין'}",
        "",
        "## גוף ההודעה הנכנסת",
        email.latest_body or "(ריק)",
    ]

    history = [m for m in email.quoted_chain if m not in style_examples]
    if history:
        sections += ["", "## התכתבות קודמת בשרשור"]
        sections += [_format_quoted(m) for m in history]

    if style_examples:
        sections += ["", "## דוגמאות לסגנון הכתיבה של המשרד (חקה אותן)"]
        sections += [_format_quoted(m) for m in style_examples]

    if excerpts:
        sections += ["", "## מסמכים מתיק הלקוח"]
        for excerpt in excerpts:
            sections.append(f"\n--- [{excerpt.citation}]\n{excerpt.text}".rstrip())

    if attachments:
        sections += ["", "## קבצים שצורפו להודעה זו"]
        for attachment in attachments:
            sections.append(f"\n--- [{attachment.citation}]\n{attachment.text}".rstrip())

    # Last, and after the excerpts, because it is the instruction the model
    # should still have in view when it starts composing.
    if template_section:
        sections += ["", template_section]

    sections += ["", "## שאלות ובקשות שיש לענות עליהן"]
    sections += [f"{i}. [{a.kind}] {a.text}" for i, a in enumerate(asks.asks, start=1)]
    if asks.expected_count is not None:
        sections.append(f"\nהשולח ציין במפורש שהוא מצפה למענה על {asks.expected_count} שאלות.")

    return "\n".join(sections)


def _format_quoted(message: QuotedMessage) -> str:
    header = " | ".join(
        part
        for part in (
            f"מאת: {message.from_}" if message.from_ else "",
            f"נשלח: {message.sent}" if message.sent else "",
        )
        if part
    )
    return f"\n---\n{header}\n{message.body}".rstrip()
