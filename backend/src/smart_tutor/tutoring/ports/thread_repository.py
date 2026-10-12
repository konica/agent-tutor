"""Persistence of threads. Reads are always scoped to the owner."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from smart_tutor.shared.domain.ids import DocumentId, RunId, ThreadId, UserId
from smart_tutor.tutoring.domain.thread import NO_THREAD_FILTER, SearchScope, Thread, ThreadFilter, ThreadStatus
from smart_tutor.tutoring.domain.thread_document import ThreadDocument
from smart_tutor.tutoring.domain.turn import Rating, Turn


class ThreadRepository(ABC):
    @abstractmethod
    def add(self, thread: Thread) -> None:
        """Store a new thread (committed when this returns)."""

    @abstractmethod
    def get_owned(self, thread_id: ThreadId, user_id: UserId) -> Thread | None:
        """The thread if it exists and belongs to this learner; None otherwise."""

    @abstractmethod
    def list_owned(
        self, user_id: UserId, status: ThreadStatus, thread_filter: ThreadFilter = NO_THREAD_FILTER
    ) -> list[Thread]:
        """The learner's threads in this status that match the filter, newest last activity first (then newest
        started; scoped by owner)."""

    @abstractmethod
    def documents_used_by_thread(self, thread_ids: Sequence[ThreadId]) -> dict[ThreadId, list[ThreadDocument]]:
        """Each thread's document list as `documents_used` orders it; a thread with none may be absent.
        (Callers pass ids of the learner's own threads.)"""

    @abstractmethod
    def set_last_learner_message_at(self, thread_id: ThreadId, at: datetime) -> None:
        """Store when the learner last asked in the thread (committed). (Callers check ownership first.)"""

    @abstractmethod
    def set_title(self, thread_id: ThreadId, title: str) -> None:
        """Store the thread's title (committed when this returns). (Callers check ownership first with `get_owned`.)"""

    @abstractmethod
    def set_search_scope(self, thread_id: ThreadId, scope: SearchScope) -> None:
        """Store the thread's search scope (committed when this returns). (Callers check ownership first.)"""

    @abstractmethod
    def add_documents_used(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        """Append the documents not listed yet, in this order, added and first used `at`.

        A listed one keeps its place and is marked first used `at` if it wasn't used yet
        (committed when this returns).
        """

    @abstractmethod
    def keep_deleted_title(self, user_id: UserId, document_id: DocumentId, title: str) -> None:
        """Copy a document's display title onto its rows in the user's threads, before the document is deleted."""

    @abstractmethod
    def add_documents(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        """The learner adds these documents, in this order, not used yet; listed ones are unchanged (committed)."""

    @abstractmethod
    def remove_document(self, thread_id: ThreadId, document_id: DocumentId) -> None:
        """Take the document off the list, if listed (committed). The document itself is untouched."""

    @abstractmethod
    def documents_used(self, thread_id: ThreadId) -> list[ThreadDocument]:
        """The thread's document list in the order documents joined it.

        (Callers check ownership first with `get_owned`.)
        """

    @abstractmethod
    def add_turn(self, turn: Turn, document_ids: Sequence[DocumentId]) -> None:
        """Keep the turn and add `document_ids` to the thread's documents used at `turn.created_at`, as
        `add_documents_used` does, in one transaction (committed when this returns). (Callers check ownership first.)"""

    @abstractmethod
    def last_turns(self, thread_id: ThreadId, user_id: UserId, limit: int) -> list[Turn]:
        """The thread's newest `limit` kept turns, oldest first; empty unless the thread is this learner's (scoped by
        owner)."""

    @abstractmethod
    def turns(self, thread_id: ThreadId, user_id: UserId) -> list[Turn]:
        """The thread's kept turns, oldest first; empty unless the thread is this learner's (scoped by owner)."""

    @abstractmethod
    def set_rating(self, thread_id: ThreadId, user_id: UserId, run_id: RunId, rating: Rating) -> bool:
        """Store the rating on that turn of the learner's thread (committed). False when the learner's thread has no
        turn with this run id."""
