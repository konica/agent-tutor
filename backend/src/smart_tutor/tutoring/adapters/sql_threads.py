"""Threads in Postgres. The table schemas live in migrations 0005, 0007 and 0009."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, Engine, Identity, MetaData, Table, Text, Uuid, select, update
from sqlalchemy.dialects.postgresql import insert

from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.tutoring.domain.thread import Thread, ThreadStatus
from smart_tutor.tutoring.domain.thread_document import ThreadDocument
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository

threads = Table(
    "threads",
    MetaData(),
    Column("thread_id", Uuid(as_uuid=False), primary_key=True),
    Column("user_id", Text),
    Column("title", Text),
    Column("status", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("last_learner_message_at", DateTime(timezone=True)),
)

thread_documents = Table(
    "thread_documents",
    threads.metadata,
    Column("thread_id", Uuid(as_uuid=False), primary_key=True),
    Column("document_id", Uuid(as_uuid=False), primary_key=True),
    Column("first_used_at", DateTime(timezone=True)),
    Column("deleted_title", Text),
    Column("seq", BigInteger, Identity(always=True)),
)


def _thread(row: Any) -> Thread:
    return Thread(
        thread_id=ThreadId(str(row.thread_id)),
        user_id=UserId(row.user_id),
        created_at=row.created_at,
        status=ThreadStatus(row.status),
        title=row.title,
        last_learner_message_at=row.last_learner_message_at,
    )


class SqlThreadRepository(ThreadRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, thread: Thread) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                threads.insert().values(
                    thread_id=thread.thread_id,
                    user_id=thread.user_id,
                    title=thread.title,
                    status=thread.status.value,
                    created_at=thread.created_at,
                    last_learner_message_at=thread.last_learner_message_at,
                )
            )

    def get_owned(self, thread_id: ThreadId, user_id: UserId) -> Thread | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(threads).where(threads.c.thread_id == thread_id, threads.c.user_id == user_id)
            ).first()
        return _thread(row) if row else None

    def set_title(self, thread_id: ThreadId, title: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(threads.update().where(threads.c.thread_id == thread_id).values(title=title))

    def add_documents_used(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        if not document_ids:
            return
        with self._engine.begin() as conn:
            for document_id in document_ids:
                conn.execute(
                    insert(thread_documents)
                    .values(thread_id=thread_id, document_id=document_id, first_used_at=at)
                    .on_conflict_do_nothing(index_elements=["thread_id", "document_id"])
                )

    def keep_deleted_title(self, user_id: UserId, document_id: DocumentId, title: str) -> None:
        owned = select(threads.c.thread_id).where(threads.c.user_id == user_id)
        with self._engine.begin() as conn:
            conn.execute(
                update(thread_documents)
                .where(thread_documents.c.document_id == document_id, thread_documents.c.thread_id.in_(owned))
                .values(deleted_title=title)
            )

    def documents_used(self, thread_id: ThreadId) -> list[ThreadDocument]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(thread_documents)
                .where(thread_documents.c.thread_id == thread_id)
                .order_by(thread_documents.c.first_used_at, thread_documents.c.seq)
            ).all()
        return [
            ThreadDocument(
                thread_id=ThreadId(str(r.thread_id)),
                document_id=DocumentId(str(r.document_id)),
                first_used_at=r.first_used_at,
                deleted_title=r.deleted_title,
            )
            for r in rows
        ]
