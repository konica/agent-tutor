"""Fakes for the LangChain model interfaces, so services are tested without Bedrock."""

import itertools
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


DESCRIPTION_ARGS: dict[str, Any] = {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "year": 2017,
    "doi": "10.48550/arXiv.1706.03762",
    "summary": "Introduces the Transformer, built only on attention. It sets a new state of the art in translation.",
    "proposed_subject_names": ["Deep Learning", "Natural Language Processing", "Machine Translation"],
}


def describe_reply(**changes: Any) -> AIMessage:
    """A model reply calling describe_document with DESCRIPTION_ARGS updated by `changes`."""
    return AIMessage(
        content="",
        tool_calls=[{"name": "describe_document", "args": {**DESCRIPTION_ARGS, **changes}, "id": "call-1"}],
        usage_metadata={"input_tokens": 120, "output_tokens": 40, "total_tokens": 160},
    )


def describing_chat_model(reply: AIMessage | None = None) -> FakeChatModel:
    """Answers every call with the same reply (default: a valid describe_document call)."""
    return FakeChatModel(messages=itertools.repeat(reply or describe_reply()))
