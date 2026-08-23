"""The public-documents audit: a work product for the lawyer, not a reply.

Drafting answers one email from a few retrieved passages. This reads a matter's
whole document set at once and produces the table the firm's procedure calls for.
The two differ in shape as well as purpose, which is why the audit has its own
skill, its own schema and its own output file rather than riding along in a
draft.

Two properties are load-bearing. Every assertion carries the citation it came
from, so the lawyer can check it against the paper. And a claim resting on a
machine-read scan is marked as such, because a transcription can misread the very
name the audit exists to compare.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from rotem_agent.llm.base import LlmClient, LlmUsage
from rotem_agent.llm.metering import CallRecord, MeteredClient
from rotem_agent.skill import Skill, load_skill

AUDIT_SKILL = "public-documents-audit"

# A whole matter can exceed a sensible prompt. Truncating loudly beats either a
# provider error or a silent audit of half the file.
MAX_CONTEXT_CHARS = 120_000

AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["timeline", "gaps", "names", "documents", "open_questions", "summary"],
    "properties": {
        "summary": {"type": "string"},
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["when", "event", "basis"],
                "properties": {
                    "when": {"type": "string"},
                    "event": {"type": "string"},
                    "citation": {"type": "string"},
                    "basis": {"type": "string", "enum": ["established", "client_stated"]},
                    "needs_original": {"type": "boolean"},
                },
            },
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["period", "why"],
                "properties": {
                    "period": {"type": "string"},
                    "why": {"type": "string"},
                    "closes_with": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "citation"],
                "properties": {
                    "name": {"type": "string"},
                    "citation": {"type": "string"},
                    "conflicts_with": {"type": "array", "items": {"type": "string"}},
                    "needs_original": {"type": "boolean"},
                },
            },
        },
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["document", "country", "name_on_document", "period", "urgency"],
                "properties": {
                    "document": {"type": "string"},
                    "country": {"type": "string"},
                    "name_on_document": {"type": "string"},
                    "period": {"type": "string"},
                    "apostille": {"type": "string"},
                    "translation": {"type": "string"},
                    "discrepancy": {"type": "string"},
                    "bridging_document": {"type": "string"},
                    "urgency": {"type": "string"},
                    "notes": {"type": "string"},
                    "held": {"type": "boolean"},
                },
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(frozen=True)
class SourceDoc:
    """One document from the matter, as the audit sees it."""

    citation: str
    text: str
    machine_read: bool = False


@dataclass
class AuditReport:
    matter: str
    data: dict[str, Any]
    model: str
    documents_read: int = 0
    truncated: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    usage: LlmUsage | None = None
    calls: list[CallRecord] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.warnings

    def rows(self) -> list[dict]:
        rows = self.data.get("documents")
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def build_context(docs: list[SourceDoc]) -> tuple[str, list[str]]:
    """Lay the matter out for the prompt, and say what would not fit."""
    parts: list[str] = []
    truncated: list[str] = []
    budget = MAX_CONTEXT_CHARS

    for doc in docs:
        header = f"--- {doc.citation}" + (" (machine-read)" if doc.machine_read else "") + " ---"
        if budget <= len(header):
            truncated.append(doc.citation)
            continue
        body = doc.text
        room = budget - len(header) - 2
        if len(body) > room:
            body = body[:room]
            truncated.append(doc.citation)
        parts.append(f"{header}\n{body}")
        budget -= len(header) + len(body) + 2

    return "\n\n".join(parts), truncated


def run_audit(
    matter: str,
    docs: list[SourceDoc],
    llm: LlmClient,
    skill: Skill | None = None,
    *,
    client_name: str = "",
) -> AuditReport:
    skill = skill or load_skill(AUDIT_SKILL)
    context, truncated = build_context(docs)
    meter = MeteredClient(llm)

    started = time.perf_counter()
    response = meter.labelled("audit").complete_json(
        system=skill.as_prompt_section(),
        user=_user_prompt(matter, client_name, context, docs),
        schema=AUDIT_SCHEMA,
        temperature=0.1,
    )
    elapsed = time.perf_counter() - started

    report = AuditReport(
        matter=matter,
        data=response.data,
        model=response.model,
        documents_read=len(docs),
        truncated=truncated,
        usage=meter.usage,
        calls=list(meter.calls),
        seconds=elapsed,
    )
    report.warnings = verify(report, docs)
    return report


def verify(report: AuditReport, docs: list[SourceDoc]) -> list[str]:
    """Catch the failures that would make the table misleading."""
    warnings: list[str] = []
    citations = {doc.citation for doc in docs}
    machine_read = {doc.citation for doc in docs if doc.machine_read}

    cited = _cited_in(report.data)
    invented = sorted(c for c in cited if c and c not in citations)
    if invented:
        warnings.append(
            "Cites documents that are not in the matter: " + ", ".join(invented)
        )

    if not report.rows():
        warnings.append("No document table was produced.")

    # A name conflict resting only on a transcription is the one finding that can
    # be an artefact of the OCR rather than of the certificates.
    for entry in report.data.get("names") or []:
        if not isinstance(entry, dict):
            continue
        citation = str(entry.get("citation", ""))
        if (
            entry.get("conflicts_with")
            and citation in machine_read
            and not entry.get("needs_original")
        ):
            warnings.append(
                f"Name conflict for {entry.get('name')} rests on the machine-read "
                f"{citation} but is not marked as needing the original."
            )

    if report.truncated:
        warnings.append(
            "The matter did not fit the prompt; these were cut short: "
            + ", ".join(sorted(set(report.truncated)))
        )

    return warnings


def render_markdown(report: AuditReport, client_name: str = "") -> str:
    data = report.data
    lines = [
        f"# בדיקת תעודות ציבוריות — {client_name or report.matter}",
        "",
        f"מסמכים שנקראו: {report.documents_read} | מודל: {report.model}",
        "",
        "> מסמך עבודה פנימי. אינו מיועד לשליחה ללקוח.",
        "",
    ]

    if summary := str(data.get("summary", "")).strip():
        lines += ["## תמצית", "", summary, ""]

    if report.warnings:
        lines += ["## אזהרות בדיקה", ""]
        lines += [f"- {w}" for w in report.warnings]
        lines.append("")

    lines += ["## ציר זמן של סטטוס אישי", ""]
    timeline = [e for e in (data.get("timeline") or []) if isinstance(e, dict)]
    if timeline:
        lines += ["| מועד | אירוע | מבוסס על | מקור |", "| --- | --- | --- | --- |"]
        for entry in timeline:
            basis = "מסמך" if entry.get("basis") == "established" else "דברי הלקוח"
            if entry.get("needs_original"):
                basis += " (טעון אימות מול המקור)"
            lines.append(
                f"| {_cell(entry.get('when'))} | {_cell(entry.get('event'))} | "
                f"{basis} | {_cell(entry.get('citation'))} |"
            )
    else:
        lines.append("לא נמצאו נתונים לבניית ציר זמן.")
    lines.append("")

    lines += ["## פערים", ""]
    gaps = [g for g in (data.get("gaps") or []) if isinstance(g, dict)]
    if gaps:
        for gap in gaps:
            lines.append(f"### {_cell(gap.get('period'))}")
            lines.append("")
            lines.append(_cell(gap.get("why")))
            closes = [str(c) for c in (gap.get("closes_with") or [])]
            if closes:
                lines.append("")
                lines.append("נסגר באמצעות:")
                lines += [f"- {c}" for c in closes]
            lines.append("")
    else:
        lines += ["לא זוהו פערים.", ""]

    lines += ["## שמות", ""]
    names = [n for n in (data.get("names") or []) if isinstance(n, dict)]
    if names:
        lines += ["| שם | מקור | מתנגש עם |", "| --- | --- | --- |"]
        for entry in names:
            conflicts = ", ".join(str(c) for c in (entry.get("conflicts_with") or [])) or "-"
            if entry.get("needs_original"):
                conflicts += " (טעון אימות מול המקור)"
            lines.append(
                f"| {_cell(entry.get('name'))} | {_cell(entry.get('citation'))} | {conflicts} |"
            )
    else:
        lines.append("לא נמצאו וריאנטים של שם.")
    lines.append("")

    lines += ["## טבלת מסמכים נדרשים", ""]
    rows = report.rows()
    if rows:
        lines += [
            "| מסמך | מדינה | שם במסמך | תקופה | אפוסטיל | תרגום נוטריוני | "
            "פער | מסמך מגשר | דחיפות | הערות |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in rows:
            lines.append(
                "| "
                + " | ".join(
                    _cell(row.get(key))
                    for key in (
                        "document",
                        "country",
                        "name_on_document",
                        "period",
                        "apostille",
                        "translation",
                        "discrepancy",
                        "bridging_document",
                        "urgency",
                        "notes",
                    )
                )
                + " |"
            )
    else:
        lines.append("לא הופקה טבלה.")
    lines.append("")

    questions = [str(q) for q in (data.get("open_questions") or []) if str(q).strip()]
    lines += ["## שאלות פתוחות לעורכת הדין", ""]
    lines += [f"- {q}" for q in questions] if questions else ["אין."]
    lines.append("")

    return "\n".join(lines)


def _user_prompt(matter: str, client_name: str, context: str, docs: list[SourceDoc]) -> str:
    inventory = "\n".join(
        f"- {doc.citation}" + (" (machine-read from a scan)" if doc.machine_read else "")
        for doc in docs
    )
    return (
        f"Matter: {matter}\n"
        f"Client: {client_name or 'unknown'}\n\n"
        f"Documents held in this matter:\n{inventory or '- none'}\n\n"
        "Document contents follow. Audit them under the firm's procedure and "
        "produce the JSON object.\n\n"
        f"{context or '(no readable documents)'}"
    )


def _cited_in(data: dict) -> set[str]:
    found: set[str] = set()
    for key in ("timeline", "names"):
        for entry in data.get(key) or []:
            if isinstance(entry, dict) and (citation := str(entry.get("citation", "")).strip()):
                found.add(citation)
    return found


def _cell(value: object) -> str:
    """A newline or pipe inside a cell breaks the table it is meant to fill."""
    text = str(value if value is not None else "").strip()
    return text.replace("|", "\\|").replace("\n", " ") or "-"
