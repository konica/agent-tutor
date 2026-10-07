"""Threads in Postgres. The table schema lives in migrations 0005 and 0007."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Column, DateTime, Engine, MetaData, Table, Text, Uuid, func, select
from sqlalchemy.dialects.postgresql import ARRAY

from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.tutoring.domain.thread import Thread, ThreadStatus
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository

threads = Table(
    "threads",
    MetaData(),
    Column("thread_id", Uuid(as_uuid=False), primary_key=True),
    Column("user_id", Text),
    Column("subject_ids", ARRAY(Uuid(as_uuid=False))),
    Column("title", Text),
    Column("status", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("last_learner_message_at", DateTime(timezone=True)),
)


def _thread(row: Any) -> Thread:
    return Thread(
        thread_id=ThreadId(str(row.thread_id)),
        user_id=UserId(row.user_id),
        subject_ids=tuple(SubjectId(str(s)) for s in row.subject_ids),
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
                    subject_ids=list(thread.subject_ids),
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

    def bind_subjects(self, thread_id: ThreadId, user_id: UserId, subject_ids: Sequence[SubjectId]) -> bool:
        # One conditional statement, so two concurrent resumes cannot both bind. cardinality(), not array_length():
        # the latter is NULL for an empty array.
        with self._engine.begin() as conn:
            result = conn.execute(
                threads.update()
                .where(
                    threads.c.thread_id == thread_id,
                    threads.c.user_id == user_id,
                    func.cardinality(threads.c.subject_ids) == 0,
                )
                .values(subject_ids=list(subject_ids))
            )
        return result.rowcount == 1
