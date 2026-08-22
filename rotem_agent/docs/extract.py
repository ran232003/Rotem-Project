from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".csv"}
PDF_SUFFIXES = {".pdf"}
DOCX_SUFFIXES = {".docx"}
SUPPORTED = TEXT_SUFFIXES | PDF_SUFFIXES | DOCX_SUFFIXES

# Below this many characters per page, a PDF is almost certainly a scan with no
# text layer. Immigration files are full of them: certificates, apostilles and
# ministry letters arrive as photographs of paper.
MIN_CHARS_PER_PAGE = 40


@dataclass
class ExtractedDoc:
    path: Path
    text: str
    content_hash: str
    pages: int = 0
    needs_ocr: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED


def extract_file(path: Path) -> ExtractedDoc:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return _extract_text(path)
    if suffix in PDF_SUFFIXES:
        return _extract_pdf(path)
    if suffix in DOCX_SUFFIXES:
        return _extract_docx(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract_text(path: Path) -> ExtractedDoc:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1255", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return ExtractedDoc(path=path, text=text.strip(), content_hash=file_hash(path))


def _extract_pdf(path: Path) -> ExtractedDoc:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is not installed. Run: pip install pypdf") from exc

    warnings: list[str] = []
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        return ExtractedDoc(
            path=path,
            text="",
            content_hash=file_hash(path),
            needs_ocr=True,
            warnings=[f"could not be read ({exc})"],
        )

    text = "\n\n".join(p.strip() for p in pages if p.strip())
    page_count = len(pages)
    # A scan yields a handful of stray characters rather than nothing, so an
    # emptiness check alone would let it through as a document with no content
    # and the retrieval index would quietly lose the file.
    needs_ocr = page_count > 0 and len(text) < MIN_CHARS_PER_PAGE * page_count
    if needs_ocr:
        warnings.append(
            f"only {len(text)} characters across {page_count} page(s): "
            "this looks like a scan and needs OCR to be searchable"
        )
    return ExtractedDoc(
        path=path,
        text=text,
        content_hash=file_hash(path),
        pages=page_count,
        needs_ocr=needs_ocr,
        warnings=warnings,
    )


def _extract_docx(path: Path) -> ExtractedDoc:
    try:
        import docx
    except ImportError as exc:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx") from exc

    document = docx.Document(str(path))
    parts = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return ExtractedDoc(
        path=path,
        text="\n\n".join(parts),
        content_hash=file_hash(path),
    )
