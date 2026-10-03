"""M0 check: the configured Bedrock models are reachable and behave as the agent needs (PRD §9.13, §14 M0).

Real calls in us-east-1 through ModelFactory (LangChain models) with your AWS credentials; a run costs well under
a cent. Run: `make bedrock-check`.
"""

import math
from typing import Literal

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.token_usage import TokenUsage

pytestmark = pytest.mark.bedrock


@tool
def decline(reason: Literal["off_topic", "not_in_documents"]) -> str:
    """Decline when the learner's documents cannot answer the question."""
    return reason


@tool
def lookup(rule: str) -> str:
    """Look up a grammar rule."""
    return "have/has + past participle"


class Example(BaseModel):
    sentence: str
    tense: str


class Lesson(BaseModel):
    """A lesson about one grammar topic."""

    topic: str
    examples: list[Example]


@pytest.fixture(scope="module")
def factory() -> ModelFactory:
    return ModelFactory(Settings())


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (math.hypot(*a) * math.hypot(*b))


async def test_nova_embeddings_sync_index_and_query(factory: ModelFactory) -> None:
    embeddings = factory.embedding()

    docs = await embeddings.aembed_documents(
        ["The present perfect links a past action to the present.", "Photosynthesis turns light into sugar."]
    )
    query = await embeddings.aembed_query("When do I use the present perfect?")

    assert [len(v) for v in [*docs, query]] == [1024] * 3
    assert cosine(query, docs[0]) > cosine(query, docs[1])


async def test_agent_streams_text_and_ends_with_usage(factory: ModelFactory) -> None:
    chunks = [c async for c in factory.chat(ChatRole.AGENT).astream("Count from one to five.")]

    assert sum(1 for c in chunks if c.text) > 1
    usage = TokenUsage.from_usage_metadata(sum(chunks[1:], chunks[0]).usage_metadata)
    assert usage.input_tokens > 0 and usage.output_tokens > 0


async def test_agent_streams_a_tool_call(factory: ModelFactory) -> None:
    model = factory.chat(ChatRole.AGENT).bind_tools([decline])
    messages = [
        SystemMessage("You answer only grammar questions. For anything else, call decline."),
        HumanMessage("What is the best pizza topping?"),
    ]

    chunks = [c async for c in model.astream(messages)]
    message = sum(chunks[1:], chunks[0])

    assert isinstance(message, AIMessage)
    assert [(c["name"], c["args"]) for c in message.tool_calls] == [("decline", {"reason": "off_topic"})]


async def test_agent_answers_from_a_tool_result(factory: ModelFactory) -> None:
    model = factory.chat(ChatRole.AGENT).bind_tools([lookup])
    messages: list[BaseMessage] = [HumanMessage("Use the lookup tool for the present perfect, then explain it.")]
    first = await model.ainvoke(messages)
    assert isinstance(first, AIMessage) and first.tool_calls, "expected the model to call lookup"

    messages += [first, *(ToolMessage(lookup.invoke(c["args"]), tool_call_id=c["id"]) for c in first.tool_calls)]
    final = await model.ainvoke(messages)

    assert "participle" in final.text.lower()


@pytest.mark.parametrize("role", [ChatRole.AGENT, ChatRole.JUDGE])
async def test_structured_output_with_nested_schema(factory: ModelFactory, role: ChatRole) -> None:
    lesson = await (
        factory.chat(role)
        .with_structured_output(Lesson)
        .ainvoke("Make a lesson on the present perfect with two example sentences.")
    )

    assert isinstance(lesson, Lesson) and len(lesson.examples) >= 2


async def test_cached_system_prompt_counts_as_input(factory: ModelFactory) -> None:
    # The `us.` profile may route the two calls to different regions, so the second can write the cache again
    # instead of reading it; either way the cached tokens must be part of input_tokens.
    rules = "You are a grammar tutor. " + "Always cite the page you used. " * 300
    system = SystemMessage(content=[{"type": "text", "text": rules}, {"cachePoint": {"type": "default"}}])
    model = factory.chat(ChatRole.AGENT)

    for _ in range(2):
        reply = await model.ainvoke([system, HumanMessage("Say hi.")])
        assert reply.usage_metadata is not None
        details = reply.usage_metadata.get("input_token_details", {})
        cached = details.get("cache_read", 0) + details.get("cache_creation", 0)
        assert cached > 1000
        assert TokenUsage.from_usage_metadata(reply.usage_metadata).input_tokens > cached
