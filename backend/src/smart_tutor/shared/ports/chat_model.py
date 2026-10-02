"""ChatModel port (PRD §9.15). Business code depends on this, never on a vendor SDK or model ID."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from smart_tutor.shared.domain.token_usage import TokenUsage


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = TokenUsage()


@dataclass(frozen=True, slots=True)
class ChatChunk:
    """One streamed piece: a text delta, a completed tool call, or the final usage."""

    text: str = ""
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class StructuredResult[T: BaseModel]:
    value: T
    usage: TokenUsage


class ChatModel(ABC):
    @abstractmethod
    def stream(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> AsyncIterator[ChatChunk]:
        """Stream a response; the last chunk carries the usage."""

    @abstractmethod
    async def invoke(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> ChatResult:
        """Return a complete response."""

    @abstractmethod
    async def structured[T: BaseModel](self, messages: Sequence[Message], schema: type[T]) -> StructuredResult[T]:
        """Return a validated object. Adapters may use a forced tool call (Nova) or native structured output."""
