from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

from rotem_agent.attachments import excerpts_from_files, safe_filename, save_eml_attachments
from rotem_agent.docs.ocr import OcrResult
from rotem_agent.llm.base import LlmUsage


class _StubOcr:
    def __init__(self, text: str, usage: LlmUsage | None = None) -> None:
        self.text = text
        self.usage = usage

    @property
    def name(self) -> str:
        return "stub-ocr"

    def read(self, path: Path, pages: int = 0) -> OcrResult:
        return OcrResult(text=self.text, usage=self.usage, model=self.name)


def _write_eml(path: Path, parts: list[tuple[str, bytes, str, str, bool]]) -> Path:
    """parts: (filename, payload, maintype, subtype, inline)"""
    message = EmailMessage()
    message["Subject"] = "נושא"
    message["From"] = "client@example.com"
    message["To"] = "office@example.com"
    message.set_content("שלום, מצורף מסמך.")
    for filename, payload, maintype, subtype, inline in parts:
        message.add_attachment(
            payload,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
            disposition="inline" if inline else "attachment",
            cid=f"<{filename}>" if inline else None,
        )
    path.write_bytes(message.as_bytes())
    return path


def test_attachment_text_becomes_an_excerpt(tmp_path):
    eml = _write_eml(
        tmp_path / "mail.eml",
        [("letter.txt", "מספר תיק 458822 אושר".encode("utf-8"), "text", "plain", False)],
    )
    saved = save_eml_attachments(eml, tmp_path / "out")
    assert [p.name for p in saved] == ["letter.txt"]

    excerpts, notes = excerpts_from_files(saved)
    assert excerpts[0].citation == "letter.txt#0"
    assert "458822" in excerpts[0].text
    assert not notes


def test_an_inline_signature_image_is_not_treated_as_a_document(tmp_path):
    """A logo is an attachment by the standard's reckoning but carries nothing to read."""
    eml = _write_eml(
        tmp_path / "mail.eml",
        [
            ("logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image", "png", True),
            ("letter.txt", "תוכן".encode("utf-8"), "text", "plain", False),
        ],
    )
    saved = save_eml_attachments(eml, tmp_path / "out")
    assert [p.name for p in saved] == ["letter.txt"]


def test_an_unreadable_type_is_reported_rather_than_ignored(tmp_path):
    eml = _write_eml(
        tmp_path / "mail.eml",
        [("bundle.zip", b"PK\x03\x04" + b"0" * 32, "application", "zip", False)],
    )
    saved = save_eml_attachments(eml, tmp_path / "out")
    excerpts, notes = excerpts_from_files(saved)
    assert not excerpts
    assert any("cannot be read" in note for note in notes)


def test_a_scanned_pdf_is_reported_as_needing_ocr(tmp_path):
    """Silence here would let the draft answer as though the document were absent."""
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"not a real pdf")
    excerpts, notes = excerpts_from_files([path])
    assert not excerpts
    assert any("OCR" in note for note in notes)


def test_a_photographed_certificate_is_transcribed_into_an_excerpt(tmp_path):
    path = tmp_path / "birth-certificate.jpg"
    path.write_bytes(b"\xff\xd8\xff" + b"0" * 32)
    excerpts, notes = excerpts_from_files([path], ocr=_StubOcr("תעודת לידה\nשם: אנה"))
    assert [e.text for e in excerpts] == ["תעודת לידה\nשם: אנה"]
    assert all(e.machine_read for e in excerpts)


def test_a_machine_read_excerpt_says_so_in_its_citation_and_notes(tmp_path):
    """The lawyer must be able to see that a name came from a machine, not paper."""
    path = tmp_path / "passport.jpg"
    path.write_bytes(b"\xff\xd8\xff" + b"0" * 32)
    excerpts, notes = excerpts_from_files([path], ocr=_StubOcr("Anna Ivanova"))
    assert "machine-read" in excerpts[0].citation
    assert any("checked against the original" in note for note in notes)


def test_ocr_token_usage_is_collected_for_the_cost_log(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"not a real pdf")
    usage: list = []
    excerpts, _ = excerpts_from_files(
        [path],
        ocr=_StubOcr("תעודה", usage=LlmUsage(input_tokens=900, output_tokens=120)),
        usage=usage,
    )
    assert excerpts and [u.input_tokens for u in usage] == [900]


def test_long_attachments_are_trimmed_to_the_passages_matching_the_email(tmp_path):
    blocks = [f"פסקה {i} " + "מילה " * 60 for i in range(10)]
    blocks[7] = "מספר התיק שלך הוא 458822 והבקשה אושרה " * 8
    path = tmp_path / "long.txt"
    path.write_text("\n\n".join(blocks), encoding="utf-8")

    excerpts, _ = excerpts_from_files([path], "מה מספר התיק שלי", max_chunks_per_file=2)
    assert len(excerpts) == 2
    assert any("458822" in excerpt.text for excerpt in excerpts)


def test_chunk_order_is_preserved_after_ranking(tmp_path):
    blocks = [f"קטע {i} " + "מילה " * 60 for i in range(8)]
    path = tmp_path / "doc.txt"
    path.write_text("\n\n".join(blocks), encoding="utf-8")
    excerpts, _ = excerpts_from_files([path], "מילה", max_chunks_per_file=3)
    indexes = [int(e.citation.split("#")[1]) for e in excerpts]
    assert indexes == sorted(indexes)


def test_a_hostile_filename_cannot_escape_the_target_folder():
    assert safe_filename("../../windows/system32/evil.txt") == "evil.txt"
    assert safe_filename("a/b\\c.txt") == "c.txt"
    assert safe_filename("...") == "attachment"


def test_no_attachments_yields_nothing(tmp_path):
    eml = _write_eml(tmp_path / "mail.eml", [])
    assert save_eml_attachments(eml, tmp_path / "out") == []
    assert excerpts_from_files([]) == ([], [])
