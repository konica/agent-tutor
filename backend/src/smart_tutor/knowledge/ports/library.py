"""Persistence of contents, documents, and uploads, committed together (one unit of work per use case)."""

from abc import ABC, abstractmethod
from collections.abc import Collection
from types import TracebackType
from typing import Self

from smart_tutor.knowledge.domain.chunk import Chunk
from smart_tutor.knowledge.domain.content import Content
from smart_tutor.knowledge.domain.document import NO_FILTER, Document, DocumentFilter
from smart_tutor.knowledge.domain.search import ChunkHit
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.shared.domain.ids import ContentId, DocumentId, SubjectId, UploadId, UserId


class ContentRepository(ABC):
    @abstractmethod
    def insert_or_get(self, content: Content) -> tuple[Content, bool]:
        """Insert unless the owner has this sha256 (unique `(owner_id, sha256)`); return the stored content and
        whether this call created it.

        Concurrent callers with the same owner and hash get one row: the second waits for the first to commit.
        """

    @abstractmethod
    def get(self, content_id: ContentId) -> Content | None: ...

    @abstractmethod
    def get_for_update(self, content_id: ContentId) -> Content | None:
        """The content, locked until the unit of work ends."""

    @abstractmethod
    def save(self, content: Content) -> None:
        """Write back state, failure_reason, attempts, and how it was processed (pages, text_key, chunker, ...)."""

    @abstractmethod
    def remove(self, content_id: ContentId) -> None:
        """Delete the content row; its chunks must be gone first."""


class DocumentRepository(ABC):
    @abstractmethod
    def add(self, document: Document) -> None: ...

    @abstractmethod
    def get_by_upload_for_update(self, upload_id: UploadId) -> Document | None:
        """The document of this upload, locked until the unit of work ends."""

    @abstractmethod
    def save(self, document: Document) -> None:
        """Write back content_id, state, failure_reason, and replace the document's subject rows."""

    @abstractmethod
    def get_by_content(self, content_id: ContentId) -> Document | None:
        """The document linked to this content (one per content: contents are per owner). No access check."""

    @abstractmethod
    def remove(self, document_id: DocumentId) -> None:
        """Delete a document row and its subject rows."""

    @abstractmethod
    def list_processing_for_content_for_update(self, content_id: ContentId) -> list[Document]:
        """Every processing document linked to this content, locked until the unit of work ends."""

    @abstractmethod
    def get(self, document_id: DocumentId) -> Document | None:
        """The document, not locked (no access check: callers apply `can_read`)."""

    @abstractmethod
    def list_failed_for_content_for_update(self, content_id: ContentId) -> list[Document]:
        """Every failed document linked to this content, locked until the unit of work ends."""

    @abstractmethod
    def list_readable_by(self, user_id: UserId, document_filter: DocumentFilter = NO_FILTER) -> list[Document]:
        """`can_read` in storage: the caller's documents matching the filter, newest first.

        Archived ones are included unless the filter says otherwise.

        Each carries its content's title, attempts, authors, and year.
        """

    @abstractmethod
    def list_readable_by_ids(self, user_id: UserId, document_ids: Collection[DocumentId]) -> list[Document]:
        """`can_read` in storage: the caller's documents with these ids, archived included.

        Each carries its content's title, attempts, authors, and year.
        """

    @abstractmethod
    def get_readable_by_sha256(self, user_id: UserId, sha256: str) -> Document | None:
        """`can_read` in storage: the caller's document whose content has this hash, archived or not.

        At most one: contents are per learner.
        """

    @abstractmethod
    def get_readable(self, user_id: UserId, document_id: DocumentId, *, for_update: bool = False) -> Document | None:
        """`can_read` in storage: the caller's document, archived or not, with its content title.

        Locked if `for_update`.
        """

    @abstractmethod
    def subject_ids_readable_by(self, user_id: UserId) -> set[SubjectId]:
        """The distinct subjects of the caller's ready, non-archived documents (PRD §9.4 "Learner's subjects")."""


class UploadRepository(ABC):
    @abstractmethod
    def add(self, upload: Upload) -> None: ...

    @abstractmethod
    def record_outcome(self, upload_id: UploadId, size: int, outcome: UploadOutcome, document_id: DocumentId) -> None:
        """What the worker found, and the document the upload ended in."""

    @abstractmethod
    def get(self, upload_id: UploadId) -> Upload | None: ...


class ChunkRepository(ABC):
    @abstractmethod
    def replace(self, content_id: ContentId, chunks: list[Chunk]) -> None:
        """Make these the content's only chunks (idempotent: processing twice never duplicates)."""

    @abstractmethod
    def remove_for_content(self, content_id: ContentId) -> None:
        """Delete every chunk of the content."""

    @abstractmethod
    def search(
        self, user_id: UserId, embedding: list[float], k: int, document_ids: Collection[DocumentId] | None = None
    ) -> list[ChunkHit]:
        """`can_read` in SQL: chunks of the caller's ready, non-archived documents; with `document_ids`, only those of
        them (ids the caller can't read match nothing)."""


class LibraryUnitOfWork(ABC):
    """`with factory() as tx: …; tx.commit()` — leaving without commit rolls back."""

    contents: ContentRepository
    documents: DocumentRepository
    uploads: UploadRepository
    chunks: ChunkRepository

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def __enter__(self) -> Self: ...

    @abstractmethod
    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None: ...
