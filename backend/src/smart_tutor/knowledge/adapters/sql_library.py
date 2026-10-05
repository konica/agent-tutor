"""PostgreSQL library: one connection and transaction per unit of work."""

from types import TracebackType
from typing import Any, Self

from sqlalchemy import ColumnElement, Connection, Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert

from smart_tutor.knowledge.adapters.sql_tables import contents, documents, uploads
from smart_tutor.knowledge.domain.chunk import Chunk
from smart_tutor.knowledge.domain.content import Content, ContentState
from smart_tutor.knowledge.domain.document import Document, DocumentState
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.knowledge.ports.library import (
    ChunkRepository,
    ContentRepository,
    DocumentRepository,
    LibraryUnitOfWork,
    UploadRepository,
)
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UploadId, UserId


def readable_by(user_id: UserId) -> ColumnElement[bool]:
    """`can_read` in SQL (Release 1: owner only; PRD §9.3). The domain twin is Document.can_be_read_by."""
    return documents.c.owner_id == user_id


def _content(row: Any) -> Content:
    return Content(
        ContentId(row.content_id),
        row.sha256,
        row.s3_key,
        row.bytes,
        ContentState(row.state),
        row.attempts,
        UserId(row.processed_by_user_id) if row.processed_by_user_id else None,
    )


def _document(row: Any) -> Document:
    return Document(
        document_id=DocumentId(row.document_id),
        owner_id=UserId(row.owner_id),
        upload_id=UploadId(row.upload_id),
        file_name=row.file_name,
        state=DocumentState(row.state),
        created_at=row.created_at,
        content_id=ContentId(row.content_id) if row.content_id else None,
        failure_reason=row.failure_reason,
        title_override=row.title_override,
    )


class _Contents(ContentRepository):
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert_or_get(self, content: Content) -> tuple[Content, bool]:
        inserted = self._conn.execute(
            insert(contents)
            .values(
                content_id=content.content_id,
                sha256=content.sha256,
                s3_key=content.s3_key,
                bytes=content.size,
                state=content.state.value,
                attempts=content.attempts,
                processed_by_user_id=content.processed_by_user_id,
                processed_at=func.now(),
            )
            .on_conflict_do_nothing(index_elements=["sha256"])
            .returning(contents.c.content_id)
        ).first()
        if inserted is not None:
            return content, True
        # READ COMMITTED: this statement sees the row the concurrent winner just committed.
        row = self._conn.execute(select(contents).where(contents.c.sha256 == content.sha256)).one()
        return _content(row), False

    # The three methods below are implemented in the next commit (SQL/S3 adapters for processing).
    def get(self, content_id: ContentId) -> Content | None:
        raise NotImplementedError

    def get_for_update(self, content_id: ContentId) -> Content | None:
        raise NotImplementedError

    def save(self, content: Content) -> None:
        raise NotImplementedError


class _Documents(DocumentRepository):
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add(self, document: Document) -> None:
        self._conn.execute(
            documents.insert().values(
                document_id=document.document_id,
                owner_id=document.owner_id,
                upload_id=document.upload_id,
                file_name=document.file_name,
                state=document.state.value,
                created_at=document.created_at,
            )
        )

    def get_by_upload_for_update(self, upload_id: UploadId) -> Document | None:
        row = self._conn.execute(select(documents).where(documents.c.upload_id == upload_id).with_for_update()).first()
        return _document(row) if row else None

    def save(self, document: Document) -> None:
        self._conn.execute(
            update(documents)
            .where(documents.c.document_id == document.document_id)
            .values(content_id=document.content_id, state=document.state.value, failure_reason=document.failure_reason)
        )

    def list_processing_for_content_for_update(self, content_id: ContentId) -> list[Document]:
        raise NotImplementedError  # implemented in the next commit (SQL/S3 adapters for processing)

    def list_readable_by(self, user_id: UserId) -> list[Document]:
        rows = self._conn.execute(
            select(documents)
            .where(readable_by(user_id), documents.c.archived.is_(False))
            .order_by(documents.c.created_at.desc(), documents.c.document_id)
        )
        return [_document(r) for r in rows]


class _Uploads(UploadRepository):
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add(self, upload: Upload) -> None:
        self._conn.execute(
            uploads.insert().values(upload_id=upload.upload_id, user_id=upload.user_id, created_at=upload.created_at)
        )

    def record_outcome(self, upload_id: UploadId, size: int, outcome: UploadOutcome) -> None:
        self._conn.execute(
            update(uploads).where(uploads.c.upload_id == upload_id).values(bytes=size, outcome=outcome.value)
        )


class _Chunks(ChunkRepository):
    def replace(self, content_id: ContentId, chunks: list[Chunk]) -> None:
        raise NotImplementedError  # implemented in the next commit (SQL/S3 adapters for processing)


class SqlLibraryUnitOfWork(LibraryUnitOfWork):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __enter__(self) -> Self:
        self._conn = self._engine.connect()
        self._tx = self._conn.begin()
        self.contents = _Contents(self._conn)
        self.documents = _Documents(self._conn)
        self.uploads = _Uploads(self._conn)
        self.chunks = _Chunks()
        return self

    def commit(self) -> None:
        self._tx.commit()

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._tx.is_active:
            self._tx.rollback()
        self._conn.close()
