from __future__ import annotations

import re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path

from rotem_agent.docs.chunk import chunk_text
from rotem_agent.docs.extract import extract_file, is_supported
from rotem_agent.retrieval.bm25 import Bm25
from rotem_agent.retrieval.hebrew import index_terms


@dataclass(frozen=True)
class AttachmentExcerpt:
    """A passage from a file attached to the incoming email.

    Carries the same citation/text shape as a retrieved excerpt so drafting
    treats both alike, but the citation names the attachment so the lawyer can
    tell a document just received from one already filed to the matter.
    """

    citation: str
    text: str
    filename: str


def excerpts_from_files(
    paths: list[Path],
    query: str = "",
    *,
    max_chunks_per_file: int = 4,
) -> tuple[list[AttachmentExcerpt], list[str]]:
    """Read attachments into excerpts, keeping the passages most like the email.

    A long attachment cannot go into the prompt whole, and taking the first few
    pages would favour letterheads and cover pages. Ranking the chunks against
    the email text costs nothing and keeps the passages that bear on what was
    actually asked.
    """
    excerpts: list[AttachmentExcerpt] = []
    notes: list[str] = []

    for path in paths:
        if not is_supported(path):
            notes.append(f"{path.name}: {path.suffix or 'no extension'} cannot be read yet")
            continue

        document = extract_file(path)
        if document.needs_ocr:
            notes.append(
                f"{path.name}: looks like a scan with no text layer, so its contents "
                "are not available to the draft. Hebrew OCR is not wired up yet."
            )
            continue
        if document.is_empty:
            notes.append(f"{path.name}: no extractable text")
            continue

        chunks = chunk_text(document.text)
        if not chunks:
            continue
        for chunk in _most_relevant(chunks, query, max_chunks_per_file):
            excerpts.append(
                AttachmentExcerpt(
                    citation=f"{path.name}#{chunk.index}",
                    text=chunk.text,
                    filename=path.name,
                )
            )
    return excerpts, notes


def save_eml_attachments(eml_path: Path, destination: Path) -> list[Path]:
    """Write the real attachments of a saved .eml to disk.

    Mirrors the Outlook path: inline images are skipped because a signature logo
    is an attachment by the standard's reckoning but carries nothing to read.
    """
    with eml_path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)

    destination.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for part in message.iter_attachments():
        name = part.get_filename()
        if not name:
            continue
        content_type = part.get_content_type()
        if content_type.startswith("image/") and (
            part.get("Content-ID") or part.get_content_disposition() == "inline"
        ):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        target = destination / safe_filename(name)
        target.write_bytes(payload)
        saved.append(target)
    return saved


def safe_filename(name: str) -> str:
    """A filename arriving by email is untrusted; keep it inside the target folder."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(name).name).strip(" .")
    return cleaned or "attachment"


def _most_relevant(chunks: list, query: str, limit: int) -> list:
    if len(chunks) <= limit:
        return chunks
    terms = index_terms(query)
    if not terms:
        return chunks[:limit]
    scores = Bm25([index_terms(chunk.text) for chunk in chunks]).score(terms)
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:limit]
    # Restore document order so the passages read coherently in the prompt.
    return [chunks[i] for i in sorted(ranked)]
