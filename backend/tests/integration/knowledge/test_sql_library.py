"""SqlLibraryUnitOfWork against the Compose Postgres (`make up`)."""

import hashlib
import threading
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.domain.chunk import Chunk
from smart_tutor.knowledge.domain.content import UNREADABLE_PDF, Content
from smart_tutor.knowledge.domain.description import DocumentDescription, parse_description
from smart_tutor.knowledge.domain.document import DUPLICATE_UPLOAD, Document, DocumentFilter, DocumentState
from smart_tutor.knowledge.domain.search import ChunkHit
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
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


def test_replace_with_no_chunks_only_deletes(engine: Engine) -> None:
    content = stored_content(engine, f"ada-{uid()}")
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.chunks.replace(content.content_id, [chunk(content, 0, 1, 0.1)])
        tx.chunks.replace(content.content_id, [])
        tx.commit()
    with engine.connect() as conn:
        count = conn.execute(text("select count(*) from chunks where content_id = :c"), {"c": content.content_id})
        assert count.scalar_one() == 0


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


def test_get_readable_is_owner_only_and_skips_archived(engine: Engine) -> None:
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
        assert tx.documents.get_readable(UserId(owner), doc.document_id) is None


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


def search(engine: Engine, user: str, i: int, subjects: list[SubjectId] | None = None, k: int = 5) -> list[ChunkHit]:
    with SqlLibraryUnitOfWork(engine) as tx:
        return tx.chunks.search(UserId(user), one_hot(i), subjects or [GENERAL], k)


def test_search_returns_the_owners_chunk_with_title_page_and_score(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    doc = searchable_document(engine, owner, [7])
    [hit] = search(engine, owner, 7)
    assert (hit.document_id, hit.page, hit.text, hit.document_title) == (doc.document_id, 1, "chunk 7", doc.file_name)
    assert hit.score == pytest.approx(1.0)


def test_a_hit_names_the_requested_subjects_its_document_has(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    s1, s2 = sorted([SubjectId(uid()), SubjectId(uid())])
    doc = searchable_document(engine, owner, [12])
    with engine.begin() as conn:
        for s in (s1, s2):
            conn.execute(
                text("INSERT INTO subjects (subject_id, canonical_name, normalized_name) VALUES (:id, :n, :n)"),
                {"id": s, "n": f"subject {s}"},
            )
    with SqlLibraryUnitOfWork(engine) as tx:
        loaded = tx.documents.get_by_upload_for_update(doc.upload_id)
        assert loaded is not None
        loaded.choose_subjects([s1, s2])
        tx.documents.save(loaded)
        tx.commit()
    [only_s2] = search(engine, owner, 12, [s2])
    [both] = search(engine, owner, 12, [s2, s1])
    assert only_s2.subject_ids == (s2,)
    assert both.subject_ids == (s1, s2)


def test_search_never_returns_another_learners_chunks(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    searchable_document(engine, owner, [8])
    assert search(engine, f"bob-{uid()}", 8) == []


def test_search_ignores_documents_without_a_requested_subject(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    searchable_document(engine, owner, [9])
    assert search(engine, owner, 9, [SubjectId(uid())]) == []


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


def test_find_by_sha256_is_owner_only_and_skips_unlinked_and_archived(engine: Engine) -> None:
    ada, bob, carol = f"ada-{uid()}", f"bob-{uid()}", f"carol-{uid()}"
    content = stored_content(engine, ada)
    sha = content.sha256
    mine, bobs = start(engine, ada), start(engine, bob)
    start(engine, ada)  # still processing: never matches
    link(engine, mine, content)
    link(engine, bobs, content)

    def find(user: str, digest: str = sha) -> DocumentId | None:
        with SqlLibraryUnitOfWork(engine) as tx:
            return tx.documents.find_readable_by_sha256(UserId(user), digest)

    assert find(ada) == mine.document_id
    assert find(bob) == bobs.document_id
    assert find(carol) is None
    assert find(ada, "0" * 64) is None

    with engine.begin() as conn:
        conn.execute(text("UPDATE documents SET archived = true WHERE document_id = :d"), {"d": mine.document_id})
    assert find(ada) is None


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
