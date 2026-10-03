"""Deterministic fakes for the ChatModel and EmbeddingModel ports."""

from collections.abc import AsyncIterator, Sequence

from pydantic import BaseModel

from smart_tutor.shared.domain.token_usage import TokenUsage
from smart_tutor.shared.ports.chat_model import (
    ChatChunk,
    ChatModel,
    ChatResult,
    Message,
    StructuredResult,
    ToolSpec,
)
from smart_tutor.shared.ports.embedding_model import EmbeddingModel, Embeddings


class FakeChatModel(ChatModel):
    """Returns scripted replies in order and records every call."""

    def __init__(self, replies: Sequence[ChatResult] = (), structured_values: Sequence[BaseModel] = ()) -> None:
        self._replies = list(replies)
        self._structured = list(structured_values)
        self.calls: list[list[Message]] = []

    async def stream(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> AsyncIterator[ChatChunk]:
        result = await self.invoke(messages, tools)
        for word in result.text.split(" "):
            yield ChatChunk(text=word)
        for call in result.tool_calls:
            yield ChatChunk(tool_call=call)
        yield ChatChunk(usage=result.usage)

    async def invoke(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> ChatResult:
        self.calls.append(list(messages))
        return self._replies.pop(0)

    async def structured[T: BaseModel](self, messages: Sequence[Message], schema: type[T]) -> StructuredResult[T]:
        self.calls.append(list(messages))
        return StructuredResult(value=schema.model_validate(self._structured.pop(0).model_dump()), usage=TokenUsage())


class FakeEmbeddingModel(EmbeddingModel):
    """Embeds text as a tiny deterministic vector (character statistics), enough for ranking tests."""

    def __init__(self, dimension: int = 4) -> None:
        self._dimension = dimension

    @property
    def model_id(self) -> str:
        return "fake-embedding"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> Embeddings:
        return Embeddings(vectors=[self._embed(t) for t in texts], usage=TokenUsage(input_tokens=len(texts)))

    async def embed_query(self, text: str) -> Embeddings:
        return Embeddings(vectors=[self._embed(text)], usage=TokenUsage(input_tokens=1))

    def _embed(self, text: str) -> list[float]:
        return [float(sum(ord(c) for c in text[i :: self._dimension])) for i in range(self._dimension)]
