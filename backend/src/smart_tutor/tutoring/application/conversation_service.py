"""Start a thread (PRD §8 US-3): it answers from all of the learner's ready documents."""

import uuid
from collections.abc import Sequence

from smart_tutor.knowledge.application import DocumentService
from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.shared.ports.clock import Clock
from smart_tutor.tutoring.domain.document_used import DELETED_DOCUMENT, DocumentUsed
from smart_tutor.tutoring.domain.errors import NoDocumentsError, ThreadNotFoundError
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository


class ConversationService:
    def __init__(self, threads: ThreadRepository, documents: DocumentService, clock: Clock) -> None:
        self._threads = threads
        self._documents = documents
        self._clock = clock

    def require_documents(self, user_id: UserId) -> None:
        """No ready, non-archived document → "Upload a document first"."""
        if not self._documents.has_ready_documents(user_id):
            raise NoDocumentsError("Upload a document first")

    def start_thread(self, user_id: UserId) -> Thread:
        """A new thread owned by the learner, persisted."""
        self.require_documents(user_id)
        thread = Thread.start(ThreadId(str(uuid.uuid4())), user_id, self._clock.now())
        self._threads.add(thread)
        return thread

    def record_answer(self, thread_id: ThreadId, user_id: UserId, document_ids: Sequence[DocumentId]) -> None:
        """Add the documents an answer drew on to the thread's documents used (a decline passes none)."""
        if self._threads.get_owned(thread_id, user_id) is None:
            raise ThreadNotFoundError("Conversation not found")
        if not document_ids:
            return
        self._threads.add_documents_used(thread_id, list(dict.fromkeys(document_ids)), self._clock.now())

    def keep_deleted_title(self, user_id: UserId, document_id: DocumentId, title: str) -> None:
        """Called by the document delete before it commits, so documents used keep the title (US-10c)."""
        self._threads.keep_deleted_title(user_id, document_id, title)

    def documents_used(self, thread_id: ThreadId, user_id: UserId) -> list[DocumentUsed]:
        """The thread's documents in order of first use; one that no longer exists reads as deleted."""
        if self._threads.get_owned(thread_id, user_id) is None:
            raise ThreadNotFoundError("Conversation not found")
        rows = self._threads.documents_used(thread_id)
        views = self._documents.documents_by_id(user_id, [row.document_id for row in rows])
        used: list[DocumentUsed] = []
        for row in rows:
            view = views.get(row.document_id)
            if view is None:
                used.append(
                    DocumentUsed(
                        row.document_id, row.deleted_title or DELETED_DOCUMENT, (), None, archived=False, deleted=True
                    )
                )
            else:
                used.append(
                    DocumentUsed(
                        row.document_id, view.title, view.authors, view.year, archived=view.archived, deleted=False
                    )
                )
        return used
