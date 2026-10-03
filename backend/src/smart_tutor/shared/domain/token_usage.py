"""Normalized token usage returned by every model call."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts cannot be negative")

    @classmethod
    def from_usage_metadata(cls, usage: Mapping[str, Any] | None) -> "TokenUsage":
        """From a LangChain `AIMessage.usage_metadata`; Bedrock's input count there already includes cached tokens."""
        if not usage:
            return cls()
        return cls(input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0))

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )
