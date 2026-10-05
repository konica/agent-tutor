"""PostgreSQL library: one connection and transaction per unit of work."""

import uuid
from types import TracebackType
from typing import Any, Self

from sqlalchemy import ColumnElement, Connection, Engine, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from smart_tutor.knowledge.adapters.sql_tables import chunks, contents, document_subjects, documents, uploads
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
from smart_tutor.shared.domain.ids import ContentId, DocumentId, SubjectId, UploadId, UserId


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
        failure_reason=row.failure_reason,
        pages=row.pages,
        text_key=row.text_key,
        chunker=row.chunker,
        embedding_model=row.embedding_model,
        embedding_dim=row.embedding_dim,
        title=row.title,
        authors=list(row.authors),
        year=row.year,
        doi=row.doi,
        summary=row.summary,
        summary_embedding=None if row.summary_embedding is None else [float(x) for x in row.summary_embedding],
        proposed_subject_names=list(row.proposed_subject_names),
        work_key=row.work_key,
    )


def _document(row: Any, subject_ids: list[SubjectId]) -> Document:
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
        content_title=getattr(row, "content_title", None),  # only listings join contents (FOR UPDATE can't)
        subject_ids=subject_ids,
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

    def get(self, content_id: ContentId) -> Content | None:
        row = self._conn.execute(select(contents).where(contents.c.content_id == content_id)).first()
        return _content(row) if row else None

    def get_for_update(self, content_id: ContentId) -> Content | None:
        row = self._conn.execute(select(contents).where(contents.c.content_id == content_id).with_for_update()).first()
        return _content(row) if row else None

    def save(self, content: Content) -> None:
        self._conn.execute(
            update(contents)
            .where(contents.c.content_id == content.content_id)
            .values(
                state=content.state.value,
                failure_reason=content.failure_reason,
                pages=content.pages,
                text_key=content.text_key,
                chunker=content.chunker,
                embedding_model=content.embedding_model,
                embedding_dim=content.embedding_dim,
                title=content.title,
                authors=content.authors,
                year=content.year,
                doi=content.doi,
                summary=content.summary,
                summary_embedding=content.summary_embedding,
                proposed_subject_names=content.proposed_subject_names,
                work_key=content.work_key,
            )
        )


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
        return self._load([row])[0] if row else None

    def save(self, document: Document) -> None:
        self._conn.execute(
            update(documents)
            .where(documents.c.document_id == document.document_id)
            .values(content_id=document.content_id, state=document.state.value, failure_reason=document.failure_reason)
        )
        self._conn.execute(delete(document_subjects).where(document_subjects.c.document_id == document.document_id))
        if document.subject_ids:
            self._conn.execute(
                document_subjects.insert(),
                [{"document_id": document.document_id, "subject_id": sid} for sid in document.subject_ids],
            )

    def list_processing_for_content_for_update(self, content_id: ContentId) -> list[Document]:
        rows = self._conn.execute(
            select(documents)
            .where(documents.c.content_id == content_id, documents.c.state == DocumentState.PROCESSING.value)
            .order_by(documents.c.document_id)  # a stable lock order for concurrent workers
            .with_for_update()
        ).all()
        return self._load(list(rows))

    def list_readable_by(self, user_id: UserId) -> list[Document]:
        rows = self._conn.execute(
            select(documents, contents.c.title.label("content_title"))
            .select_from(documents.outerjoin(contents, documents.c.content_id == contents.c.content_id))
            .where(readable_by(user_id), documents.c.archived.is_(False))
            .order_by(documents.c.created_at.desc(), documents.c.document_id)
        )
        return self._load(list(rows))

    def _load(self, rows: list[Any]) -> list[Document]:
        """Documents with their subject ids in one extra query. Postgres keeps no insertion order, so by id."""
        by_document: dict[str, list[SubjectId]] = {}
        if rows:
            subject_rows = self._conn.execute(
                select(document_subjects.c.document_id, document_subjects.c.subject_id)
                .where(document_subjects.c.document_id.in_([r.document_id for r in rows]))
                .order_by(document_subjects.c.subject_id)
            )
            for r in subject_rows:
                by_document.setdefault(str(r.document_id), []).append(SubjectId(str(r.subject_id)))
        return [_document(r, by_document.get(str(r.document_id), [])) for r in rows]


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
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def replace(self, content_id: ContentId, new_chunks: list[Chunk]) -> None:
        self._conn.execute(delete(chunks).where(chunks.c.content_id == content_id))
        if new_chunks:
            self._conn.execute(
                chunks.insert(),
                [
                    {
                        "chunk_id": str(uuid.uuid4()),
                        "content_id": c.content_id,
                        "seq": c.seq,
                        "page": c.page,
                        "text": c.text,
                        "embedding": c.embedding,
                    }
                    for c in new_chunks
                ],
            )


class SqlLibraryUnitOfWork(LibraryUnitOfWork):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __enter__(self) -> Self:
        self._conn = self._engine.connect()
        self._tx = self._conn.begin()
        self.contents = _Contents(self._conn)
        self.documents = _Documents(self._conn)
        self.uploads = _Uploads(self._conn)
        self.chunks = _Chunks(self._conn)
        return self

    def commit(self) -> None:
        self._tx.commit()

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._tx.is_active:
            self._tx.rollback()
        self._conn.close()
