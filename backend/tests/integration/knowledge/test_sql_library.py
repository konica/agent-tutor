"""SqlLibraryUnitOfWork against the Compose Postgres (`make up`)."""

import hashlib
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.application import ArchiveService, DocumentService
from smart_tutor.knowledge.domain.chunk import Chunk
from smart_tutor.knowledge.domain.content import UNREADABLE_PDF, Content
from smart_tutor.knowledge.domain.description import DocumentDescription, parse_description
from smart_tutor.knowledge.domain.document import Document, DocumentFilter, DocumentState
from smart_tutor.knowledge.domain.search import ChunkHit
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.shared.adapters.clock import SystemClock
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import ContentId, DocumentId, SubjectId, UploadId, UserId

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


def test_concurrent_insert_or_get_by_one_owner_makes_one_content_row(engine: Engine) -> None:
    owner = UserId(f"ada-{uid()}")
    sha = hashlib.sha256(uid().encode()).hexdigest()
    barrier = threading.Barrier(2, timeout=10)
    results: list[bool] = []

    def worker() -> None:
        with SqlLibraryUnitOfWork(engine) as tx:
            barrier.wait()
            _, created = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, owner))
            results.append(created)
            tx.commit()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    assert sorted(results) == [False, True]
    with engine.connect() as conn:
        rows = conn.execute(text("select count(*) from contents where sha256 = :s"), {"s": sha}).scalar_one()
    assert rows == 1


def test_two_owners_with_the_same_hash_get_two_contents(engine: Engine) -> None:
    sha = hashlib.sha256(uid().encode()).hexdigest()
    made = []
    for owner in (f"ada-{uid()}", f"bob-{uid()}"):
        with SqlLibraryUnitOfWork(engine) as tx:
            content, created = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(owner)))
            tx.commit()
        assert created is True
        assert content.owner_id == owner
        made.append(content.content_id)
    with engine.connect() as conn:
        rows = conn.execute(text("select content_id, owner_id from contents where sha256 = :s"), {"s": sha}).all()
    assert sorted(str(r.content_id) for r in rows) == sorted(made)
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.contents.get(made[1])
    assert loaded is not None and loaded.owner_id.startswith("bob-")


def test_a_duplicate_upload_removes_its_document_and_points_to_the_existing_one(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    sha = hashlib.sha256(uid().encode()).hexdigest()
    first, second = start(engine, owner), start(engine, owner)
    with SqlLibraryUnitOfWork(engine) as tx:
        content, _ = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(owner)))
        doc = tx.documents.get_by_upload_for_update(first.upload_id)
        assert doc is not None
        doc.link_content(content.content_id)
        tx.documents.save(doc)
        tx.uploads.record_outcome(first.upload_id, 10, UploadOutcome.STORED, first.document_id)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        again, created = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(owner)))
        assert not created and again.content_id == content.content_id
        existing = tx.documents.get_by_content(again.content_id)
        assert existing is not None and existing.document_id == first.document_id
        tx.documents.remove(second.document_id)
        tx.uploads.record_outcome(second.upload_id, 10, UploadOutcome.DUPLICATE, existing.document_id)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        assert tx.documents.get(second.document_id) is None
        assert [d.document_id for d in tx.documents.list_readable_by(UserId(owner))] == [first.document_id]
        stored, duplicate = tx.uploads.get(first.upload_id), tx.uploads.get(second.upload_id)
        assert tx.uploads.get(UploadId(uid())) is None
        assert tx.documents.get_by_content(ContentId(uid())) is None
    assert stored is not None and (stored.outcome, stored.document_id, stored.size) == (
        UploadOutcome.STORED,
        first.document_id,
        10,
    )
    assert duplicate is not None and (duplicate.outcome, duplicate.document_id) == (
        UploadOutcome.DUPLICATE,
        first.document_id,
    )
    assert duplicate.user_id == owner


def test_removing_a_document_drops_its_subjects(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    doc = start(engine, owner)
    link(engine, doc, stored_content(engine, owner))
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.documents.get_by_upload_for_update(doc.upload_id)
        assert loaded is not None
        loaded.await_subjects()
        loaded.choose_subjects([GENERAL])
        tx.documents.save(loaded)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.documents.remove(doc.document_id)
        tx.commit()
    with engine.connect() as conn:
        count = conn.execute(
            text("select count(*) from document_subjects where document_id = :d"), {"d": doc.document_id}
        )
        assert count.scalar_one() == 0


GENERAL = SubjectId("00000000-0000-4000-8000-000000000001")


def stored_content(engine: Engine, owner: str) -> Content:
    sha = hashlib.sha256(uid().encode()).hexdigest()
    with SqlLibraryUnitOfWork(engine) as tx:
        content, _ = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(owner)))
        tx.commit()
    return content


def link(engine: Engine, doc: Document, content: Content) -> None:
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.documents.get_by_upload_for_update(doc.upload_id)
        assert loaded is not None
        loaded.link_content(content.content_id)
        tx.documents.save(loaded)
        tx.commit()


def chunk(content: Content, seq: int, page: int | None, value: float) -> Chunk:
    return Chunk(content.content_id, seq, page, f"text {seq}", [value] * 1024)


def test_replace_chunks_is_idempotent(engine: Engine) -> None:
    content = stored_content(engine, f"ada-{uid()}")
    first = [chunk(content, 0, 1, 0.1), chunk(content, 1, 2, 0.2), chunk(content, 2, None, 0.3)]
    second = [chunk(content, 0, 1, 0.5), chunk(content, 1, 3, 0.25)]
    for batch in (first, second, second):
        with SqlLibraryUnitOfWork(engine) as tx:
            tx.chunks.replace(content.content_id, batch)
            tx.commit()
    with engine.connect() as conn:
        rows = conn.execute(
            text("select seq, page, text, embedding::text as emb from chunks where content_id = :c order by seq"),
            {"c": content.content_id},
        ).all()
    assert [(r.seq, r.page, r.text) for r in rows] == [(0, 1, "text 0"), (1, 3, "text 1")]
    vectors = [[float(v) for v in r.emb.strip("[]").split(",")] for r in rows]
    assert [len(v) for v in vectors] == [1024, 1024]
    assert vectors[0][0] == pytest.approx(0.5)
    assert vectors[1][-1] == pytest.approx(0.25)


def test_chunks_without_a_start_index_are_listed_and_filled(engine: Engine) -> None:
    content = stored_content(engine, f"ada-{uid()}")
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.chunks.replace(
            content.content_id,
            [chunk(content, 0, 1, 0.1), replace(chunk(content, 1, 1, 0.2), start_index=5)],
        )
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        assert tx.chunks.contents_missing_start_index().count(content.content_id) == 1
        stored = tx.chunks.list_for_content(content.content_id)
    assert [(c.seq, c.page, c.text, c.start_index) for c in stored] == [(0, 1, "text 0", None), (1, 1, "text 1", 5)]
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.chunks.set_start_indexes({stored[0].chunk_id: 3, uid(): 9})  # an unknown id updates nothing
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        assert content.content_id not in tx.chunks.contents_missing_start_index()
        assert [c.start_index for c in tx.chunks.list_for_content(content.content_id)] == [3, 5]


def test_a_chunk_is_readable_only_through_its_owners_document_archived_included(engine: Engine) -> None:
    owner, other = f"ada-{uid()}", f"bob-{uid()}"
    doc = searchable_document(engine, owner, [3])
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.documents.get(doc.document_id)
        assert loaded is not None and loaded.content_id is not None
        [stored] = tx.chunks.list_for_content(loaded.content_id)
    with SqlLibraryUnitOfWork(engine) as tx:
        mine = tx.chunks.get_readable(UserId(owner), stored.chunk_id)
        assert tx.chunks.get_readable(UserId(other), stored.chunk_id) is None
        assert tx.chunks.get_readable(UserId(owner), "not-a-uuid") is None
        assert tx.chunks.get_readable(UserId(owner), str(uuid.uuid4())) is None
    assert mine is not None
    assert (mine.document_id, mine.page, mine.start_index, mine.text) == (doc.document_id, 1, None, "chunk 3")
    with engine.begin() as conn:
        conn.execute(text("UPDATE documents SET archived = true WHERE document_id = :d"), {"d": doc.document_id})
    with SqlLibraryUnitOfWork(engine) as tx:
        assert tx.chunks.get_readable(UserId(owner), stored.chunk_id) is not None


def test_replace_with_no_chunks_only_deletes(engine: Engine) -> None:
    content = stored_content(engine, f"ada-{uid()}")
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.chunks.replace(content.content_id, [chunk(content, 0, 1, 0.1)])
        tx.chunks.replace(content.content_id, [])
        tx.commit()
    with engine.connect() as conn:
        count = conn.execute(text("select count(*) from chunks where content_id = :c"), {"c": content.content_id})
        assert count.scalar_one() == 0


def test_removing_a_content_and_its_chunks_leaves_other_contents(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    gone_doc, kept_doc = start(engine, owner), start(engine, owner)
    gone, kept = stored_content(engine, owner), stored_content(engine, owner)
    link(engine, gone_doc, gone)
    link(engine, kept_doc, kept)
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.chunks.replace(gone.content_id, [chunk(gone, 0, 1, 0.1), chunk(gone, 1, 2, 0.2)])
        tx.chunks.replace(kept.content_id, [chunk(kept, 0, 1, 0.3)])
        tx.commit()

    with SqlLibraryUnitOfWork(engine) as tx:
        tx.chunks.remove_for_content(gone.content_id)
        tx.documents.remove(gone_doc.document_id)
        tx.contents.remove(gone.content_id)
        tx.commit()

    def count(table: str, content: Content) -> int:
        with engine.connect() as conn:
            query = text(f"select count(*) from {table} where content_id = :c")
            return conn.execute(query, {"c": content.content_id}).scalar_one()

    assert count("chunks", gone) == 0
    assert count("contents", gone) == 0
    assert count("chunks", kept) > 0
    assert count("contents", kept) == 1


def test_ready_content_fields_round_trip(engine: Engine) -> None:
    content = stored_content(engine, f"ada-{uid()}")
    with SqlLibraryUnitOfWork(engine) as tx:
        locked = tx.contents.get_for_update(content.content_id)
        assert locked is not None
        locked.ready(pages=3, text_key="contents/x.pages.json", chunker="c:v1", embedding_model="m", embedding_dim=1024)
        tx.contents.save(locked)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.contents.get(content.content_id)
    assert loaded is not None
    assert (loaded.state, loaded.pages, loaded.text_key, loaded.chunker) == (
        "ready",
        3,
        "contents/x.pages.json",
        "c:v1",
    )
    assert (loaded.embedding_model, loaded.embedding_dim, loaded.failure_reason) == ("m", 1024, None)


def test_failed_content_round_trips_its_reason(engine: Engine) -> None:
    content = stored_content(engine, f"ada-{uid()}")
    with SqlLibraryUnitOfWork(engine) as tx:
        locked = tx.contents.get_for_update(content.content_id)
        assert locked is not None
        locked.fail(UNREADABLE_PDF)
        tx.contents.save(locked)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.contents.get(content.content_id)
    assert loaded is not None
    assert (loaded.state, loaded.failure_reason) == ("failed", UNREADABLE_PDF)


def test_missing_content_is_none(engine: Engine) -> None:
    with SqlLibraryUnitOfWork(engine) as tx:
        assert tx.contents.get(ContentId(uid())) is None
        assert tx.contents.get_for_update(ContentId(uid())) is None


def test_ready_document_round_trips_its_subjects(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    doc = start(engine, owner)
    link(engine, doc, stored_content(engine, owner))
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.documents.get_by_upload_for_update(doc.upload_id)
        assert loaded is not None
        assert loaded.subject_ids == []
        loaded.await_subjects()
        loaded.choose_subjects([GENERAL])
        tx.documents.save(loaded)
        tx.documents.save(loaded)  # saving twice replaces the rows
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        (listed,) = tx.documents.list_readable_by(UserId(owner))
        locked = tx.documents.get_by_upload_for_update(doc.upload_id)
    assert (listed.state, listed.subject_ids) == ("ready", [GENERAL])
    assert locked is not None and locked.subject_ids == [GENERAL]


def test_get_readable_is_owner_only_and_includes_archived(engine: Engine) -> None:
    owner, other = f"ada-{uid()}", f"bob-{uid()}"
    doc = start(engine, owner)
    with SqlLibraryUnitOfWork(engine) as tx:
        found = tx.documents.get_readable(UserId(owner), doc.document_id)
        locked = tx.documents.get_readable(UserId(owner), doc.document_id, for_update=True)
        assert tx.documents.get_readable(UserId(other), doc.document_id) is None
    assert found is not None and found.document_id == doc.document_id
    assert locked is not None and locked.document_id == doc.document_id
    with engine.begin() as conn:
        conn.execute(text("UPDATE documents SET archived = true WHERE document_id = :d"), {"d": doc.document_id})
    with SqlLibraryUnitOfWork(engine) as tx:
        found_archived = tx.documents.get_readable(UserId(owner), doc.document_id)
    assert found_archived is not None and found_archived.archived


def test_archive_and_restore_round_trip(engine: Engine) -> None:
    owner = UserId(f"ada-{uid()}")
    doc = start(engine, owner)
    at = datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
    doc.archive(at)
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.documents.save(doc)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        archived = tx.documents.get_readable(owner, doc.document_id)
    assert archived is not None and archived.archived is True and archived.archived_at == at
    archived.restore()
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.documents.save(archived)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        restored = tx.documents.get_readable(owner, doc.document_id)
    assert restored is not None and (restored.archived, restored.archived_at) == (False, None)


def test_a_renamed_document_keeps_its_title_through_archive_and_resets(engine: Engine) -> None:
    owner = UserId(f"ada-{uid()}")
    doc = start(engine, owner)
    docs = DocumentService(lambda: SqlLibraryUnitOfWork(engine), max_attempts=3)
    docs.set_title(owner, doc.document_id, "  Mine ")
    ArchiveService(lambda: SqlLibraryUnitOfWork(engine), SystemClock(), max_attempts=3).archive(owner, doc.document_id)
    with SqlLibraryUnitOfWork(engine) as tx:
        kept = tx.documents.get_readable(owner, doc.document_id)
        [listed] = tx.documents.list_readable_by(owner, DocumentFilter(archived=True))
    assert kept is not None and kept.title_override == "Mine" and kept.archived is True
    assert listed.title == "Mine"
    docs.set_title(owner, doc.document_id, None)
    with SqlLibraryUnitOfWork(engine) as tx:
        reset = tx.documents.get_readable(owner, doc.document_id)
    assert reset is not None and reset.title_override is None


def test_a_processing_document_stays_archived_when_the_worker_saves_it(engine: Engine) -> None:
    owner = UserId(f"ada-{uid()}")
    doc = start(engine, owner)
    content = Content.first_upload(ContentId(uid()), hashlib.sha256(uid().encode()).hexdigest(), 10, owner)
    at = datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
    doc.link_content(content.content_id)
    doc.archive(at)
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.contents.insert_or_get(content)
        tx.documents.save(doc)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:  # the worker's path
        [loaded] = tx.documents.list_processing_for_content_for_update(content.content_id)
        loaded.await_subjects()
        tx.documents.save(loaded)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        after = tx.documents.get_readable(owner, doc.document_id)
    assert after is not None
    assert (after.state, after.archived, after.archived_at) == (DocumentState.AWAITING_SUBJECTS, True, at)


def test_list_readable_by_ids_includes_archived_and_is_owner_only(engine: Engine) -> None:
    owner, other = f"ada-{uid()}", f"bob-{uid()}"
    doc = start(engine, owner)
    with engine.begin() as conn:
        conn.execute(text("UPDATE documents SET archived = true WHERE document_id = :d"), {"d": doc.document_id})
    with SqlLibraryUnitOfWork(engine) as tx:
        mine = tx.documents.list_readable_by_ids(UserId(owner), [doc.document_id, DocumentId(uid())])
        theirs = tx.documents.list_readable_by_ids(UserId(other), [doc.document_id])
        nothing = tx.documents.list_readable_by_ids(UserId(owner), [])
    assert [(d.document_id, d.archived) for d in mine] == [(doc.document_id, True)]
    assert theirs == [] and nothing == []


def test_subject_ids_readable_by_counts_only_ready_documents(engine: Engine) -> None:
    owner, other = f"ada-{uid()}", f"bob-{uid()}"
    waiting, chosen, theirs = start(engine, owner), start(engine, owner), start(engine, other)
    for d in (waiting, chosen, theirs):
        link(engine, d, stored_content(engine, d.owner_id))
    with SqlLibraryUnitOfWork(engine) as tx:
        for d, pick in ((waiting, None), (chosen, GENERAL), (theirs, GENERAL)):
            loaded = tx.documents.get_by_upload_for_update(d.upload_id)
            assert loaded is not None
            loaded.await_subjects()
            if pick:
                loaded.choose_subjects([pick])
            tx.documents.save(loaded)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        assert tx.documents.subject_ids_readable_by(UserId(owner)) == {GENERAL}
        assert tx.documents.subject_ids_readable_by(UserId(f"nobody-{uid()}")) == set()


def test_list_processing_for_content_excludes_ready_and_failed(engine: Engine) -> None:
    owners = [f"u{i}-{uid()}" for i in range(3)]
    docs = [start(engine, o) for o in owners]
    content = stored_content(engine, owners[0])
    for d in docs:
        link(engine, d, content)
    with SqlLibraryUnitOfWork(engine) as tx:
        ready = tx.documents.get_by_upload_for_update(docs[1].upload_id)
        failed = tx.documents.get_by_upload_for_update(docs[2].upload_id)
        assert ready is not None and failed is not None
        ready.await_subjects()
        ready.choose_subjects([GENERAL])
        failed.fail("nope")
        tx.documents.save(ready)
        tx.documents.save(failed)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        processing = tx.documents.list_processing_for_content_for_update(content.content_id)
    assert [d.document_id for d in processing] == [docs[0].document_id]


def one_hot(i: int) -> list[float]:
    vector = [0.0] * 1024
    vector[i] = 1.0
    return vector


def searchable_document(engine: Engine, owner: str, hot: list[int], *, ready: bool = True) -> Document:
    """A document of `owner` in General whose content has one chunk per index in `hot`, each a one-hot vector."""
    doc = start(engine, owner, f"{uid()}.pdf")
    content = stored_content(engine, owner)
    link(engine, doc, content)
    with SqlLibraryUnitOfWork(engine) as tx:
        chunks = [Chunk(content.content_id, n, n + 1, f"chunk {i}", one_hot(i)) for n, i in enumerate(hot)]
        tx.chunks.replace(content.content_id, chunks)
        if ready:
            loaded = tx.documents.get_by_upload_for_update(doc.upload_id)
            assert loaded is not None
            loaded.await_subjects()
            loaded.choose_subjects([GENERAL])
            tx.documents.save(loaded)
        tx.commit()
    return doc


def search(
    engine: Engine, user: str, i: int, k: int = 5, document_ids: list[DocumentId] | None = None
) -> list[ChunkHit]:
    with SqlLibraryUnitOfWork(engine) as tx:
        return tx.chunks.search(UserId(user), one_hot(i), k, document_ids)


def test_search_returns_the_owners_chunk_with_title_page_and_score(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    doc = searchable_document(engine, owner, [7])
    [hit] = search(engine, owner, 7)
    assert (hit.document_id, hit.page, hit.text, hit.document_title) == (doc.document_id, 1, "chunk 7", doc.file_name)
    assert hit.score == pytest.approx(1.0)


def test_search_covers_documents_in_any_subject(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    other = SubjectId(uid())
    doc = searchable_document(engine, owner, [12])
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO subjects (subject_id, canonical_name, normalized_name) VALUES (:id, :n, :n)"),
            {"id": other, "n": f"subject {other}"},
        )
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.documents.get_by_upload_for_update(doc.upload_id)
        assert loaded is not None
        loaded.choose_subjects([other])
        tx.documents.save(loaded)
        tx.commit()
    [hit] = search(engine, owner, 12)
    assert hit.document_id == doc.document_id


def test_search_never_returns_another_learners_chunks(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    searchable_document(engine, owner, [8])
    assert search(engine, f"bob-{uid()}", 8) == []


def test_search_skips_archived_documents(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    doc = searchable_document(engine, owner, [10])
    with engine.begin() as conn:
        conn.execute(text("update documents set archived = true where document_id = :d"), {"d": doc.document_id})
    assert search(engine, owner, 10) == []


def test_search_skips_a_document_still_processing(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    searchable_document(engine, owner, [11], ready=False)
    assert search(engine, owner, 11) == []


def test_search_with_document_ids_returns_only_those_documents(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    first = searchable_document(engine, owner, [30])
    searchable_document(engine, owner, [31])
    hits = search(engine, owner, 31, document_ids=[first.document_id])
    assert {h.document_id for h in hits} == {first.document_id}
    assert search(engine, owner, 30, document_ids=[]) == []


def test_search_with_document_ids_skips_an_archived_document(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    doc = searchable_document(engine, owner, [32])
    with engine.begin() as conn:
        conn.execute(text("update documents set archived = true where document_id = :d"), {"d": doc.document_id})
    assert search(engine, owner, 32, document_ids=[doc.document_id]) == []


def test_search_with_another_learners_document_id_returns_nothing(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    doc = searchable_document(engine, owner, [33])
    assert search(engine, f"bob-{uid()}", 33, document_ids=[doc.document_id]) == []


def test_search_orders_nearest_first_and_limits_to_k(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    searchable_document(engine, owner, [20, 21, 22])
    hits = search(engine, owner, 21, k=2)
    assert len(hits) == 2 and hits[0].text == "chunk 21"
    assert hits[0].score == pytest.approx(1.0) and hits[1].score == pytest.approx(0.0)


def description() -> DocumentDescription:
    return parse_description(
        {
            "title": "Attention Is All You Need",
            "authors": ["Ashish Vaswani", "Noam Shazeer"],
            "year": 2017,
            "doi": "10.5555/3295222.3295349",
            "summary": "Introduces the Transformer, a model built on attention alone.",
            "proposed_subject_names": ["Machine learning", "Natural language processing", "Neural networks"],
        }
    )


def test_described_content_round_trips(engine: Engine) -> None:
    content = stored_content(engine, f"ada-{uid()}")
    described = description()
    with SqlLibraryUnitOfWork(engine) as tx:
        locked = tx.contents.get_for_update(content.content_id)
        assert locked is not None
        locked.describe(described, [0.5] * 1024)
        tx.contents.save(locked)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.contents.get(content.content_id)
    assert loaded is not None
    assert (loaded.title, loaded.year, loaded.doi) == (described.title, 2017, described.doi)
    assert loaded.summary == described.summary
    assert loaded.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert loaded.proposed_subject_names == list(described.proposed_subject_names)
    assert loaded.work_key == described.work_key
    assert isinstance(loaded.summary_embedding, list)
    assert loaded.summary_embedding == [0.5] * 1024
    assert all(isinstance(v, float) for v in loaded.summary_embedding)


def test_an_undescribed_content_has_empty_description_fields(engine: Engine) -> None:
    content = stored_content(engine, f"ada-{uid()}")
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.contents.get(content.content_id)
    assert loaded is not None
    assert (loaded.title, loaded.summary, loaded.summary_embedding, loaded.work_key) == (None, None, None, None)
    assert (loaded.authors, loaded.proposed_subject_names) == ([], [])


def test_listing_shows_the_content_title_and_the_override_wins(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    content = stored_content(engine, owner)
    described = description()
    with SqlLibraryUnitOfWork(engine) as tx:
        locked = tx.contents.get_for_update(content.content_id)
        assert locked is not None
        locked.describe(described, [0.5] * 1024)
        tx.contents.save(locked)
        tx.commit()
    titled, plain = start(engine, owner, "titled.pdf"), start(engine, owner, "plain.pdf")
    link(engine, titled, content)

    def titles() -> dict[str, str]:
        with SqlLibraryUnitOfWork(engine) as tx:
            return {d.document_id: d.title for d in tx.documents.list_readable_by(UserId(owner))}

    assert titles() == {titled.document_id: "Attention Is All You Need", plain.document_id: "plain.pdf"}
    with engine.begin() as conn:
        conn.execute(
            text("update documents set title_override = 'My notes' where document_id = :d"), {"d": titled.document_id}
        )
    assert titles()[titled.document_id] == "My notes"


def fail_content(engine: Engine, content: Content) -> None:
    with SqlLibraryUnitOfWork(engine) as tx:
        locked = tx.contents.get_for_update(content.content_id)
        assert locked is not None
        locked.fail(UNREADABLE_PDF)
        tx.contents.save(locked)
        tx.commit()


def test_retry_attempts_and_failed_document_locks_round_trip(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    content = stored_content(engine, owner)
    failed, processing = start(engine, owner, "a.pdf"), start(engine, f"bob-{uid()}", "b.pdf")  # one per owner
    other = start(engine, owner)
    for doc in (failed, processing):
        link(engine, doc, content)
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.documents.get_by_upload_for_update(failed.upload_id)
        assert loaded is not None
        loaded.fail(UNREADABLE_PDF)
        tx.documents.save(loaded)
        tx.commit()
    fail_content(engine, content)

    with SqlLibraryUnitOfWork(engine) as tx:
        by_id = {d.document_id: d for d in tx.documents.list_readable_by(UserId(owner))}
        assert by_id[failed.document_id].content_attempts == 1
        assert by_id[other.document_id].content_attempts is None
        assert tx.documents.get(DocumentId(uid())) is None
        found = tx.documents.get(failed.document_id)
        assert found is not None and found.document_id == failed.document_id
        assert [d.document_id for d in tx.documents.list_failed_for_content_for_update(content.content_id)] == [
            failed.document_id
        ]
        locked = tx.contents.get_for_update(content.content_id)
        assert locked is not None
        locked.retry(3)
        tx.contents.save(locked)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        again = tx.contents.get(content.content_id)
        relisted = {d.document_id: d for d in tx.documents.list_readable_by(UserId(owner))}
    assert again is not None and (again.state, again.attempts) == ("processing", 2)
    assert relisted[failed.document_id].content_attempts == 2


def test_find_by_sha256_is_owner_only_and_skips_unlinked_but_includes_archived(engine: Engine) -> None:
    ada, bob, carol = f"ada-{uid()}", f"bob-{uid()}", f"carol-{uid()}"
    content = stored_content(engine, ada)
    sha = content.sha256
    with SqlLibraryUnitOfWork(engine) as tx:  # bob uploads the same bytes: his own content
        bobs_content, created = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(bob)))
        assert created
        tx.commit()
    mine, bobs = start(engine, ada), start(engine, bob)
    start(engine, ada)  # still processing: never matches
    link(engine, mine, content)
    link(engine, bobs, bobs_content)

    def find(user: str, digest: str = sha) -> DocumentId | None:
        with SqlLibraryUnitOfWork(engine) as tx:
            found = tx.documents.get_readable_by_sha256(UserId(user), digest)
        return found.document_id if found else None

    assert find(ada) == mine.document_id
    assert find(bob) == bobs.document_id
    assert find(carol) is None
    assert find(ada, "0" * 64) is None

    with engine.begin() as conn:
        conn.execute(text("UPDATE documents SET archived = true WHERE document_id = :d"), {"d": mine.document_id})
    with SqlLibraryUnitOfWork(engine) as tx:  # an archived document is still found, flagged
        archived = tx.documents.get_readable_by_sha256(UserId(ada), sha)
    assert archived is not None and archived.document_id == mine.document_id and archived.archived


def test_listing_returns_the_authors_and_year_of_the_content(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    content = stored_content(engine, owner)
    with SqlLibraryUnitOfWork(engine) as tx:
        locked = tx.contents.get_for_update(content.content_id)
        assert locked is not None
        locked.describe(description(), [0.5] * 1024)
        tx.contents.save(locked)
        tx.commit()
    described, uploading = start(engine, owner, "described.pdf"), start(engine, owner, "uploading.pdf")
    link(engine, described, content)
    with SqlLibraryUnitOfWork(engine) as tx:
        by_id = {d.document_id: d for d in tx.documents.list_readable_by(UserId(owner))}
    assert by_id[described.document_id].content_authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert by_id[described.document_id].content_year == 2017
    assert (by_id[uploading.document_id].content_authors, by_id[uploading.document_id].content_year) == ([], None)


def library_to_filter(engine: Engine, owner: str) -> tuple[SubjectId, SubjectId]:
    """Ready `late.pdf` (s1, 2026-10-01T17:30Z), ready `early.pdf` (s2, 16:30Z), and a processing one."""
    s1, s2 = SubjectId(uid()), SubjectId(uid())
    with engine.begin() as conn:
        for s in (s1, s2):
            conn.execute(
                text("INSERT INTO subjects (subject_id, canonical_name, normalized_name) VALUES (:id, :n, :n)"),
                {"id": s, "n": f"subject {s}"},
            )
    for name, subject, created in (("late.pdf", s1, "2026-10-01T17:30Z"), ("early.pdf", s2, "2026-10-01T16:30Z")):
        doc = start(engine, owner, name)
        link(engine, doc, stored_content(engine, owner))
        with SqlLibraryUnitOfWork(engine) as tx:
            loaded = tx.documents.get_by_upload_for_update(doc.upload_id)
            assert loaded is not None
            loaded.await_subjects()
            loaded.choose_subjects([subject])
            tx.documents.save(loaded)
            tx.commit()
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE documents SET created_at = :t WHERE document_id = :d"),
                {"t": datetime.fromisoformat(created), "d": doc.document_id},
            )
    start(engine, owner, "processing.pdf")
    return s1, s2


def listed(engine: Engine, owner: str, document_filter: DocumentFilter) -> set[str]:
    with SqlLibraryUnitOfWork(engine) as tx:
        return {d.title for d in tx.documents.list_readable_by(UserId(owner), document_filter)}


def test_listing_filters_by_any_subject(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    s1, s2 = library_to_filter(engine, owner)
    assert listed(engine, owner, DocumentFilter(subject_ids=frozenset({s1}))) == {"late.pdf"}
    assert listed(engine, owner, DocumentFilter(subject_ids=frozenset({s1, s2}))) == {"late.pdf", "early.pdf"}
    assert listed(engine, owner, DocumentFilter(subject_ids=frozenset({SubjectId(uid())}))) == set()


def test_listing_filters_by_archived(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    active, archived = start(engine, owner, "active.pdf"), start(engine, owner, "archived.pdf")
    with engine.begin() as conn:
        conn.execute(text("UPDATE documents SET archived = true WHERE document_id = :d"), {"d": archived.document_id})
    assert listed(engine, owner, DocumentFilter(archived=False)) == {"active.pdf"}
    assert listed(engine, owner, DocumentFilter(archived=True)) == {"archived.pdf"}
    assert listed(engine, owner, DocumentFilter()) == {"active.pdf", "archived.pdf"}
    assert active.document_id != archived.document_id


def test_listing_filters_by_state(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    library_to_filter(engine, owner)
    ready = DocumentFilter(states=frozenset({DocumentState.READY}))
    assert listed(engine, owner, ready) == {"late.pdf", "early.pdf"}
    assert listed(engine, owner, DocumentFilter(states=frozenset({DocumentState.PROCESSING}))) == {"processing.pdf"}
    assert listed(engine, owner, DocumentFilter(states=frozenset({DocumentState.FAILED}))) == set()


def test_listing_filters_by_the_upload_instant_range(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    library_to_filter(engine, owner)
    boundary = datetime(2026, 10, 1, 17, 0, tzinfo=UTC)  # 00:00 on 2 Oct in GMT+7
    assert listed(engine, owner, DocumentFilter(uploaded_before=boundary)) == {"early.pdf"}
    assert "early.pdf" not in listed(engine, owner, DocumentFilter(uploaded_from=boundary))
    assert "late.pdf" in listed(engine, owner, DocumentFilter(uploaded_from=boundary))
    exact = datetime(2026, 10, 1, 17, 30, tzinfo=UTC)
    assert "late.pdf" in listed(engine, owner, DocumentFilter(uploaded_from=exact))  # inclusive
    assert "late.pdf" not in listed(engine, owner, DocumentFilter(uploaded_before=exact))  # exclusive


def test_listing_combines_filters_and_stays_owner_only(engine: Engine) -> None:
    owner, other = f"ada-{uid()}", f"bob-{uid()}"
    s1, s2 = library_to_filter(engine, owner)
    everything = DocumentFilter(
        subject_ids=frozenset({s1, s2}),
        states=frozenset({DocumentState.READY}),
        uploaded_from=datetime(2026, 10, 1, 17, 0, tzinfo=UTC),
        uploaded_before=datetime(2026, 10, 2, 17, 0, tzinfo=UTC),
    )
    assert listed(engine, owner, everything) == {"late.pdf"}
    assert listed(engine, other, everything) == set()
