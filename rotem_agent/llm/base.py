"""Provider-agnostic surface for the model calls.

Everything Gemini-specific stays behind this so the Phase 0 bake-off can swap in
Claude or GPT without touching application code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol


class LlmError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlmUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class LlmResponse:
    data: dict[str, Any]
    model: str
    usage: LlmUsage | None = None


class LlmClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
    ) -> LlmResponse: ...


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_payload(text: str) -> dict[str, Any]:
    """Structured output should already be clean JSON, but stay tolerant."""
    if not text or not text.strip():
        raise LlmError("Model returned an empty response.")

    candidates = [text]
    if fenced := _FENCE.search(text):
        candidates.insert(0, fenced.group(1))
    if (start := text.find("{")) != -1 and (end := text.rfind("}")) > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise LlmError(f"Could not parse JSON from model response: {text[:300]}")
