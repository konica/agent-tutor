"""Search the learner's chunks (PRD §9.2 step 2, §9.3). Every result passes `can_read`.

With document ids (a conversation limited to its documents, US-4c) only those of the caller's readable documents.
"""

import uuid
from collections.abc import Callable, Sequence

from langchain_core.embeddings import Embeddings

from smart_tutor.knowledge.domain.errors import InvalidSearchError
from smart_tutor.knowledge.domain.search import ChunkHit
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import DocumentId, UserId

MAX_QUERY_CHARS = 4000
MAX_K = 20
MAX_DOCUMENT_IDS = 200


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


class SearchService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], embeddings: Embeddings) -> None:
        self._uow = uow
        self._embeddings = embeddings

    def search(
        self, user_id: UserId, query: str, k: int = 5, document_ids: Sequence[str] | None = None
    ) -> list[ChunkHit]:
        query = query.strip()
        if not query or len(query) > MAX_QUERY_CHARS:
            raise InvalidSearchError(f"A query has 1 to {MAX_QUERY_CHARS} characters")
        if not 1 <= k <= MAX_K:
            raise InvalidSearchError(f"k is 1 to {MAX_K}")
        limit: list[DocumentId] | None = None
        if document_ids is not None:
            if len(document_ids) > MAX_DOCUMENT_IDS:
                raise InvalidSearchError(f"At most {MAX_DOCUMENT_IDS} document ids")
            limit = [DocumentId(i) for i in document_ids if _is_uuid(i)]  # unreadable or malformed ids match nothing
            if not limit:
                return []
        embedding = self._embeddings.embed_query(query)  # outside the transaction
        with self._uow() as tx:
            return tx.chunks.search(user_id, embedding, k, limit)
