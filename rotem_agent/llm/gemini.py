from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

from rotem_agent.llm.base import LlmError, LlmResponse, LlmUsage, parse_json_payload


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
    ) -> LlmResponse:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_schema=schema,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        except Exception as exc:  # SDK raises a variety of transport errors
            raise LlmError(f"Gemini request failed: {exc}") from exc

        return LlmResponse(
            data=parse_json_payload(response.text or ""),
            model=self._model,
            usage=_usage(response),
        )


def _usage(response: Any) -> LlmUsage | None:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return None
    return LlmUsage(
        input_tokens=getattr(metadata, "prompt_token_count", None),
        output_tokens=getattr(metadata, "candidates_token_count", None),
        thinking_tokens=getattr(metadata, "thoughts_token_count", None),
        cached_tokens=getattr(metadata, "cached_content_token_count", None),
    )
