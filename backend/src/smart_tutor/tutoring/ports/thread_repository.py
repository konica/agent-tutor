"""Persistence of threads. Reads are always scoped to the owner."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.domain.thread_document import ThreadDocument


class ThreadRepository(ABC):
    @abstractmethod
    def add(self, thread: Thread) -> None:
        """Store a new thread (committed when this returns)."""

    @abstractmethod
    def get_owned(self, thread_id: ThreadId, user_id: UserId) -> Thread | None:
        """The thread if it exists and belongs to this learner; None otherwise."""

    @abstractmethod
    def set_title(self, thread_id: ThreadId, title: str) -> None:
        """Store the thread's title (committed when this returns). (Callers check ownership first with `get_owned`.)"""

    @abstractmethod
    def add_documents_used(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        """Append the documents not listed yet, in this order, first used `at`.

        Already listed ones keep their place (committed when this returns).
        """

    @abstractmethod
    def keep_deleted_title(self, user_id: UserId, document_id: DocumentId, title: str) -> None:
        """Copy a document's display title onto its rows in the user's threads, before the document is deleted."""

    @abstractmethod
    def documents_used(self, thread_id: ThreadId) -> list[ThreadDocument]:
        """In order of first use. (Callers check ownership first with `get_owned`.)"""
