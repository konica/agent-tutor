"""Search the learner's chunks. The adapter calls the RAG MCP server with the learner's token (PRD §9.3)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk


class Retriever(ABC):
    @abstractmethod
    async def search(self, query: str, subject_ids: Sequence[SubjectId], k: int = 5) -> list[RetrievedChunk]:
        """Nearest chunks first. Raises UnauthenticatedError when the token is refused, RetrievalError otherwise."""
