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
    learner_subjects: dict[str, str]  # all of the learner's subjects (id → their name); detection picks from them
    subject_ids: list[str]  # the thread's 1–3 subjects, set by resolve_subjects
    subject_names: list[str]  # the learner's names for the thread's subjects, for the system prompt
    chunks: list[RetrievedChunk]
    answer: str
    citations: list[Citation]
