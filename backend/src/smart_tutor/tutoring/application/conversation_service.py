"""Start a thread (PRD §8 US-3) and manage its documents and search scope (US-4b, US-4c)."""

import uuid
from collections.abc import Sequence

from smart_tutor.knowledge.application import DocumentService
from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.shared.ports.clock import Clock
from smart_tutor.tutoring.domain.document_used import DELETED_DOCUMENT, DocumentUsed
from smart_tutor.tutoring.domain.errors import (
    DocumentNotAvailableError,
    NoDocumentsError,
    ThreadArchivedError,
    ThreadNotFoundError,
)
from smart_tutor.tutoring.domain.thread import SearchScope, Thread, ThreadStatus
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

    def require_readable(self, user_id: UserId, document_id: DocumentId) -> None:
        """The document is the learner's ready, non-archived one (`can_read`), else "Document not found"."""
        view = self._documents.documents_by_id(user_id, [document_id]).get(document_id)
        if view is None or view.state != "ready" or view.archived:
            raise DocumentNotAvailableError("Document not found")

    def start_thread(
        self, user_id: UserId, question: str | None = None, document_id: DocumentId | None = None
    ) -> Thread:
        """A new thread owned by the learner, persisted; its title starts as the first question. Started from a
        document (US-4c), it lists that document as added by the learner; answers still search all documents."""
        self.require_documents(user_id)
        if document_id is not None:
            self.require_readable(user_id, document_id)
        now = self._clock.now()
        thread = Thread.start(ThreadId(str(uuid.uuid4())), user_id, now, title=question)
        self._threads.add(thread)
        if document_id is not None:
            self._threads.add_documents(ThreadId(thread.thread_id), [document_id], now)
        return thread

    def update_thread(
        self, thread_id: ThreadId, user_id: UserId, *, title: str | None = None, search_scope: SearchScope | None = None
    ) -> Thread:
        """The learner renames the conversation (US-13) and/or limits its search to its documents (US-4c). Every
        check runs before anything is saved."""
        thread = self._get(thread_id, user_id)
        new_title = thread.rename(title) if title is not None else None
        if search_scope is not None:
            thread.limit_search(search_scope, len(self._threads.documents_used(thread_id)))
        if new_title is not None:
            self._threads.set_title(thread_id, new_title)
        if search_scope is not None:
            self._threads.set_search_scope(thread_id, search_scope)
        return thread

    def get_thread(self, thread_id: ThreadId, user_id: UserId) -> Thread:
        return self._get(thread_id, user_id)

    def search_documents(self, thread_id: ThreadId, user_id: UserId) -> list[DocumentId] | None:
        """What a new question in the thread searches: None for the whole library, else the listed documents' ids,
        read here and never from the prompt (US-4c). MCP search keeps only those the learner can read."""
        thread = self._get(thread_id, user_id)
        if thread.status is ThreadStatus.ARCHIVED:
            raise ThreadArchivedError("An archived conversation is read-only. Restore it first.")
        if thread.search_scope is SearchScope.LIBRARY:
            return None
        return [row.document_id for row in self._threads.documents_used(thread_id)]

    def record_answer(self, thread_id: ThreadId, user_id: UserId, document_ids: Sequence[DocumentId]) -> None:
        """Add the documents an answer drew on to the thread's documents used (a decline passes none)."""
        self._owned(thread_id, user_id)
        if not document_ids:
            return
        self._threads.add_documents_used(thread_id, list(dict.fromkeys(document_ids)), self._clock.now())

    def keep_deleted_title(self, user_id: UserId, document_id: DocumentId, title: str) -> None:
        """Called by the document delete before it commits, so documents used keep the title (US-10c)."""
        self._threads.keep_deleted_title(user_id, document_id, title)

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
        thread = self._get(thread_id, user_id)
        self._threads.remove_document(thread_id, document_id)
        # A limited thread never has an empty list: the last removal turns the limit off.
        if thread.search_scope is SearchScope.LISTED and not self._threads.documents_used(thread_id):
            self._threads.set_search_scope(thread_id, SearchScope.LIBRARY)

    def _get(self, thread_id: ThreadId, user_id: UserId) -> Thread:
        thread = self._threads.get_owned(thread_id, user_id)
        if thread is None:
            raise ThreadNotFoundError("Conversation not found")
        return thread

    def _owned(self, thread_id: ThreadId, user_id: UserId) -> None:
        self._get(thread_id, user_id)

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
