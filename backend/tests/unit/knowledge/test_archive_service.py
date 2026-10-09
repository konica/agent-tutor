"""ArchiveService: archive and restore keep everything but the flag (PRD §8 US-10, §9.5)."""

import copy

import pytest

from fakes import (
    TEST_LIMITS,
    FakeObjectStore,
    FixedClock,
    InMemoryLibrary,
    describing_chat_model,
    fake_embeddings,
    fake_tools,
    ingest_ready,
)
from smart_tutor.knowledge.application import (
    ArchiveService,
    DocumentNotFoundError,
    DocumentService,
    IngestionService,
    SearchService,
    UploadService,
)
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UserId

ART = SubjectId("art")
ADA = UserId("ada")


def test_archive_hides_chunks_and_subjects_until_restore() -> None:
    library, clock = InMemoryLibrary(), FixedClock()
    doc = ingest_ready(library, "ada", "attention mechanisms", [ART])
    archive = ArchiveService(library.unit_of_work, clock, max_attempts=3)
    docs = DocumentService(library.unit_of_work, max_attempts=3)
    search = SearchService(library.unit_of_work, fake_embeddings())

    view = archive.archive(ADA, doc)
    assert view.archived is True
    assert library.state.documents[doc].archived_at == clock.current
    assert search.search(ADA, "attention mechanisms") == []
    assert docs.learner_subjects(ADA) == frozenset()

    assert archive.restore(ADA, doc).archived is False
    assert [h.document_id for h in search.search(ADA, "attention mechanisms")] == [doc]
    assert docs.learner_subjects(ADA) == frozenset({ART})


def test_a_subject_stays_mine_while_another_active_document_has_it() -> None:
    library = InMemoryLibrary()
    archived = ingest_ready(library, "ada", "one", [ART])
    ingest_ready(library, "ada", "two", [ART])
    ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3).archive(ADA, archived)
    assert DocumentService(library.unit_of_work, max_attempts=3).learner_subjects(ADA) == frozenset({ART})


def test_archiving_keeps_content_chunks_subjects_and_state() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "kept", [ART])
    before = copy.deepcopy(library.state)
    ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3).archive(ADA, doc)
    after = library.state.documents[doc]
    assert (after.state, after.subject_ids, after.content_id) == (
        before.documents[doc].state,
        before.documents[doc].subject_ids,
        before.documents[doc].content_id,
    )
    assert library.state.contents == before.contents and library.state.chunks == before.chunks


def test_another_learner_cant_archive_or_restore() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "mine")
    archive = ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3)
    with pytest.raises(DocumentNotFoundError):
        archive.archive(UserId("bob"), doc)
    with pytest.raises(DocumentNotFoundError):
        archive.restore(UserId("bob"), doc)
    with pytest.raises(DocumentNotFoundError):
        archive.archive(ADA, DocumentId("missing"))
    assert library.state.documents[doc].archived is False


def test_archiving_twice_keeps_the_first_time() -> None:
    library, clock = InMemoryLibrary(), FixedClock()
    doc = ingest_ready(library, "ada", "twice")
    archive = ArchiveService(library.unit_of_work, clock, max_attempts=3)
    archive.archive(ADA, doc)
    first = clock.current
    clock.current = first.replace(day=first.day + 1)
    archive.archive(ADA, doc)
    assert library.state.documents[doc].archived_at == first


def test_a_processing_document_archived_before_the_worker_finishes_stays_archived() -> None:
    library, clock, objects = InMemoryLibrary(), FixedClock(), FakeObjectStore()
    started = UploadService(library.unit_of_work, objects, clock, TEST_LIMITS).start_upload(ADA, "paper.pdf")
    doc = DocumentId(started.document_id)
    ArchiveService(library.unit_of_work, clock, max_attempts=3).archive(ADA, doc)
    archived_at = library.state.documents[doc].archived_at
    assert archived_at is not None

    objects.objects[started.fields["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    IngestionService(
        library.unit_of_work, objects, fake_tools(chat=describing_chat_model(None)), TEST_LIMITS
    ).ingest_upload(started.fields["key"])

    done = library.state.documents[doc]
    assert done.state.value == "awaiting_subjects"  # the worker's path ran
    assert (done.archived, done.archived_at) == (True, archived_at)
