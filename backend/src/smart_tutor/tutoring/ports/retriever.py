"""Search the learner's chunks. The adapter calls the RAG MCP server with the learner's token (PRD §9.3)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk


class Retriever(ABC):
    @abstractmethod
    async def search(self, query: str, k: int = 5, document_ids: Sequence[str] | None = None) -> list[RetrievedChunk]:
        """Nearest chunks first, from all the learner's ready documents or only `document_ids` (US-4c).

        Raises UnauthenticatedError when the token is refused, RetrievalError otherwise."""
