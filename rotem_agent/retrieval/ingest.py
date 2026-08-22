from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rotem_agent.docs.chunk import chunk_text
from rotem_agent.docs.extract import extract_file, file_hash, is_supported
from rotem_agent.matters.registry import Matter
from rotem_agent.retrieval.embed import Embedder
from rotem_agent.retrieval.hebrew import index_terms
from rotem_agent.retrieval.store import ChunkStore


@dataclass
class IngestSummary:
    matter: str
    added: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    needs_ocr: list[str] = field(default_factory=list)
    chunks: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


def ingest_matter(
    matter: Matter,
    store: ChunkStore,
    embedder: Embedder | None = None,
    *,
    log: Callable[[str], None] = print,
    force: bool = False,
) -> IngestSummary:
    summary = IngestSummary(matter=matter.slug)
    docs_dir = matter.docs_dir
    if not docs_dir.exists():
        log(f"  no docs folder at {docs_dir}")
        return summary

    known = store.hashes(matter.slug)
    seen: set[str] = set()

    for path in sorted(p for p in docs_dir.rglob("*") if p.is_file()):
        rel_path = str(path.relative_to(docs_dir)).replace("\\", "/")
        if not is_supported(path):
            summary.skipped.append(rel_path)
            continue
        seen.add(rel_path)

        digest = file_hash(path)
        if not force and known.get(rel_path) == digest:
            summary.unchanged.append(rel_path)
            continue

        document = extract_file(path)
        if document.needs_ocr:
            summary.needs_ocr.append(rel_path)
        for warning in document.warnings:
            log(f"  {rel_path}: {warning}")

        pieces = chunk_text(document.text)
        if not pieces:
            # Recorded with zero chunks so the hash is remembered and the file is
            # not re-extracted every run, and so it shows up as present but
            # unsearchable rather than vanishing from the matter entirely.
            store.replace_document(
                matter.slug,
                rel_path,
                digest,
                pages=document.pages,
                needs_ocr=document.needs_ocr,
                chunks=[],
                embed_model=embedder.name if embedder else "",
            )
            log(f"  {rel_path}: no extractable text")
            continue

        vectors: list = [None] * len(pieces)
        if embedder is not None:
            embedded = embedder.embed_documents([piece.text for piece in pieces])
            if len(embedded) != len(pieces):
                raise RuntimeError(
                    f"{rel_path}: embedder returned {len(embedded)} vectors for "
                    f"{len(pieces)} chunks; refusing to store mismatched vectors."
                )
            vectors = list(embedded)

        store.replace_document(
            matter.slug,
            rel_path,
            digest,
            pages=document.pages,
            needs_ocr=document.needs_ocr,
            chunks=[
                (
                    piece.index,
                    piece.text,
                    piece.start,
                    piece.end,
                    index_terms(piece.text),
                    vectors[position],
                )
                for position, piece in enumerate(pieces)
            ],
            embed_model=embedder.name if embedder else "",
        )
        summary.added.append(rel_path)
        summary.chunks += len(pieces)
        log(f"  {rel_path}: {len(pieces)} chunk(s)")

    for rel_path in known:
        if rel_path not in seen:
            store.forget_document(matter.slug, rel_path)
            summary.removed.append(rel_path)
            log(f"  {rel_path}: removed from the index, file is gone")

    return summary
