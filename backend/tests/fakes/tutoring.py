"""In-memory threads and a fake retriever."""

import copy
from collections.abc import Sequence

from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.ports.retriever import Retriever
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository


class InMemoryThreads(ThreadRepository):
    def __init__(self) -> None:
        self.threads: dict[str, Thread] = {}

    def add(self, thread: Thread) -> None:
        self.threads[thread.thread_id] = copy.deepcopy(thread)

    def get_owned(self, thread_id: ThreadId, user_id: UserId) -> Thread | None:
        found = self.threads.get(thread_id)
        return copy.deepcopy(found) if found and found.is_owned_by(user_id) else None


class FakeRetriever(Retriever):
    def __init__(self, chunks: list[RetrievedChunk] | None = None, error: Exception | None = None) -> None:
        self._chunks = chunks or []
        self._error = error
        self.calls: list[tuple[str, list[SubjectId], int]] = []

    async def search(self, query: str, subject_ids: Sequence[SubjectId], k: int = 5) -> list[RetrievedChunk]:
        self.calls.append((query, list(subject_ids), k))
        if self._error is not None:
            raise self._error
        return list(self._chunks)
