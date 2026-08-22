"""Counting what a draft actually costs.

One reply is not one model call. The asks are extracted first, in a separate
call, and only then is the reply written, so reporting the reply's usage alone
understated the bill by an entire call. The meter therefore sits around the
client rather than at either call site, and anything routed through it is
counted whether or not the caller remembered it existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rotem_agent.llm.base import LlmResponse, LlmUsage


@dataclass(frozen=True)
class CallRecord:
    """One model call. `purpose` is what it was for, not which method ran."""

    purpose: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0


class MeteredClient:
    """An LlmClient that records the usage of every call it forwards."""

    def __init__(self, inner: Any, purpose: str = "draft") -> None:
        self._inner = inner
        self._purpose = purpose
        self.calls: list[CallRecord] = []

    def labelled(self, purpose: str) -> "MeteredClient":
        """A view that tags its calls differently but shares the same tally."""
        twin = MeteredClient(self._inner, purpose)
        twin.calls = self.calls
        return twin

    @property
    def model(self) -> str:
        return self._inner.model

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
    ) -> LlmResponse:
        response = self._inner.complete_json(
            system=system, user=user, schema=schema, temperature=temperature
        )
        usage = response.usage
        self.calls.append(
            CallRecord(
                purpose=self._purpose,
                model=response.model,
                input_tokens=(usage.input_tokens or 0) if usage else 0,
                output_tokens=(usage.output_tokens or 0) if usage else 0,
                thinking_tokens=(usage.thinking_tokens or 0) if usage else 0,
                cached_tokens=(usage.cached_tokens or 0) if usage else 0,
            )
        )
        return response

    @property
    def usage(self) -> LlmUsage | None:
        """Everything spent so far, or None if no call reported usage."""
        if not self.calls:
            return None
        return LlmUsage(
            input_tokens=sum(call.input_tokens for call in self.calls),
            output_tokens=sum(call.output_tokens for call in self.calls),
            thinking_tokens=sum(call.thinking_tokens for call in self.calls),
            cached_tokens=sum(call.cached_tokens for call in self.calls),
        )
