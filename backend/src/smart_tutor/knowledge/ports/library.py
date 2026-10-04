"""Persistence of contents, documents, and uploads, committed together (one unit of work per use case)."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from smart_tutor.knowledge.domain.content import Content
from smart_tutor.knowledge.domain.document import Document
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.shared.domain.ids import UploadId, UserId


class ContentRepository(ABC):
    @abstractmethod
    def insert_or_get(self, content: Content) -> tuple[Content, bool]:
        """Insert unless the sha256 exists; return the stored content and whether this call created it.

        Concurrent callers with the same sha256 get one row: the second waits for the first to commit.
        """


class DocumentRepository(ABC):
    @abstractmethod
    def add(self, document: Document) -> None: ...

    @abstractmethod
    def get_by_upload_for_update(self, upload_id: UploadId) -> Document | None:
        """The document of this upload, locked until the unit of work ends."""

    @abstractmethod
    def save(self, document: Document) -> None:
        """Write back content_id, state, and failure_reason."""

    @abstractmethod
    def list_readable_by(self, user_id: UserId) -> list[Document]:
        """`can_read` in storage: the caller's non-archived documents, newest first."""


class UploadRepository(ABC):
    @abstractmethod
    def add(self, upload: Upload) -> None: ...

    @abstractmethod
    def record_outcome(self, upload_id: UploadId, size: int, outcome: UploadOutcome) -> None: ...


class LibraryUnitOfWork(ABC):
    """`with factory() as tx: …; tx.commit()` — leaving without commit rolls back."""

    contents: ContentRepository
    documents: DocumentRepository
    uploads: UploadRepository

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def __enter__(self) -> Self: ...

    @abstractmethod
    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None: ...
