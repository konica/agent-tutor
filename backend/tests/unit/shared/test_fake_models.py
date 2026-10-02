"""The fakes must honor the port contracts, so services tested with them behave like with real adapters."""

from pydantic import BaseModel

from fakes import FakeChatModel, FakeEmbeddingModel
from smart_tutor.shared.domain.token_usage import TokenUsage
from smart_tutor.shared.ports.chat_model import ChatResult, Message


class Note(BaseModel):
    title: str


async def test_stream_ends_with_usage() -> None:
    model = FakeChatModel(replies=[ChatResult(text="hello there", usage=TokenUsage(10, 2))])

    chunks = [c async for c in model.stream([Message(role="user", content="hi")])]

    assert "".join(c.text for c in chunks if c.text) == "hellothere"
    assert chunks[-1].usage == TokenUsage(10, 2)


async def test_structured_returns_validated_schema() -> None:
    model = FakeChatModel(structured_values=[Note(title="Tenses")])

    result = await model.structured([Message(role="user", content="summarize")], Note)

    assert result.value == Note(title="Tenses")


async def test_embeddings_match_declared_dimension(embedding_model: FakeEmbeddingModel) -> None:
    [vector] = await embedding_model.embed_documents(["chunk"])

    assert len(vector) == embedding_model.dimension
    assert await embedding_model.embed_query("chunk") == vector
