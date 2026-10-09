"""In-memory threads and a fake retriever."""

import copy
import dataclasses
from collections.abc import Sequence
from datetime import datetime

from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.domain.thread_document import ThreadDocument
from smart_tutor.tutoring.ports.retriever import Retriever
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository


class InMemoryThreads(ThreadRepository):
    def __init__(self) -> None:
        self.threads: dict[str, Thread] = {}
        self.documents_used_rows: dict[str, list[ThreadDocument]] = {}

    def add(self, thread: Thread) -> None:
        self.threads[thread.thread_id] = copy.deepcopy(thread)

    def get_owned(self, thread_id: ThreadId, user_id: UserId) -> Thread | None:
        found = self.threads.get(thread_id)
        return copy.deepcopy(found) if found and found.is_owned_by(user_id) else None

    def set_title(self, thread_id: ThreadId, title: str) -> None:
        self.threads[thread_id].title = title

    def add_documents_used(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        rows = self.documents_used_rows.setdefault(thread_id, [])
        for document_id in document_ids:
            i = next((i for i, row in enumerate(rows) if row.document_id == document_id), None)
            if i is None:
                rows.append(ThreadDocument(thread_id, document_id, "answer", at, first_used_at=at))
            elif rows[i].first_used_at is None:
                rows[i] = dataclasses.replace(rows[i], first_used_at=at)

    def add_documents(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        rows = self.documents_used_rows.setdefault(thread_id, [])
        for document_id in document_ids:
            if all(row.document_id != document_id for row in rows):
                rows.append(ThreadDocument(thread_id, document_id, "learner", at))

    def remove_document(self, thread_id: ThreadId, document_id: DocumentId) -> None:
        rows = self.documents_used_rows.get(thread_id, [])
        self.documents_used_rows[thread_id] = [row for row in rows if row.document_id != document_id]

    def documents_used(self, thread_id: ThreadId) -> list[ThreadDocument]:
        return list(self.documents_used_rows.get(thread_id, []))


class FakeRetriever(Retriever):
    def __init__(self, chunks: list[RetrievedChunk] | None = None, error: Exception | None = None) -> None:
        self._chunks = chunks or []
        self._error = error
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        self.calls.append((query, k))
        if self._error is not None:
            raise self._error
        return list(self._chunks)
