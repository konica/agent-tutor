"""Search the learner's chunks (PRD §9.2 step 2, §9.3). Every result passes `can_read`."""

import uuid
from collections.abc import Callable, Sequence

from langchain_core.embeddings import Embeddings

from smart_tutor.knowledge.domain.errors import InvalidSearchError
from smart_tutor.knowledge.domain.search import ChunkHit
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import SubjectId, UserId

MAX_QUERY_CHARS = 4000
MAX_SUBJECTS = 100  # all of a learner's subjects, for subject detection (PRD §9.2 step 1)
MAX_K = 20


class SearchService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], embeddings: Embeddings) -> None:
        self._uow = uow
        self._embeddings = embeddings

    def search(self, user_id: UserId, query: str, subject_ids: Sequence[SubjectId], k: int = 5) -> list[ChunkHit]:
        query = query.strip()
        if not query or len(query) > MAX_QUERY_CHARS:
            raise InvalidSearchError(f"A query has 1 to {MAX_QUERY_CHARS} characters")
        if not 1 <= len(subject_ids) <= MAX_SUBJECTS:
            raise InvalidSearchError(f"Search 1 to {MAX_SUBJECTS} subjects")
        for subject_id in subject_ids:
            try:
                uuid.UUID(subject_id)
            except ValueError:
                raise InvalidSearchError("A subject id is a UUID") from None
        if not 1 <= k <= MAX_K:
            raise InvalidSearchError(f"k is 1 to {MAX_K}")
        embedding = self._embeddings.embed_query(query)  # outside the transaction
        with self._uow() as tx:
            return tx.chunks.search(user_id, embedding, subject_ids, k)
