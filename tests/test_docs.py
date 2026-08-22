from __future__ import annotations

from pathlib import Path

import pytest

from rotem_agent.docs.chunk import chunk_text
from rotem_agent.docs.extract import extract_file, file_hash, is_supported


def test_supported_suffixes():
    assert is_supported(Path("a.pdf")) and is_supported(Path("a.DOCX"))
    assert not is_supported(Path("scan.jpg"))


def test_text_file_reads_hebrew_utf8(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("שלום עולם", encoding="utf-8")
    assert extract_file(path).text == "שלום עולם"


def test_text_file_falls_back_to_windows_hebrew_encoding(tmp_path):
    """Older Israeli office files are cp1255, and must not decode to mojibake."""
    path = tmp_path / "legacy.txt"
    path.write_bytes("אשרת חוזר".encode("cp1255"))
    assert extract_file(path).text == "אשרת חוזר"


def test_hash_changes_with_content(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("one", encoding="utf-8")
    first = file_hash(path)
    path.write_text("two", encoding="utf-8")
    assert file_hash(path) != first


def test_unsupported_type_is_rejected(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    with pytest.raises(ValueError, match="Unsupported"):
        extract_file(path)


def test_unreadable_pdf_is_flagged_for_ocr_not_silently_empty(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not really a pdf")
    doc = extract_file(path)
    assert doc.needs_ocr is True
    assert doc.warnings


def test_chunking_splits_on_paragraphs_and_keeps_offsets():
    text = "\n\n".join(f"פסקה מספר {i} " + "מילה " * 40 for i in range(6))
    chunks = chunk_text(text, target_chars=300, overlap_chars=0)
    assert len(chunks) > 1
    for chunk in chunks:
        assert text[chunk.start : chunk.end].strip() == chunk.text


def test_overlap_only_prefixes_later_chunks():
    text = "\n\n".join("שורה " + "מילה " * 30 for _ in range(4))
    chunks = chunk_text(text, target_chars=200, overlap_chars=60)
    assert chunks[0].text == text[chunks[0].start : chunks[0].end].strip()
    later = chunks[1]
    assert len(later.text) > len(text[later.start : later.end].strip())


def test_a_paragraph_larger_than_the_target_is_split():
    text = "משפט אחד. " * 300
    chunks = chunk_text(text, target_chars=400)
    assert len(chunks) > 1
    assert all(chunk.text for chunk in chunks)


def test_text_with_no_whitespace_still_chunks():
    chunks = chunk_text("א" * 5000, target_chars=500)
    assert len(chunks) > 1
    assert sum(len(c.text) for c in chunks) >= 5000


def test_empty_and_blank_text_yield_nothing():
    assert chunk_text("") == []
    assert chunk_text("   \n\n   \n") == []


def test_chunk_indexes_are_sequential():
    text = "\n\n".join(f"בלוק {i} " + "מילה " * 30 for i in range(8))
    chunks = chunk_text(text, target_chars=250)
    assert [c.index for c in chunks] == list(range(len(chunks)))
