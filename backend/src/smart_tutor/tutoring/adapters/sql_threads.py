"""Threads in Postgres. The table schemas live in migrations 0005, 0007, 0009, 0010, 0011, 0014 and 0015."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    Connection,
    DateTime,
    Engine,
    Identity,
    MetaData,
    Table,
    Text,
    Uuid,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert

from smart_tutor.shared.domain.ids import DocumentId, RunId, ThreadId, UserId
from smart_tutor.tutoring.domain.thread import SearchScope, Thread, ThreadStatus
from smart_tutor.tutoring.domain.thread_document import ThreadDocument
from smart_tutor.tutoring.domain.turn import Decline, Turn, TurnCitation
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

thread_turns = Table(
    "thread_turns",
    threads.metadata,
    Column("turn_id", BigInteger, Identity(always=True), primary_key=True),
    Column("thread_id", Uuid(as_uuid=False)),
    Column("user_id", Text),
    Column("question", Text),
    Column("answer", Text),
    Column("citations", JSONB),
    Column("decline_code", Text),
    Column("decline_message", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("run_id", Uuid(as_uuid=False)),
)


def _add_documents_used(
    conn: Connection, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime
) -> None:
    for document_id in document_ids:
        stmt = insert(thread_documents).values(
            thread_id=thread_id, document_id=document_id, added_by="answer", added_at=at, first_used_at=at
        )
        # A listed document keeps its place; one the learner added is now used.
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["thread_id", "document_id"],
                set_={"first_used_at": func.coalesce(thread_documents.c.first_used_at, stmt.excluded.first_used_at)},
            )
        )


def _turn(row: Any) -> Turn:
    decline = Decline(row.decline_code, row.decline_message) if row.decline_code is not None else None
    citations = tuple(
        TurnCitation(c["n"], DocumentId(c["document_id"]), c["chunk_id"], c["page"]) for c in row.citations
    )
    return Turn(
        ThreadId(str(row.thread_id)),
        UserId(row.user_id),
        row.question,
        row.answer,
        citations,
        decline,
        row.created_at,
        RunId(str(row.run_id)) if row.run_id else None,
    )


def _thread_document(row: Any) -> ThreadDocument:
    return ThreadDocument(
        thread_id=ThreadId(str(row.thread_id)),
        document_id=DocumentId(str(row.document_id)),
        added_by=row.added_by,
        added_at=row.added_at,
        first_used_at=row.first_used_at,
        deleted_title=row.deleted_title,
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

    def list_owned(self, user_id: UserId, status: ThreadStatus) -> list[Thread]:
        last_activity = func.coalesce(threads.c.last_learner_message_at, threads.c.created_at)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(threads)
                .where(threads.c.user_id == user_id, threads.c.status == status.value)
                .order_by(last_activity.desc(), threads.c.created_at.desc(), threads.c.thread_id)
            ).all()
        return [_thread(r) for r in rows]

    def documents_used_by_thread(self, thread_ids: Sequence[ThreadId]) -> dict[ThreadId, list[ThreadDocument]]:
        if not thread_ids:
            return {}
        # One query for all the threads, so listing N conversations doesn't cost N queries.
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(thread_documents)
                .where(thread_documents.c.thread_id.in_(thread_ids))
                .order_by(thread_documents.c.thread_id, thread_documents.c.added_at, thread_documents.c.seq)
            ).all()
        grouped: dict[ThreadId, list[ThreadDocument]] = {}
        for r in rows:
            grouped.setdefault(ThreadId(str(r.thread_id)), []).append(_thread_document(r))
        return grouped

    def set_last_learner_message_at(self, thread_id: ThreadId, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(threads.update().where(threads.c.thread_id == thread_id).values(last_learner_message_at=at))

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
            _add_documents_used(conn, thread_id, document_ids, at)

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
        return [_thread_document(r) for r in rows]

    def add_turn(self, turn: Turn, document_ids: Sequence[DocumentId]) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                thread_turns.insert().values(
                    thread_id=turn.thread_id,
                    user_id=turn.user_id,
                    question=turn.question,
                    answer=turn.answer,
                    citations=[
                        {"n": c.n, "document_id": c.document_id, "chunk_id": c.chunk_id, "page": c.page}
                        for c in turn.citations
                    ],
                    decline_code=turn.decline.code if turn.decline else None,
                    decline_message=turn.decline.message if turn.decline else None,
                    created_at=turn.created_at,
                    run_id=turn.run_id,
                )
            )
            _add_documents_used(conn, turn.thread_id, document_ids, turn.created_at)

    def turns(self, thread_id: ThreadId, user_id: UserId) -> list[Turn]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(thread_turns)
                .where(thread_turns.c.thread_id == thread_id, thread_turns.c.user_id == user_id)
                .order_by(thread_turns.c.turn_id)
            ).all()
        return [_turn(r) for r in rows]
