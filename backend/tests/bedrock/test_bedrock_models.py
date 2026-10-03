"""M0 check: the configured Bedrock models are reachable and behave as the adapters expect (PRD §9.13, §13 M0).

Real calls in us-east-1 with your AWS credentials; a run costs well under a cent. Run: `make bedrock-check`.
"""

import math

import pytest
from pydantic import BaseModel

from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.chat_model import Message, ToolSpec

pytestmark = pytest.mark.bedrock

DECLINE = ToolSpec(
    "decline",
    "Decline when the learner's documents cannot answer the question.",
    {"type": "object", "properties": {"reason": {"type": "string", "enum": ["off_topic", "not_in_documents"]}}},
)


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
    model = factory.embedding()

    docs = await model.embed_documents(
        ["The present perfect links a past action to the present.", "Photosynthesis turns light into sugar."]
    )
    query = await model.embed_query("When do I use the present perfect?")

    assert [len(v) for v in docs.vectors + query.vectors] == [model.dimension] * 3 == [1024] * 3
    assert docs.usage.input_tokens > 0 and query.usage.input_tokens > 0
    assert cosine(query.vectors[0], docs.vectors[0]) > cosine(query.vectors[0], docs.vectors[1])


async def test_agent_streams_text_and_ends_with_usage(factory: ModelFactory) -> None:
    chunks = [c async for c in factory.chat(ChatRole.AGENT).stream([Message("user", "Count from one to five.")])]

    assert sum(1 for c in chunks if c.text) > 1
    assert chunks[-1].usage is not None and chunks[-1].usage.output_tokens > 0


async def test_agent_streams_a_tool_call(factory: ModelFactory) -> None:
    messages = [
        Message("system", "You answer only grammar questions. For anything else, call decline."),
        Message("user", "What is the best pizza topping?"),
    ]

    calls = [c.tool_call async for c in factory.chat(ChatRole.AGENT).stream(messages, [DECLINE]) if c.tool_call]

    assert [(c.name, c.arguments) for c in calls] == [("decline", {"reason": "off_topic"})]


async def test_agent_accepts_a_tool_round_trip(factory: ModelFactory) -> None:
    rule = {"type": "object", "properties": {"rule": {"type": "string"}}}
    lookup = ToolSpec("lookup", "Look up a grammar rule.", rule)
    question = Message("user", "Use the lookup tool for the present perfect, then explain.")
    model = factory.chat(ChatRole.AGENT)
    first = await model.invoke([question], [lookup])
    assert first.tool_calls, "expected the model to call lookup"

    final = await model.invoke(
        [
            question,
            Message("assistant", first.text, tool_calls=tuple(first.tool_calls)),
            *(Message("tool", "have/has + past participle", tool_call_id=c.id) for c in first.tool_calls),
        ],
        [lookup],
    )

    assert "participle" in final.text.lower()


@pytest.mark.parametrize("role", [ChatRole.AGENT, ChatRole.JUDGE])
async def test_structured_output_with_nested_schema(factory: ModelFactory, role: ChatRole) -> None:
    result = await factory.chat(role).structured(
        [Message("user", "Make a lesson on the present perfect with two example sentences.")], Lesson
    )

    assert len(result.value.examples) >= 2
    assert result.usage.output_tokens > 0


async def test_cached_system_prompt_still_counts_as_input(factory: ModelFactory) -> None:
    system = Message("system", "You are a grammar tutor. " + "Always cite the page you used. " * 300)
    model = factory.chat(ChatRole.AGENT)

    first = await model.invoke([system, Message("user", "Say hi.")])
    second = await model.invoke([system, Message("user", "Say hi.")])

    assert first.usage.input_tokens > 1000
    assert second.usage.input_tokens == first.usage.input_tokens
