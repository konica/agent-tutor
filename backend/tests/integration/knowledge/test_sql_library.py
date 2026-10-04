"""SqlLibraryUnitOfWork against the Compose Postgres (`make up`)."""

import hashlib
import threading
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.domain.content import Content
from smart_tutor.knowledge.domain.document import DUPLICATE_UPLOAD, Document
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UploadId, UserId

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = Settings().database_url
    upgrade_to_head(url)
    return create_db_engine(url)


def uid() -> str:
    return str(uuid.uuid4())


def start(engine: Engine, owner: str, name: str = "paper.pdf") -> Document:
    upload = Upload(UploadId(uid()), UserId(owner), datetime.now(UTC))
    doc = Document.start_upload(DocumentId(uid()), UserId(owner), upload.upload_id, name, upload.created_at)
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.uploads.add(upload)
        tx.documents.add(doc)
        tx.commit()
    return doc


def test_documents_list_only_for_their_owner(engine: Engine) -> None:
    ada, bob = f"ada-{uid()}", f"bob-{uid()}"
    first, second = start(engine, ada, "first.pdf"), start(engine, ada, "second.pdf")
    start(engine, bob)
    with SqlLibraryUnitOfWork(engine) as tx:
        mine = tx.documents.list_readable_by(UserId(ada))
    assert [d.document_id for d in mine] == [second.document_id, first.document_id]
    assert all(d.owner_id == ada for d in mine)


def test_uncommitted_work_rolls_back(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.uploads.add(Upload(UploadId(uid()), UserId(owner), datetime.now(UTC)))
    with engine.connect() as conn:
        count = conn.execute(text("select count(*) from uploads where user_id = :u"), {"u": owner}).scalar_one()
    assert count == 0


def test_concurrent_insert_or_get_makes_one_content_row(engine: Engine) -> None:
    sha = hashlib.sha256(uid().encode()).hexdigest()
    barrier = threading.Barrier(2, timeout=10)
    results: list[bool] = []

    def worker(user: str) -> None:
        with SqlLibraryUnitOfWork(engine) as tx:
            barrier.wait()
            _, created = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(user)))
            results.append(created)
            tx.commit()

    threads = [threading.Thread(target=worker, args=(u,), daemon=True) for u in ("ada", "bob")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    assert sorted(results) == [False, True]
    with engine.connect() as conn:
        rows = conn.execute(text("select count(*) from contents where sha256 = :s"), {"s": sha}).scalar_one()
    assert rows == 1


def test_duplicate_document_keeps_content_id_null(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    sha = hashlib.sha256(uid().encode()).hexdigest()
    first, second = start(engine, owner), start(engine, owner)
    with SqlLibraryUnitOfWork(engine) as tx:
        content, _ = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(owner)))
        doc = tx.documents.get_by_upload_for_update(first.upload_id)
        assert doc is not None
        doc.link_content(content.content_id)
        tx.documents.save(doc)
        tx.uploads.record_outcome(first.upload_id, 10, UploadOutcome.STORED)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        _, created = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(owner)))
        assert not created
        dup = tx.documents.get_by_upload_for_update(second.upload_id)
        assert dup is not None
        dup.fail(DUPLICATE_UPLOAD)
        tx.documents.save(dup)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        by_id = {d.document_id: d for d in tx.documents.list_readable_by(UserId(owner))}
    assert by_id[first.document_id].content_id == content.content_id
    assert (by_id[second.document_id].state, by_id[second.document_id].content_id) == ("failed", None)
