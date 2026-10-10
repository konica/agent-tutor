"""Graph state and runtime context. The token lives only in the context (ADR 0007): never state, never traced."""

from dataclasses import dataclass, field
from typing import TypedDict

from smart_tutor.shared.domain.citation import Citation
from smart_tutor.tutoring.application import RetrievedChunk


@dataclass
class AgentContext:
    access_token: str = field(repr=False)


class AskState(TypedDict, total=False):
    question: str
    document_ids: list[str] | None
    chunks: list[RetrievedChunk]
    answer: str
    citations: list[Citation]
    declined: bool
