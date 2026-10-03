"""ChatModel over the Bedrock Converse API (Nova 2 Lite for the agent, Qwen3 for the judge).

boto3 is synchronous, so each call (and each streamed event) runs in a worker thread. Every call is a LangSmith
`llm` run with its token usage (a no-op unless LANGSMITH_TRACING is on).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from botocore.exceptions import BotoCoreError, ClientError
from langsmith import traceable
from pydantic import BaseModel, ValidationError

from smart_tutor.shared.domain.errors import ModelError, ModelOutputError
from smart_tutor.shared.domain.token_usage import TokenUsage
from smart_tutor.shared.ports.chat_model import (
    ChatChunk,
    ChatModel,
    ChatResult,
    Message,
    StructuredResult,
    ToolCall,
    ToolSpec,
)

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

# ModelConfig.params name -> Converse inferenceConfig name.
_INFERENCE_PARAMS = {"temperature": "temperature", "max_tokens": "maxTokens", "top_p": "topP"}


class BedrockConverseChatModel(ChatModel):
    def __init__(
        self,
        client: "BedrockRuntimeClient",
        model_id: str,
        params: Mapping[str, float | int | str] | None = None,
        prompt_cache: bool = False,
    ) -> None:
        unknown = set(params or {}) - set(_INFERENCE_PARAMS)
        if unknown:
            raise ValueError(f"unsupported chat params for {model_id}: {sorted(unknown)}")
        self._client = client
        self._model_id = model_id
        self._inference = {_INFERENCE_PARAMS[k]: v for k, v in (params or {}).items()}
        self._prompt_cache = prompt_cache

    async def stream(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> AsyncIterator[ChatChunk]:
        async for chunk in self._traced(self._stream, reduce_fn=_trace_stream)(messages, tools):
            yield chunk

    async def invoke(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> ChatResult:
        result: ChatResult = await self._traced(self._converse)(messages, tools)
        return result

    async def structured[T: BaseModel](self, messages: Sequence[Message], schema: type[T]) -> StructuredResult[T]:
        tool = ToolSpec(
            name=schema.__name__,
            description=(schema.__doc__ or f"Return the {schema.__name__}.").strip(),
            parameters=schema.model_json_schema(),
        )
        result: ChatResult = await self._traced(self._converse)(messages, [tool], forced_tool=tool.name)
        if not result.tool_calls:
            raise ModelOutputError(f"{self._model_id} returned no {tool.name} tool call")
        try:
            return StructuredResult(value=schema.model_validate(result.tool_calls[0].arguments), usage=result.usage)
        except ValidationError as e:
            raise ModelOutputError(f"{self._model_id} returned an invalid {tool.name}: {e}") from e

    def _traced[F: Callable[..., Any]](
        self, fn: F, reduce_fn: Callable[[Sequence[Any]], dict[str, Any]] | None = None
    ) -> F:
        traced = traceable(
            run_type="llm",
            name=f"bedrock:{self._model_id}",
            metadata={"ls_provider": "amazon_bedrock", "ls_model_name": self._model_id},
            process_inputs=_trace_inputs,
            process_outputs=_trace_outputs,
            reduce_fn=reduce_fn,
        )(fn)
        return cast(F, traced)  # same call signature; traceable only adds the `langsmith_extra` keyword

    async def _converse(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec], forced_tool: str | None = None
    ) -> ChatResult:
        request = self._request(messages, tools)
        if forced_tool is not None:
            request["toolConfig"]["toolChoice"] = {"tool": {"name": forced_tool}}
        response = await _call(lambda: self._client.converse(**request))
        return _result(response["output"]["message"]["content"], response["usage"])

    async def _stream(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> AsyncIterator[ChatChunk]:
        request = self._request(messages, tools)
        response = await _call(lambda: self._client.converse_stream(**request))
        events: Iterator[Any] = iter(response["stream"])
        tool_blocks: dict[int, dict[str, str]] = {}  # contentBlockIndex -> id, name, partial JSON input
        while (event := await _call(lambda: next(events, None))) is not None:
            if "contentBlockStart" in event:
                start = event["contentBlockStart"]
                if "toolUse" in start["start"]:
                    tool_use = start["start"]["toolUse"]
                    tool_blocks[start["contentBlockIndex"]] = {
                        "id": tool_use["toolUseId"],
                        "name": tool_use["name"],
                        "input": "",
                    }
            elif "contentBlockDelta" in event:
                delta = event["contentBlockDelta"]
                if "text" in delta["delta"]:
                    yield ChatChunk(text=delta["delta"]["text"])
                elif "toolUse" in delta["delta"]:
                    tool_blocks[delta["contentBlockIndex"]]["input"] += delta["delta"]["toolUse"]["input"]
            elif "contentBlockStop" in event:
                block = tool_blocks.pop(event["contentBlockStop"]["contentBlockIndex"], None)
                if block is not None:
                    yield ChatChunk(tool_call=ToolCall(block["id"], block["name"], _parse_arguments(block["input"])))
            elif "metadata" in event:
                yield ChatChunk(usage=_usage(event["metadata"]["usage"]))
            else:
                for error in ("internalServerException", "modelStreamErrorException", "throttlingException"):
                    if error in event:
                        raise ModelError(f"{self._model_id} stream failed: {event[error].get('message', error)}")

    def _request(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> dict[str, Any]:
        system: list[dict[str, Any]] = [{"text": m.content} for m in messages if m.role == "system" and m.content]
        if system and self._prompt_cache:
            system.append({"cachePoint": {"type": "default"}})
        request: dict[str, Any] = {"modelId": self._model_id, "messages": _turns(messages)}
        if system:
            request["system"] = system
        if self._inference:
            request["inferenceConfig"] = self._inference
        if tools:
            request["toolConfig"] = {
                "tools": [
                    {"toolSpec": {"name": t.name, "description": t.description, "inputSchema": {"json": t.parameters}}}
                    for t in tools
                ]
            }
        return request


async def _call[R](fn: Callable[[], R]) -> R:
    """Run a blocking boto3 call in a thread; translate SDK errors so callers never import botocore."""
    try:
        return await asyncio.to_thread(fn)
    except (ClientError, BotoCoreError) as e:
        raise ModelError(str(e)) from e


def _turns(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Map messages to Converse turns: roles must alternate, and tool results travel in a user turn."""
    turns: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            if m.tool_call_id is None:
                raise ValueError("a tool message needs the tool_call_id it answers")
            role = "user"
            blocks: list[dict[str, Any]] = [
                {"toolResult": {"toolUseId": m.tool_call_id, "content": [{"text": m.content}]}}
            ]
        else:
            role = m.role
            blocks = [{"text": m.content}] if m.content else []
            blocks += [{"toolUse": {"toolUseId": c.id, "name": c.name, "input": c.arguments}} for c in m.tool_calls]
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": blocks})
    return turns


def _result(content: Sequence[Mapping[str, Any]], usage: Mapping[str, Any]) -> ChatResult:
    text = "".join(block["text"] for block in content if "text" in block)
    calls = [
        ToolCall(block["toolUse"]["toolUseId"], block["toolUse"]["name"], dict(block["toolUse"]["input"]))
        for block in content
        if "toolUse" in block
    ]
    return ChatResult(text=text, tool_calls=calls, usage=_usage(usage))


def _usage(usage: Mapping[str, Any]) -> TokenUsage:
    # Bedrock leaves cached prompt tokens out of inputTokens; count them so usage matches Bedrock's totals.
    cached = usage.get("cacheReadInputTokens", 0) + usage.get("cacheWriteInputTokens", 0)
    return TokenUsage(input_tokens=usage["inputTokens"] + cached, output_tokens=usage["outputTokens"])


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        arguments = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        raise ModelOutputError(f"tool call input is not JSON: {raw[:200]}") from e
    if not isinstance(arguments, dict):
        raise ModelOutputError("tool call input is not a JSON object")
    return arguments


def _trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    messages = [
        {"role": m.role, "content": m.content}
        | ({"tool_call_id": m.tool_call_id} if m.tool_call_id else {})
        | ({"tool_calls": _call_dicts(m.tool_calls)} if m.tool_calls else {})
        for m in inputs.get("messages", ())
    ]
    return {"messages": messages, "tools": [t.name for t in inputs.get("tools", ())]}


def _trace_stream(chunks: Sequence[ChatChunk]) -> dict[str, Any]:
    """Fold streamed chunks into the same trace output as `invoke`."""
    usage = next((c.usage for c in reversed(chunks) if c.usage is not None), TokenUsage())
    calls = [c.tool_call for c in chunks if c.tool_call is not None]
    return _trace_outputs(ChatResult(text="".join(c.text for c in chunks), tool_calls=calls, usage=usage))


def _trace_outputs(output: Any) -> dict[str, Any]:
    """LangSmith output for an `llm` run; `usage_metadata` lets it show tokens and cost."""
    if not isinstance(output, ChatResult):
        return output if isinstance(output, dict) else {"output": output}
    return {
        "content": output.text,
        "tool_calls": _call_dicts(output.tool_calls),
        "usage_metadata": {
            "input_tokens": output.usage.input_tokens,
            "output_tokens": output.usage.output_tokens,
            "total_tokens": output.usage.total_tokens,
        },
    }


def _call_dicts(calls: Sequence[ToolCall]) -> list[dict[str, Any]]:
    return [{"id": c.id, "name": c.name, "args": c.arguments} for c in calls]
