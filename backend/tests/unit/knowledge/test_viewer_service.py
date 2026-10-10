"""ViewerService: a short-lived PDF link for documents the caller can read (PRD §8 US-4b, §9.3 step 5)."""

from dataclasses import replace

import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, ingest_ready
from fakes.knowledge import fake_chunk_id
from smart_tutor.knowledge.application import (
    VIEWER_LINK_SECONDS,
    ArchiveService,
    ChunkNotFoundError,
    ChunkPassage,
    DocumentNotFoundError,
    DocumentStateError,
    UploadService,
    ViewerService,
)
from smart_tutor.knowledge.domain.document import DocumentState
from smart_tutor.shared.domain.ids import DocumentId, UserId

ADA = UserId("ada")


def viewer(library: InMemoryLibrary, objects: FakeObjectStore) -> ViewerService:
    return ViewerService(library.unit_of_work, objects, max_attempts=3)


def test_a_ready_document_gets_a_five_minute_link_to_its_content() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "attention mechanisms")
    content_id = library.state.documents[doc].content_id
    assert content_id is not None
    content = library.state.contents[content_id]
    content.title, content.authors, content.year = "Attention", ["Vaswani"], 2017

    found = viewer(library, objects).file(ADA, doc)

    key = f"contents/ada/{content_id}.pdf"
    assert VIEWER_LINK_SECONDS == 300
    assert objects.presigned_gets == [(key, 300)]
    assert (found.url, found.expires_in) == (f"https://s3.test/{key}?expires=300", 300)
    assert (found.view.title, found.view.authors, found.view.year) == ("Attention", ("Vaswani",), 2017)


def test_a_document_awaiting_subjects_can_be_opened() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "waiting")
    library.state.documents[doc].state = DocumentState.AWAITING_SUBJECTS
    assert viewer(library, objects).file(ADA, doc).view.state == "awaiting_subjects"


def test_an_archived_document_can_be_opened() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "archived")
    ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3).archive(ADA, doc)
    assert viewer(library, objects).file(ADA, doc).view.archived is True


def test_a_processing_document_has_no_file_yet() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    started = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS).start_upload(ADA, "p.pdf")
    with pytest.raises(DocumentStateError, match="can't be opened until it has been processed"):
        viewer(library, objects).file(ADA, DocumentId(started.document_id))
    assert objects.presigned_gets == []


def test_a_failed_document_has_no_file() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "failed")
    library.state.documents[doc].state = DocumentState.FAILED
    with pytest.raises(DocumentStateError):
        viewer(library, objects).file(ADA, doc)
    assert objects.presigned_gets == []


def test_another_learners_and_unknown_documents_are_not_found() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "mine")
    with pytest.raises(DocumentNotFoundError):
        viewer(library, objects).file(UserId("bob"), doc)
    with pytest.raises(DocumentNotFoundError):
        viewer(library, objects).file(ADA, DocumentId("unknown"))
    assert objects.presigned_gets == []


def _first_chunk_id(library: InMemoryLibrary, doc: DocumentId) -> str:
    content_id = library.state.documents[doc].content_id
    assert content_id is not None
    return fake_chunk_id(content_id, 0)


def test_a_cited_chunk_gives_its_document_page_offset_and_text() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "attention mechanisms")
    content_id = library.state.documents[doc].content_id
    assert content_id is not None
    library.state.chunks[content_id][0] = replace(library.state.chunks[content_id][0], start_index=12)
    chunk_id = _first_chunk_id(library, doc)

    found = viewer(library, objects).passage(ADA, chunk_id)

    assert found == ChunkPassage(chunk_id, doc, 1, 12, "attention mechanisms")


def test_a_chunk_of_an_archived_document_can_be_read() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "archived words")
    ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3).archive(ADA, doc)
    assert viewer(library, objects).passage(ADA, _first_chunk_id(library, doc)).document_id == doc


def test_another_learners_chunk_is_not_found() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "private words")
    with pytest.raises(ChunkNotFoundError, match="isn't in your library"):
        viewer(library, objects).passage(UserId("bob"), _first_chunk_id(library, doc))


def test_an_unknown_or_malformed_chunk_is_not_found() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    ingest_ready(library, "ada", "some words")
    for chunk_id in ("00000000-0000-4000-8000-000000000000", "not-a-uuid"):
        with pytest.raises(ChunkNotFoundError):
            viewer(library, objects).passage(ADA, chunk_id)
