from __future__ import annotations

from rotem_agent.audit import (
    AUDIT_SKILL,
    AuditReport,
    SourceDoc,
    build_context,
    render_markdown,
    run_audit,
    verify,
)
from rotem_agent.llm.base import LlmResponse, LlmUsage
from rotem_agent.skill import load_skill


class _StubLlm:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.system = ""
        self.user = ""

    @property
    def model(self) -> str:
        return "stub-model"

    def complete_json(self, *, system, user, schema, temperature=0.2):
        self.system, self.user = system, user
        return LlmResponse(
            data=self.data,
            model=self.model,
            usage=LlmUsage(input_tokens=1000, output_tokens=300, thinking_tokens=200),
        )


def _report(data: dict, **kwargs) -> AuditReport:
    return AuditReport(matter="anna", data=data, model="stub-model", **kwargs)


def _delimiters(row: str) -> int:
    """Count the pipes that structure the row, ignoring any escaped in a value."""
    return row.replace("\\|", "").count("|")


FULL_DOCS = [
    SourceDoc("birth.pdf", "תעודת לידה"),
    SourceDoc("divorce.pdf", "תעודת גירושין"),
    SourceDoc("marriage.pdf", "תעודת נישואין"),
]

FULL = {
    "summary": "פער בין הגירושין לנישואין החדשים.",
    "timeline": [
        {
            "when": "1995",
            "event": "גירושין",
            "citation": "divorce.pdf",
            "basis": "established",
        },
        {"when": "2005", "event": "נישואין", "citation": "marriage.pdf", "basis": "established"},
    ],
    "gaps": [
        {
            "period": "1995-2005",
            "why": "לא הוכח שהלקוחה הייתה פנויה לנישואין.",
            "closes_with": ["תעודת מצב אישי", "CENOMAR"],
        }
    ],
    "names": [
        {"name": "IVANOVA", "citation": "birth.pdf", "conflicts_with": ["IVANOVva"]},
    ],
    "documents": [
        {
            "document": "תעודת מצב אישי",
            "country": "מולדובה",
            "name_on_document": "IVANOVA",
            "period": "1995-2005",
            "apostille": "נדרש",
            "translation": "נדרש",
            "discrepancy": "פער סטטוס",
            "bridging_document": "CENOMAR",
            "urgency": "גבוהה",
            "notes": "[[TBD: תוקף התעודה]]",
        }
    ],
    "open_questions": ["מהו הנוהל הדורש CENOMAR?"],
}


# -------------------------------------------------------------------- the skill

def test_the_audit_skill_loads_with_its_reference():
    skill = load_skill(AUDIT_SKILL)
    assert "bridging documents" in skill.references
    section = skill.as_prompt_section()
    assert "CENOMAR" in section
    assert "Never invent a requirement's authority" in section


# ------------------------------------------------------------------ the context

def test_context_labels_machine_read_documents():
    context, truncated = build_context(
        [
            SourceDoc("birth.pdf", "text one"),
            SourceDoc("passport.jpg", "text two", machine_read=True),
        ]
    )
    assert "--- birth.pdf ---" in context
    assert "--- passport.jpg (machine-read) ---" in context
    assert not truncated


def test_an_oversized_matter_is_cut_and_says_so():
    """A silent truncation would produce an audit of half a file that looks whole."""
    docs = [SourceDoc(f"doc{i}.pdf", "א" * 50_000) for i in range(5)]
    context, truncated = build_context(docs)
    assert truncated
    assert len(context) <= 130_000


# ---------------------------------------------------------------- verification

def test_a_citation_outside_the_matter_is_caught():
    """A fabricated source is the failure that would send the client for nothing."""
    data = dict(FULL)
    data["names"] = [{"name": "X", "citation": "invented.pdf"}]
    warnings = verify(_report(data), FULL_DOCS)
    assert any("invented.pdf" in w for w in warnings)


def test_a_name_conflict_from_a_scan_must_be_marked_for_the_original():
    data = {
        **FULL,
        "names": [
            {"name": "IVANOVA", "citation": "passport.jpg", "conflicts_with": ["IVANOVva"]}
        ],
    }
    docs = [*FULL_DOCS, SourceDoc("passport.jpg", "t", machine_read=True)]
    warnings = verify(_report(data), docs)
    assert any("machine-read" in w for w in warnings)


def test_a_marked_conflict_from_a_scan_is_accepted():
    data = {
        **FULL,
        "names": [
            {
                "name": "IVANOVA",
                "citation": "passport.jpg",
                "conflicts_with": ["IVANOVva"],
                "needs_original": True,
            }
        ],
    }
    docs = [*FULL_DOCS, SourceDoc("passport.jpg", "t", machine_read=True)]
    assert not verify(_report(data), docs)


def test_a_conflict_from_a_text_layer_needs_no_marking():
    data = {
        **FULL,
        "names": [{"name": "IVANOVA", "citation": "birth.pdf", "conflicts_with": ["X"]}],
    }
    assert not verify(_report(data), FULL_DOCS)


def test_an_empty_table_is_a_problem():
    data = {**FULL, "documents": []}
    warnings = verify(_report(data), FULL_DOCS)
    assert any("No document table" in w for w in warnings)


# ----------------------------------------------------------------- the run

def test_run_audit_passes_the_inventory_and_meters_the_call():
    llm = _StubLlm(FULL)
    docs = [SourceDoc("birth.pdf", "תעודת לידה"), SourceDoc("scan.jpg", "x", True)]
    report = run_audit("anna", docs, llm, load_skill(AUDIT_SKILL))

    assert "birth.pdf" in llm.user and "machine-read from a scan" in llm.user
    assert report.documents_read == 2
    assert report.usage.input_tokens == 1000
    assert report.usage.billed_output_tokens == 500
    assert [c.purpose for c in report.calls] == ["audit"]


# ----------------------------------------------------------------- rendering

def test_markdown_carries_the_ten_column_table():
    report = _report(FULL)
    text = render_markdown(report, "אנה")
    assert "# בדיקת תעודות ציבוריות — אנה" in text
    assert "מסמך עבודה פנימי" in text
    header = next(line for line in text.splitlines() if line.startswith("| מסמך |"))
    assert _delimiters(header) == 11  # ten columns
    assert "CENOMAR" in text
    assert "מהו הנוהל הדורש CENOMAR?" in text


def test_a_pipe_in_a_value_cannot_break_the_table():
    data = {
        **FULL,
        "documents": [
            {
                "document": "תעודה | עם קו",
                "country": "X",
                "name_on_document": "Y",
                "period": "1995",
                "urgency": "גבוהה",
                "notes": "שורה\nשנייה",
            }
        ],
    }
    row = next(
        line
        for line in render_markdown(_report(data)).splitlines()
        if line.startswith("| תעודה")
    )
    assert _delimiters(row) == 11
    assert "\\|" in row
    assert "\n" not in row


def test_missing_sections_render_without_crashing():
    text = render_markdown(_report({"summary": "", "documents": []}))
    assert "לא הופקה טבלה." in text
    assert "לא זוהו פערים." in text


def test_warnings_appear_in_the_work_product():
    """The lawyer reads the file, not the console, so a caveat must live in it."""
    report = _report(FULL, warnings=["Cites documents that are not in the matter: x.pdf"])
    assert "אזהרות בדיקה" in render_markdown(report)
    assert "x.pdf" in render_markdown(report)
