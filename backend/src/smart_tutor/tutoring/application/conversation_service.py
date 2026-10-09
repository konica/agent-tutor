"""Start a thread (PRD §8 US-3) and manage its documents (US-4b, US-4c): it answers from all ready documents."""

import uuid
from collections.abc import Sequence

from smart_tutor.knowledge.application import DocumentService
from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.shared.ports.clock import Clock
from smart_tutor.tutoring.domain.document_used import DELETED_DOCUMENT, DocumentUsed
from smart_tutor.tutoring.domain.errors import DocumentNotAvailableError, NoDocumentsError, ThreadNotFoundError
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.domain.thread_document import ThreadDocument
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

    def start_thread(self, user_id: UserId, question: str | None = None) -> Thread:
        """A new thread owned by the learner, persisted; its title starts as the first question."""
        self.require_documents(user_id)
        thread = Thread.start(ThreadId(str(uuid.uuid4())), user_id, self._clock.now(), title=question)
        self._threads.add(thread)
        return thread

    def rename_thread(self, thread_id: ThreadId, user_id: UserId, title: str) -> Thread:
        """The learner renames their conversation (US-13): trimmed, 1-120 characters; not while archived."""
        thread = self._threads.get_owned(thread_id, user_id)
        if thread is None:
            raise ThreadNotFoundError("Conversation not found")
        self._threads.set_title(thread_id, thread.rename(title))
        return thread

    def record_answer(self, thread_id: ThreadId, user_id: UserId, document_ids: Sequence[DocumentId]) -> None:
        """Add the documents an answer drew on to the thread's documents used (a decline passes none)."""
        self._owned(thread_id, user_id)
        if not document_ids:
            return
        self._threads.add_documents_used(thread_id, list(dict.fromkeys(document_ids)), self._clock.now())

    def documents_used(self, thread_id: ThreadId, user_id: UserId) -> list[DocumentUsed]:
        """The thread's documents in the order they were added; one that no longer exists reads as deleted."""
        self._owned(thread_id, user_id)
        return self._views(user_id, self._threads.documents_used(thread_id))

    def add_documents(
        self, thread_id: ThreadId, user_id: UserId, document_ids: Sequence[DocumentId]
    ) -> list[DocumentUsed]:
        """The learner adds documents to the list (US-4c): each must be their ready, non-archived document
        (`can_read`), or nothing is added."""
        self._owned(thread_id, user_id)
        ids = list(dict.fromkeys(document_ids))
        views = self._documents.documents_by_id(user_id, ids)
        if any((v := views.get(i)) is None or v.state != "ready" or v.archived for i in ids):
            raise DocumentNotAvailableError("Document not found")
        self._threads.add_documents(thread_id, ids, self._clock.now())
        return self._views(user_id, self._threads.documents_used(thread_id))

    def remove_document(self, thread_id: ThreadId, user_id: UserId, document_id: DocumentId) -> None:
        """Take a document off the list; the document and old citations to it are unchanged (US-4c)."""
        self._owned(thread_id, user_id)
        self._threads.remove_document(thread_id, document_id)

    def _owned(self, thread_id: ThreadId, user_id: UserId) -> None:
        if self._threads.get_owned(thread_id, user_id) is None:
            raise ThreadNotFoundError("Conversation not found")

    def _views(self, user_id: UserId, rows: Sequence[ThreadDocument]) -> list[DocumentUsed]:
        views = self._documents.documents_by_id(user_id, [row.document_id for row in rows])
        used: list[DocumentUsed] = []
        for row in rows:
            view = views.get(row.document_id)
            is_used = row.first_used_at is not None
            if view is None:
                used.append(
                    DocumentUsed(
                        row.document_id,
                        row.deleted_title or DELETED_DOCUMENT,
                        (),
                        None,
                        archived=False,
                        deleted=True,
                        added_by=row.added_by,
                        used=is_used,
                    )
                )
            else:
                used.append(
                    DocumentUsed(
                        row.document_id,
                        view.title,
                        view.authors,
                        view.year,
                        archived=view.archived,
                        deleted=False,
                        added_by=row.added_by,
                        used=is_used,
                    )
                )
        return used
