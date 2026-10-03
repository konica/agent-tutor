"""Fakes for the LangChain model interfaces, so services are tested without Bedrock."""

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool


class FakeChatModel(GenericFakeChatModel):
    """Replies with scripted `AIMessage`s in order (text, tool calls, usage); accepts tools.

    `with_structured_output` works on a scripted reply that calls the schema's tool.
    """

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        return self


def fake_chat_model(*replies: AIMessage) -> FakeChatModel:
    return FakeChatModel(messages=iter(replies))


def fake_embeddings(dimension: int = 8) -> DeterministicFakeEmbedding:
    """Same text, same vector; different texts get unrelated vectors."""
    return DeterministicFakeEmbedding(size=dimension)
