"""DeleteService: a delete removes the document, its content, chunks, and every file version (PRD §8 US-10c, §9.5)."""

import logging
import uuid

import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, ingest_ready
from fakes.knowledge import _Documents
from smart_tutor.knowledge.application import DeleteService, DocumentNotFoundError, DocumentStateError, UploadService
from smart_tutor.knowledge.domain.content import content_key, pages_key
from smart_tutor.knowledge.domain.document import DocumentState
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UserId

ART = SubjectId("art")
ADA = UserId("ada")


def service(
    library: InMemoryLibrary, objects: FakeObjectStore
) -> tuple[DeleteService, list[tuple[UserId, DocumentId, str]]]:
    kept: list[tuple[UserId, DocumentId, str]] = []
    return DeleteService(library.unit_of_work, objects, lambda u, d, t: kept.append((u, d, t))), kept


def _started(library: InMemoryLibrary, owner: str) -> DocumentId:
    started = UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(
        UserId(owner), "paper.pdf"
    )
    return started.document_id


def test_delete_removes_the_document_its_content_chunks_and_every_file_version() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "Attention weighs tokens.", [ART])
    content_id = library.state.documents[doc].content_id or ""
    title = library.state.documents[doc].title
    deleter, kept = service(library, objects)

    deleter.delete(ADA, DocumentId(doc))

    assert doc not in library.state.documents
    assert content_id not in library.state.contents and content_id not in library.state.chunks
    assert sorted(objects.versions_deleted) == sorted([content_key(ADA, content_id), pages_key(ADA, content_id)])
    assert kept == [(ADA, DocumentId(doc), title)]


def test_another_learners_or_a_missing_document_is_not_found_and_nothing_changes() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "Attention weighs tokens.", [ART])
    content_id = library.state.documents[doc].content_id or ""
    deleter, kept = service(library, objects)

    for user, document_id in [(UserId("bob"), doc), (ADA, str(uuid.uuid4()))]:
        with pytest.raises(DocumentNotFoundError, match="Document not found"):
            deleter.delete(user, DocumentId(document_id))

    assert doc in library.state.documents
    assert content_id in library.state.contents and content_id in library.state.chunks
    assert kept == [] and objects.versions_deleted == []


def test_a_processing_document_cant_be_deleted() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = _started(library, "ada")
    deleter, kept = service(library, objects)

    with pytest.raises(DocumentStateError, match="still processing"):
        deleter.delete(ADA, doc)

    assert doc in library.state.documents
    assert kept == [] and objects.versions_deleted == []


def test_a_failed_document_without_content_is_deleted_without_touching_storage() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = _started(library, "ada")
    with library.unit_of_work() as tx:
        document = tx.documents.get(doc)
        assert document is not None
        document.fail("This file isn't a readable PDF")
        tx.documents.save(document)
        tx.commit()
    assert library.state.documents[doc].content_id is None
    deleter, kept = service(library, objects)

    deleter.delete(ADA, doc)

    assert doc not in library.state.documents
    assert len(kept) == 1
    assert objects.versions_deleted == []


def test_an_archived_document_can_be_deleted() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "Attention weighs tokens.", [ART])
    library.state.documents[doc].archived = True
    deleter, _ = service(library, objects)

    deleter.delete(ADA, DocumentId(doc))

    assert doc not in library.state.documents
    assert len(objects.versions_deleted) == 2


def test_the_state_is_checked_again_under_the_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "Attention weighs tokens.", [ART])
    library.state.documents[doc].state = DocumentState.FAILED
    original = _Documents.get_readable

    def retried_before_the_lock(
        self: _Documents, user_id: UserId, document_id: DocumentId, *, for_update: bool = False
    ) -> object:
        if for_update:  # a retry made it processing between the unlocked read and the locked one
            self._s.documents[document_id].state = DocumentState.PROCESSING
        return original(self, user_id, document_id, for_update=for_update)

    monkeypatch.setattr(_Documents, "get_readable", retried_before_the_lock)
    deleter, kept = service(library, objects)

    with pytest.raises(DocumentStateError):
        deleter.delete(ADA, DocumentId(doc))

    assert doc in library.state.documents
    assert kept == [] and objects.versions_deleted == []


def test_storage_failing_after_the_commit_is_logged_and_the_rows_stay_deleted(caplog: pytest.LogCaptureFixture) -> None:
    class Failing(FakeObjectStore):
        def delete_all_versions(self, key: str) -> None:
            raise RuntimeError("S3 down")

    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "Attention weighs tokens.", [ART])
    content_id = library.state.documents[doc].content_id or ""
    deleter, _ = service(library, Failing())

    with caplog.at_level(logging.ERROR):
        deleter.delete(ADA, DocumentId(doc))

    assert doc not in library.state.documents and content_id not in library.state.contents
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any(content_key(ADA, content_id) in m for m in errors)
    assert any(pages_key(ADA, content_id) in m for m in errors)
