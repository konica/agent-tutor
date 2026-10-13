"""Graph state and runtime context. The token lives only in the context (ADR 0007): never state, never traced."""

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from smart_tutor.shared.domain.citation import Citation
from smart_tutor.tutoring.application import (
    GUARD_MESSAGE,
    LIMITED_DECLINE,
    NO_DOCUMENTS_DECLINE,
    GuardReason,
    HistoryTurn,
    RetrievedChunk,
)


@dataclass
class AgentContext:
    access_token: str = field(repr=False)


# "limited": a limited search that doesn't cover the question (US-4c); "no_documents": nothing is readable (US-3);
# "guard": a guard tripped (US-6, D29); the server sends it as `replace`.
DeclineCode = Literal["limited", "no_documents", "guard"]
# What the learner reads for each decline (the server's decline event, the eval target's answer).
DECLINE_MESSAGES: dict[DeclineCode, str] = {
    "limited": LIMITED_DECLINE,
    "no_documents": NO_DOCUMENTS_DECLINE,
    "guard": GUARD_MESSAGE,
}


class AskState(TypedDict, total=False):
    question: str
    document_ids: list[str] | None
    history: list[HistoryTurn]  # earlier turns, oldest first (question and answer text only; ADR 0015)
    chunks: list[RetrievedChunk]
    no_documents: bool  # the readable set is empty: the learner has no ready, non-archived document
    answer: str
    citations: list[Citation]
    decline: DeclineCode
    guard: GuardReason  # why a guard tripped; logs and traces only
