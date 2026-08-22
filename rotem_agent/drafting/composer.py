from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from rotem_agent.analysis.questions import AskSet, extract_asks
from rotem_agent.config import Firm, GlossaryTerm, load_firm, load_glossary
from rotem_agent.drafting.prompt import DRAFT_SCHEMA, build_system_prompt, build_user_prompt
from rotem_agent.llm.base import LlmClient, LlmUsage
from rotem_agent.mailparse.parser import ParsedEmail
from rotem_agent.mailparse.quotes import QuotedMessage
from rotem_agent.skill import Skill, load_skill

_PLACEHOLDER_SPAN = re.compile(r"\[\[.*?\]\]", re.DOTALL)
_LIST_MARKER = re.compile(r"^[ \t]*\d{1,2}[.)][ \t]", re.MULTILINE)
_NUMBER = re.compile(r"\d+")
_EMAIL_IN_TEXT = re.compile(r"[\w.\-+]+@[\w.\-]+")
_HEBREW = re.compile(r"[\u0590-\u05FF]")
_LATIN = re.compile(r"[A-Za-z]")
_LEAKED_INTERNAL = re.compile(
    r"INTERNAL|DO NOT SEND|לא לשליחה|confidence:|approval:|matter_category", re.IGNORECASE
)

# The identity gate in the skill: these senders must be confirmed before any
# case detail leaves the office.
_GATED_CLIENT_TYPES = {"opposing_party", "unknown"}


@dataclass(frozen=True)
class Answer:
    ask: str
    answered: bool
    excerpt: str


@dataclass(frozen=True)
class InternalNote:
    client_type: str
    matter_category: str
    urgency: str
    confidence: str
    approval: str
    is_holding_reply: bool
    next_action: str
    key_facts: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    likely_sources: list[str] = field(default_factory=list)
    unverified_propositions: list[str] = field(default_factory=list)
    escalation_triggers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DraftReport:
    subject: str
    language: str
    draft_text: str
    internal: InternalNote
    answers: list[Answer]
    placeholders: list[str]
    asks: AskSet
    model: str
    source_policy: str
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    usage: LlmUsage | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


def compose(
    email: ParsedEmail,
    llm: LlmClient,
    firm: Firm | None = None,
    glossary: list[GlossaryTerm] | None = None,
    skill: Skill | None = None,
    source_policy: str = "advisory",
) -> DraftReport:
    firm = firm or load_firm()
    glossary = glossary if glossary is not None else load_glossary()
    skill = skill or load_skill()

    asks = extract_asks(email.latest_body, llm)
    style_examples = _style_examples(email.quoted_chain, firm)

    response = llm.complete_json(
        system=build_system_prompt(firm, glossary, skill, source_policy),
        user=build_user_prompt(email, asks, style_examples),
        schema=DRAFT_SCHEMA,
        temperature=0.3,
    )

    draft = response.data.get("draft", {})
    internal = _internal_note(response.data.get("internal", {}))
    answers = [
        Answer(
            ask=str(item.get("ask", "")).strip(),
            answered=bool(item.get("answered")),
            excerpt=str(item.get("excerpt", "")).strip(),
        )
        for item in response.data.get("answers", [])
    ]

    draft_text = str(draft.get("body", "")).strip()
    problems, warnings = _verify(draft_text, answers, asks, email, internal, source_policy, firm)
    effective_approval, approval_warning = _enforce_approval(internal)
    if approval_warning:
        warnings.append(approval_warning)

    return DraftReport(
        subject=str(draft.get("subject", email.subject)).strip(),
        language=str(draft.get("language", "he")).strip(),
        draft_text=draft_text,
        internal=_with_approval(internal, effective_approval),
        answers=answers,
        placeholders=[
            str(p).strip() for p in response.data.get("placeholders", []) if str(p).strip()
        ],
        asks=asks,
        model=response.model,
        source_policy=source_policy,
        problems=problems,
        warnings=warnings,
        usage=response.usage,
    )


def _internal_note(data: dict) -> InternalNote:
    def strings(key: str) -> list[str]:
        return [str(v).strip() for v in data.get(key, []) if str(v).strip()]

    return InternalNote(
        client_type=str(data.get("client_type", "unknown")),
        matter_category=str(data.get("matter_category", "not_a_matter")),
        urgency=str(data.get("urgency", "routine")),
        confidence=str(data.get("confidence", "low")),
        approval=str(data.get("approval", "lawyer_review")),
        is_holding_reply=bool(data.get("is_holding_reply")),
        next_action=str(data.get("next_action", "")).strip(),
        key_facts=strings("key_facts"),
        missing_facts=strings("missing_facts"),
        likely_sources=strings("likely_sources"),
        unverified_propositions=strings("unverified_propositions"),
        escalation_triggers=strings("escalation_triggers"),
    )


def _with_approval(note: InternalNote, approval: str) -> InternalNote:
    return InternalNote(**{**note.__dict__, "approval": approval})


def _enforce_approval(note: InternalNote) -> tuple[str, str | None]:
    """Nothing in this system may be marked sendable without a human.

    The application holds no send capability at all, so this is belt and braces,
    but the internal note is what a future dashboard would act on.
    """
    if note.escalation_triggers or note.urgency == "emergency":
        if note.approval != "principal_lawyer_review":
            return "principal_lawyer_review", (
                "Approval raised to principal lawyer review because an escalation "
                f"trigger fired: {'; '.join(note.escalation_triggers) or note.urgency}"
            )
        return note.approval, None
    if note.approval == "may_send":
        return "lawyer_review", (
            "Model marked this as sendable without review; overridden to lawyer review."
        )
    return note.approval, None


def _style_examples(chain: list[QuotedMessage], firm: Firm) -> list[QuotedMessage]:
    """Messages in the trail written by the firm itself are the tone reference."""
    examples = []
    for message in chain:
        if not message.from_:
            continue
        addresses = _EMAIL_IN_TEXT.findall(message.from_)
        if any(firm.is_own_address(a) for a in addresses) or firm.lawyer_name in message.from_:
            examples.append(message)
    return examples


def _verify(
    draft_text: str,
    answers: list[Answer],
    asks: AskSet,
    email: ParsedEmail,
    internal: InternalNote,
    source_policy: str,
    firm: Firm,
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []

    if not draft_text:
        problems.append("The model returned an empty draft.")

    if _has_signature(draft_text, firm):
        warnings.append(
            "Draft ends with the firm signature; it will be duplicated once the real "
            "Outlook signature is appended."
        )

    if leaked := _LEAKED_INTERNAL.search(draft_text):
        problems.append(f"Internal note wording leaked into the client draft: {leaked.group(0)!r}")

    # A holding reply deliberately declines to answer, so unanswered asks are
    # expected there and only become a problem in a substantive reply.
    unanswered = [a.ask for a in answers if not a.answered]
    coverage_gap = len(answers) != len(asks.asks)
    if internal.is_holding_reply:
        if unanswered:
            warnings.append(
                f"Holding reply: {len(unanswered)} ask(s) deferred pending source verification."
            )
        if coverage_gap:
            warnings.append(
                f"Holding reply acknowledges {len(answers)} of {len(asks.asks)} asks."
            )
    else:
        if unanswered:
            problems.append(
                f"{len(unanswered)} ask(s) reported unanswered: {'; '.join(unanswered)}"
            )
        if coverage_gap:
            problems.append(
                f"Coverage mismatch: {len(asks.asks)} asks extracted but {len(answers)} answered."
            )

    if source_policy == "strict" and internal.unverified_propositions and not internal.is_holding_reply:
        problems.append(
            f"{len(internal.unverified_propositions)} unverified proposition(s) asserted "
            "without a holding reply, which the strict source policy forbids: "
            + "; ".join(internal.unverified_propositions)
        )

    if internal.confidence == "low" and not internal.is_holding_reply:
        warnings.append("Confidence is low but the draft is substantive rather than a holding reply.")

    if internal.client_type in _GATED_CLIENT_TYPES:
        warnings.append(
            f"Identity gate: sender classified as {internal.client_type}; "
            "confirm authorisation before any case detail goes out."
        )

    if len(internal.missing_facts) > 5:
        warnings.append(
            f"{len(internal.missing_facts)} missing facts listed; the skill allows two to five."
        )

    if asks.count_mismatch:
        warnings.append(
            f"Sender explicitly expects {asks.expected_count} answers "
            f"but {len(asks.asks)} asks were extracted."
        )

    if asks.heuristic_only:
        warnings.append(
            "Possible asks the model dropped: " + "; ".join(a.text for a in asks.heuristic_only)
        )

    if (expected := _detect_language(email.latest_body)) and expected != _detect_language(draft_text):
        problems.append(
            f"Language mismatch: incoming email is {expected} but the draft is not."
        )

    if ungrounded := _ungrounded_numbers(draft_text, email.context_text()):
        warnings.append(
            "Numbers in the draft that do not appear in the source context: "
            + ", ".join(ungrounded)
        )

    return problems, warnings


def _has_signature(draft_text: str, firm: Firm) -> bool:
    """The real Outlook signature is appended later, so the model must not add one."""
    tail = "\n".join(draft_text.strip().split("\n")[-3:])
    return firm.lawyer_name in tail or firm.firm_name in tail


def _detect_language(text: str) -> str | None:
    hebrew, latin = len(_HEBREW.findall(text)), len(_LATIN.findall(text))
    if hebrew + latin < 20:
        return None
    return "he" if hebrew > latin else "en"


def _ungrounded_numbers(draft_text: str, context: str) -> list[str]:
    """Every date, duration and statutory number must come from the thread.

    Placeholders and the draft's own list numbering are excluded, so what
    remains is a number the model produced from nowhere.
    """
    cleaned = _LIST_MARKER.sub("", _PLACEHOLDER_SPAN.sub("", draft_text))
    in_draft = set(_NUMBER.findall(cleaned))
    in_context = set(_NUMBER.findall(context))
    return sorted(in_draft - in_context, key=lambda value: (len(value), value))


def render_draft_html(report: DraftReport) -> str:
    direction = "rtl" if report.language == "he" else "ltr"
    banner = (
        "טיוטת המתנה — אין בה עמדה משפטית, בהמתנה לאימות מקורות."
        if report.internal.is_holding_reply
        else "טיוטה לבדיקה. החתימה תתווסף בנפרד."
    )
    paragraphs = "\n".join(
        f"    <p>{html.escape(block).replace(chr(10), '<br>')}</p>"
        for block in report.draft_text.split("\n\n")
        if block.strip()
    )
    return f"""<!DOCTYPE html>
<html lang="{report.language}" dir="{direction}">
<head>
  <meta charset="utf-8">
  <title>{html.escape(report.subject)}</title>
  <style>
    body {{ font-family: Arial, "Segoe UI", sans-serif; direction: {direction};
           max-width: 46rem; margin: 2rem auto; line-height: 1.7; color: #1a1a1a; }}
    .banner {{ background: #fff4e5; border: 1px solid #f0c14b; padding: .75rem 1rem;
               border-radius: .4rem; margin-bottom: 1.5rem; }}
    h1 {{ font-size: 1.1rem; color: #555; font-weight: 600; }}
  </style>
</head>
<body>
  <div class="banner">{banner} · {html.escape(report.internal.approval)}</div>
  <h1>{html.escape(report.subject)}</h1>
{paragraphs}
</body>
</html>
"""


def render_internal_note(report: DraftReport) -> str:
    note = report.internal
    lines = [
        "# INTERNAL — DO NOT SEND",
        "",
        f"- Client type: {note.client_type}",
        f"- Matter category: {note.matter_category}",
        f"- Urgency: {note.urgency}",
        f"- Confidence: {note.confidence}",
        f"- Approval: {note.approval}",
        f"- Holding reply: {'yes' if note.is_holding_reply else 'no'}",
        f"- Source policy: {report.source_policy}",
        f"- Next action: {note.next_action or '-'}",
    ]
    for title, items in (
        ("Key facts", note.key_facts),
        ("Missing facts", note.missing_facts),
        ("Likely official sources", note.likely_sources),
        ("Unverified propositions", note.unverified_propositions),
        ("Escalation triggers", note.escalation_triggers),
        ("Placeholders", report.placeholders),
        ("Problems", report.problems),
        ("Warnings", report.warnings),
    ):
        lines += ["", f"## {title}"]
        lines += [f"- {item}" for item in items] or ["- none"]
    return "\n".join(lines) + "\n"
