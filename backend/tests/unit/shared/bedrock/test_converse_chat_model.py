"""BedrockConverseChatModel maps the ChatModel port onto Converse requests and responses."""

from typing import Any

import pytest
from pydantic import BaseModel

from fakes.bedrock import FakeBedrockClient, converse_response, throttled
from smart_tutor.shared.adapters.bedrock.converse_chat_model import BedrockConverseChatModel
from smart_tutor.shared.domain.errors import ModelError, ModelOutputError
from smart_tutor.shared.domain.token_usage import TokenUsage
from smart_tutor.shared.ports.chat_model import Message, ToolCall, ToolSpec

DECLINE = ToolSpec("decline", "Decline the question.", {"type": "object", "properties": {"reason": {"type": "string"}}})


def model(client: FakeBedrockClient, **kwargs: Any) -> BedrockConverseChatModel:
    return BedrockConverseChatModel(client, "us.amazon.nova-2-lite-v1:0", **kwargs)  # type: ignore[arg-type]


class Note(BaseModel):
    """A short lesson note."""

    title: str
    score: int


async def test_tool_round_trip_becomes_alternating_turns() -> None:
    client = FakeBedrockClient([converse_response([{"text": "Done."}])])
    call_a, call_b = ToolCall("t1", "search", {"q": "a"}), ToolCall("t2", "search", {"q": "b"})

    await model(client).invoke(
        [
            Message("system", "You are a tutor."),
            Message("user", "Explain tenses."),
            Message("assistant", "", tool_calls=(call_a, call_b)),
            Message("tool", "chunk A", tool_call_id="t1"),
            Message("tool", "chunk B", tool_call_id="t2"),
        ]
    )

    request = client.requests[0]
    assert request["system"] == [{"text": "You are a tutor."}]
    assert [t["role"] for t in request["messages"]] == ["user", "assistant", "user"]
    assert request["messages"][1]["content"] == [
        {"toolUse": {"toolUseId": "t1", "name": "search", "input": {"q": "a"}}},
        {"toolUse": {"toolUseId": "t2", "name": "search", "input": {"q": "b"}}},
    ]
    assert [b["toolResult"]["toolUseId"] for b in request["messages"][2]["content"]] == ["t1", "t2"]


async def test_tool_message_without_call_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="tool_call_id"):
        await model(FakeBedrockClient()).invoke([Message("tool", "chunk")])


async def test_prompt_cache_marks_the_end_of_the_system_prompt() -> None:
    client = FakeBedrockClient([converse_response([{"text": "hi"}])])

    await model(client, prompt_cache=True).invoke([Message("system", "Rules."), Message("user", "hi")])

    assert client.requests[0]["system"] == [{"text": "Rules."}, {"cachePoint": {"type": "default"}}]


def test_params_map_to_inference_config_and_unknown_params_fail_fast() -> None:
    assert model(FakeBedrockClient(), params={"temperature": 0, "max_tokens": 512})._request(
        [Message("user", "hi")], []
    )["inferenceConfig"] == {"temperature": 0, "maxTokens": 512}
    with pytest.raises(ValueError, match="unsupported chat params"):
        model(FakeBedrockClient(), params={"temprature": 0})


async def test_invoke_returns_text_tool_calls_and_usage_including_cached_tokens() -> None:
    content = [{"text": "Let me check."}, {"toolUse": {"toolUseId": "t1", "name": "decline", "input": {"reason": "x"}}}]
    client = FakeBedrockClient([converse_response(content, cacheReadInputTokens=2000, cacheWriteInputTokens=0)])

    result = await model(client).invoke([Message("user", "hi")], [DECLINE])

    assert result.text == "Let me check."
    assert result.tool_calls == [ToolCall("t1", "decline", {"reason": "x"})]
    assert result.usage == TokenUsage(input_tokens=2010, output_tokens=5)
    assert client.requests[0]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "decline"


async def test_stream_yields_text_then_assembled_tool_call_then_usage() -> None:
    events = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Hello"}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": " there"}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"contentBlockStart": {"contentBlockIndex": 1, "start": {"toolUse": {"toolUseId": "t1", "name": "decline"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '{"reas'}}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": 'on": "off_topic"}'}}}},
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": {"usage": {"inputTokens": 30, "outputTokens": 8}, "metrics": {"latencyMs": 100}}},
    ]

    chunks = [c async for c in model(FakeBedrockClient([events])).stream([Message("user", "hi")], [DECLINE])]

    assert "".join(c.text for c in chunks) == "Hello there"
    assert [c.tool_call for c in chunks if c.tool_call] == [ToolCall("t1", "decline", {"reason": "off_topic"})]
    assert chunks[-1].usage == TokenUsage(30, 8)


async def test_stream_error_event_raises_model_error() -> None:
    events = [{"throttlingException": {"message": "slow down"}}]

    with pytest.raises(ModelError, match="slow down"):
        _ = [c async for c in model(FakeBedrockClient([events])).stream([Message("user", "hi")])]


async def test_structured_forces_the_schema_tool_and_validates() -> None:
    tool_use = {"toolUse": {"toolUseId": "t1", "name": "Note", "input": {"title": "Tenses", "score": 3}}}
    client = FakeBedrockClient([converse_response([tool_use])])

    result = await model(client).structured([Message("user", "summarize")], Note)

    assert result.value == Note(title="Tenses", score=3)
    tool_config = client.requests[0]["toolConfig"]
    assert tool_config["toolChoice"] == {"tool": {"name": "Note"}}
    assert tool_config["tools"][0]["toolSpec"]["description"] == "A short lesson note."


@pytest.mark.parametrize(
    "content",
    [
        [{"text": "No tool for you."}],
        [{"toolUse": {"toolUseId": "t1", "name": "Note", "input": {"title": "Tenses"}}}],
    ],
)
async def test_structured_raises_when_the_payload_breaks_the_schema(content: list[dict[str, Any]]) -> None:
    with pytest.raises(ModelOutputError):
        await model(FakeBedrockClient([converse_response(content)])).structured([Message("user", "x")], Note)


async def test_sdk_errors_become_model_errors() -> None:
    with pytest.raises(ModelError, match="ThrottlingException"):
        await model(FakeBedrockClient([throttled()])).invoke([Message("user", "hi")])
