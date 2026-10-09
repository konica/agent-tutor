"""DeleteService over the real SqlLibraryUnitOfWork and SqlThreadRepository against the Compose Postgres (`make up`)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.application.delete_service import DeleteService
from smart_tutor.knowledge.domain.content import Content, pages_key
from smart_tutor.shared.domain.ids import ContentId, ThreadId, UserId
from smart_tutor.tutoring.adapters.sql_threads import SqlThreadRepository
from smart_tutor.tutoring.domain.thread import Thread
from tests.fakes.knowledge import FakeObjectStore
from tests.integration.knowledge.test_sql_library import engine, searchable_document, uid

pytestmark = pytest.mark.integration

__all__ = ["engine"]


def count(engine: Engine, sql: str, **params: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql), params).scalar_one())


def test_deleting_a_ready_document_removes_its_rows_and_files_and_keeps_its_title_in_threads(engine: Engine) -> None:
    owner, other = f"ada-{uid()}", f"bob-{uid()}"
    doc = searchable_document(engine, owner, [1, 2])
    with SqlLibraryUnitOfWork(engine) as tx:
        (listed,) = tx.documents.list_readable_by(UserId(owner))
        assert listed.content_id is not None
        content = tx.contents.get(listed.content_id)
        assert content is not None
        # Another learner uploads the very same bytes: a separate content that must survive.
        strangers = Content.first_upload(ContentId(uid()), content.sha256, 10, UserId(other))
        tx.contents.insert_or_get(strangers)
        tx.commit()
    keys = [content.s3_key, pages_key(content.owner_id, content.content_id)]
    objects = FakeObjectStore()
    for key in keys:
        objects.put(key, b"x", "application/pdf")

    threads = SqlThreadRepository(engine)
    thread = Thread.start(ThreadId(str(uuid.uuid4())), UserId(owner), datetime.now(UTC))
    threads.add(thread)
    threads.add_documents_used(thread.thread_id, [doc.document_id], datetime.now(UTC))

    DeleteService(lambda: SqlLibraryUnitOfWork(engine), objects, threads.keep_deleted_title).delete(
        UserId(owner), doc.document_id
    )

    d, c = str(doc.document_id), str(content.content_id)
    assert count(engine, "select count(*) from documents where document_id = :d", d=d) == 0
    assert count(engine, "select count(*) from document_subjects where document_id = :d", d=d) == 0
    assert count(engine, "select count(*) from contents where content_id = :c", c=c) == 0
    assert count(engine, "select count(*) from chunks where content_id = :c", c=c) == 0
    assert objects.versions_deleted == keys
    other_rows = "select count(*) from contents where owner_id = :o and sha256 = :s"
    assert count(engine, other_rows, o=other, s=content.sha256) == 1
    (used,) = threads.documents_used(thread.thread_id)
    assert used.deleted_title == doc.title
