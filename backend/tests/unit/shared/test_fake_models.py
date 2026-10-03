"""The fakes stand in for Bedrock models in service tests: scripted replies, tool calls, structured output."""

from langchain_core.messages import AIMessage
from pydantic import BaseModel

from fakes import fake_chat_model, fake_embeddings
from smart_tutor.shared.domain.token_usage import TokenUsage


class Note(BaseModel):
    title: str


async def test_scripted_reply_carries_usage() -> None:
    usage = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    model = fake_chat_model(AIMessage("hello there", usage_metadata=usage))

    reply = await model.ainvoke("hi")

    assert reply.content == "hello there"
    assert TokenUsage.from_usage_metadata(reply.usage_metadata) == TokenUsage(10, 2)


async def test_structured_output_parses_a_scripted_tool_call() -> None:
    call = {"name": "Note", "args": {"title": "Tenses"}, "id": "t1"}
    model = fake_chat_model(AIMessage("", tool_calls=[call]))

    assert await model.with_structured_output(Note).ainvoke("summarize") == Note(title="Tenses")


def test_fake_embeddings_are_deterministic() -> None:
    embeddings = fake_embeddings(dimension=4)

    assert embeddings.embed_query("chunk") == embeddings.embed_documents(["chunk"])[0]
    assert len(embeddings.embed_query("chunk")) == 4
