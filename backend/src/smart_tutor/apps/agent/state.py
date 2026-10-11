"""Graph state and runtime context. The token lives only in the context (ADR 0007): never state, never traced."""

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from smart_tutor.shared.domain.citation import Citation
from smart_tutor.tutoring.application import RetrievedChunk


@dataclass
class AgentContext:
    access_token: str = field(repr=False)


# "limited": a limited search that doesn't cover the question (US-4c); "no_documents": nothing is readable (US-3).
DeclineCode = Literal["limited", "no_documents"]


class AskState(TypedDict, total=False):
    question: str
    document_ids: list[str] | None
    chunks: list[RetrievedChunk]
    no_documents: bool  # the readable set is empty: the learner has no ready, non-archived document
    answer: str
    citations: list[Citation]
    decline: DeclineCode
