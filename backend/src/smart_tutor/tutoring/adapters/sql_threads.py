"""Threads in Postgres. The table schemas live in migrations 0005, 0007, 0009, 0010 and 0011."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, Engine, Identity, MetaData, Table, Text, Uuid, func, select, update
from sqlalchemy.dialects.postgresql import insert

from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.tutoring.domain.thread import SearchScope, Thread, ThreadStatus
from smart_tutor.tutoring.domain.thread_document import ThreadDocument
from smart_tutor.tutoring.domain.turn import Turn
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository

threads = Table(
    "threads",
    MetaData(),
    Column("thread_id", Uuid(as_uuid=False), primary_key=True),
    Column("user_id", Text),
    Column("title", Text),
    Column("status", Text),
    Column("search_scope", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("last_learner_message_at", DateTime(timezone=True)),
)

thread_documents = Table(
    "thread_documents",
    threads.metadata,
    Column("thread_id", Uuid(as_uuid=False), primary_key=True),
    Column("document_id", Uuid(as_uuid=False), primary_key=True),
    Column("added_by", Text),
    Column("added_at", DateTime(timezone=True)),
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
        search_scope=SearchScope(row.search_scope),
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
                    search_scope=thread.search_scope.value,
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

    def set_search_scope(self, thread_id: ThreadId, scope: SearchScope) -> None:
        with self._engine.begin() as conn:
            conn.execute(threads.update().where(threads.c.thread_id == thread_id).values(search_scope=scope.value))

    def add_documents_used(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        if not document_ids:
            return
        with self._engine.begin() as conn:
            for document_id in document_ids:
                stmt = insert(thread_documents).values(
                    thread_id=thread_id, document_id=document_id, added_by="answer", added_at=at, first_used_at=at
                )
                # A listed document keeps its place; one the learner added is now used.
                conn.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["thread_id", "document_id"],
                        set_={
                            "first_used_at": func.coalesce(
                                thread_documents.c.first_used_at, stmt.excluded.first_used_at
                            )
                        },
                    )
                )

    def add_documents(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        if not document_ids:
            return
        with self._engine.begin() as conn:
            for document_id in document_ids:
                conn.execute(
                    insert(thread_documents)
                    .values(thread_id=thread_id, document_id=document_id, added_by="learner", added_at=at)
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

    def remove_document(self, thread_id: ThreadId, document_id: DocumentId) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                thread_documents.delete().where(
                    thread_documents.c.thread_id == thread_id, thread_documents.c.document_id == document_id
                )
            )

    def documents_used(self, thread_id: ThreadId) -> list[ThreadDocument]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(thread_documents)
                .where(thread_documents.c.thread_id == thread_id)
                .order_by(thread_documents.c.added_at, thread_documents.c.seq)
            ).all()
        return [
            ThreadDocument(
                thread_id=ThreadId(str(r.thread_id)),
                document_id=DocumentId(str(r.document_id)),
                added_by=r.added_by,
                added_at=r.added_at,
                first_used_at=r.first_used_at,
                deleted_title=r.deleted_title,
            )
            for r in rows
        ]

    def add_turn(self, turn: Turn, document_ids: Sequence[DocumentId]) -> None:
        raise NotImplementedError("Task 2")

    def turns(self, thread_id: ThreadId, user_id: UserId) -> list[Turn]:
        raise NotImplementedError("Task 2")
