"""Reading scanned certificates.

Most immigration paperwork is a photograph of paper: birth certificates, old
passports, apostilles, ministry letters. The extractor detects those and refuses
them rather than indexing an empty file, which is safe but leaves the agent
answering as though the document were absent.

The transcription is done by the same multimodal model already drafting the
replies, rather than a separate OCR vendor. It reads Hebrew and Latin script in
one pass, needs no second API key or data-processing agreement, and its cost
lands in the same usage log as everything else.

The danger is specific and worth stating plainly. A model asked to transcribe
will tend to tidy what it reads, and the whole purpose of the certificate audit
is to find discrepancies between a name on a birth certificate and the same name
on a passport. A transcription that silently normalises one spelling to the other
destroys exactly the evidence being looked for. So the instruction demands
verbatim copying, the temperature is zero, and everything read this way is
marked as machine-read so a discrepancy is never asserted from it without a
human checking the original.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from rotem_agent.llm.base import LlmUsage

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}
PDF_MIME = "application/pdf"

# The SDK accepts larger payloads through the Files API, which is a separate
# upload-and-poll flow. Refusing loudly beats a confusing transport error.
MAX_INLINE_BYTES = 18 * 1024 * 1024

_ILLEGIBLE = "[לא קריא]"

_INSTRUCTION = f"""Transcribe this document exactly as it appears.

This is a legal document in an Israeli immigration file. The transcription is
used to detect discrepancies between documents, such as a name spelled one way
on a birth certificate and another way on a passport. Tidying the text destroys
the evidence, so:

- Copy every name, date, number and place exactly as written, including spelling
  that looks wrong or inconsistent. Do not correct, normalise, translate or
  transliterate anything.
- Keep the original script. A name written in Latin letters stays in Latin
  letters; a name in Cyrillic stays in Cyrillic.
- Where a character or word cannot be read, write {_ILLEGIBLE} in its place.
  Never guess a name, a date or a number.
- Transcribe stamps, seals, apostille text and handwritten annotations too, each
  on its own line prefixed with its kind, for example "חתימה:" or "חותמת:".
- Give the document's own layout order. Do not summarise, explain, comment or
  add anything that is not on the page.

Output the transcription only."""


@dataclass
class OcrResult:
    text: str
    usage: LlmUsage | None = None
    model: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())

    @property
    def illegible_marks(self) -> int:
        return self.text.count(_ILLEGIBLE)


class Ocr(Protocol):
    @property
    def name(self) -> str: ...

    def read(self, path: Path, pages: int = 0) -> OcrResult: ...


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_MIME


def mime_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return PDF_MIME
    return IMAGE_MIME.get(suffix)


class GeminiOcr:
    """Verbatim transcription through the Gemini multimodal API."""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model or os.getenv("GEMINI_OCR_MODEL", "").strip() or os.getenv(
            "GEMINI_MODEL", "gemini-3.6-flash"
        ).strip()

    @property
    def name(self) -> str:
        return self._model

    def read(self, path: Path, pages: int = 0) -> OcrResult:
        from google.genai import types

        mime = mime_for(path)
        if mime is None:
            return OcrResult(text="", warnings=[f"no OCR support for {path.suffix}"])

        size = path.stat().st_size
        if size > MAX_INLINE_BYTES:
            return OcrResult(
                text="",
                warnings=[
                    f"{size / 1e6:.1f} MB is too large to send inline; "
                    "split the file or reduce its resolution"
                ],
            )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[
                    types.Part.from_bytes(data=path.read_bytes(), mime_type=mime),
                    _INSTRUCTION,
                ],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )
        except Exception as exc:
            return OcrResult(text="", warnings=[f"OCR failed ({exc})"])

        text = (response.text or "").strip()
        result = OcrResult(text=text, usage=_usage(response), model=self._model)
        if not text:
            result.warnings.append("OCR returned nothing")
        elif pages and len(text) < 40 * pages:
            # Far too little text for the page count means the transcription
            # failed even though the call succeeded.
            result.warnings.append(
                f"OCR produced only {len(text)} characters for {pages} page(s); "
                "check the scan quality"
            )
        if result.illegible_marks:
            result.warnings.append(
                f"{result.illegible_marks} illegible passage(s) marked; "
                "names and dates there must be read from the original"
            )
        return result


def _usage(response: object) -> LlmUsage | None:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return None
    return LlmUsage(
        input_tokens=getattr(metadata, "prompt_token_count", None),
        output_tokens=getattr(metadata, "candidates_token_count", None),
        thinking_tokens=getattr(metadata, "thoughts_token_count", None),
        cached_tokens=getattr(metadata, "cached_content_token_count", None),
    )
