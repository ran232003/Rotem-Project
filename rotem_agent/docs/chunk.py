from __future__ import annotations

import re
from dataclasses import dataclass

TARGET_CHARS = 900
OVERLAP_CHARS = 150
MAX_BLOCK_CHARS = 1400

_PARAGRAPH = re.compile(r"\n\s*\n+")
_SENTENCE = re.compile(r"(?<=[.!?׃])\s+")


@dataclass(frozen=True)
class Chunk:
    """A retrievable passage.

    `start` and `end` bound the passage's own content in the source text and are
    what a citation should point at. `text` may additionally carry a short
    lead-in copied from the previous chunk, so that a clause split across a
    boundary is still readable in whichever half is retrieved.
    """

    index: int
    text: str
    start: int
    end: int


def chunk_text(
    text: str,
    *,
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> list[Chunk]:
    blocks = _blocks(text, max_chars=max(target_chars, MAX_BLOCK_CHARS))
    if not blocks:
        return []

    chunks: list[Chunk] = []
    current: list[tuple[int, int]] = []

    def flush() -> None:
        if not current:
            return
        start, end = current[0][0], current[-1][1]
        body = text[start:end].strip()
        if not body:
            current.clear()
            return
        lead = _lead_in(text, start, overlap_chars) if chunks else ""
        chunks.append(
            Chunk(index=len(chunks), text=(lead + body).strip(), start=start, end=end)
        )
        current.clear()

    for block in blocks:
        current.append(block)
        if current[-1][1] - current[0][0] >= target_chars:
            flush()
    flush()
    return chunks


def _blocks(text: str, *, max_chars: int) -> list[tuple[int, int]]:
    """Paragraph spans, with anything oversized split at sentence boundaries."""
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in _PARAGRAPH.finditer(text):
        spans.append((cursor, match.start()))
        cursor = match.end()
    spans.append((cursor, len(text)))

    result: list[tuple[int, int]] = []
    for start, end in spans:
        if not text[start:end].strip():
            continue
        if end - start <= max_chars:
            result.append((start, end))
            continue
        result.extend(_split_long(text, start, end, max_chars))
    return result


def _split_long(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    cursor = start
    for match in _SENTENCE.finditer(text, start, end):
        if match.start() - cursor >= max_chars:
            pieces.append((cursor, match.start()))
            cursor = match.end()
    if cursor < end:
        pieces.append((cursor, end))

    # A wall of text with no sentence breaks still has to be cut somewhere.
    final: list[tuple[int, int]] = []
    for piece_start, piece_end in pieces:
        while piece_end - piece_start > max_chars:
            cut = _back_to_space(text, piece_start + max_chars, piece_start)
            final.append((piece_start, cut))
            piece_start = cut
        final.append((piece_start, piece_end))
    return final


def _back_to_space(text: str, position: int, floor: int) -> int:
    for index in range(position, floor, -1):
        if text[index - 1].isspace():
            return index
    return position


def _lead_in(text: str, start: int, overlap_chars: int) -> str:
    if overlap_chars <= 0 or start <= 0:
        return ""
    begin = _forward_to_space(text, max(0, start - overlap_chars), start)
    lead = text[begin:start].strip()
    return f"{lead} " if lead else ""


def _forward_to_space(text: str, position: int, ceiling: int) -> int:
    for index in range(position, ceiling):
        if text[index].isspace():
            return index + 1
    return position
