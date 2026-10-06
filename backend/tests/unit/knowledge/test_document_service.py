import hashlib
from datetime import timedelta

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, fake_tools
from smart_tutor.knowledge.application import DocumentService, IngestionService, UploadService
from smart_tutor.shared.domain.ids import UserId


def test_lists_only_the_callers_documents_newest_first() -> None:
    library, clock = InMemoryLibrary(), FixedClock()
    uploads = UploadService(library.unit_of_work, FakeObjectStore(), clock, TEST_LIMITS)
    uploads.start_upload(UserId("ada"), "first.pdf")
    clock.current += timedelta(minutes=1)
    uploads.start_upload(UserId("ada"), "second.pdf")
    uploads.start_upload(UserId("bob"), "bobs.pdf")

    docs = DocumentService(library.unit_of_work).list_documents(UserId("ada"))

    assert [d.title for d in docs] == ["second.pdf", "first.pdf"]
    assert {d.state for d in docs} == {"processing"}
    assert all(d.failure_reason is None for d in docs)
    assert DocumentService(library.unit_of_work).list_documents(UserId("carol")) == []


PDF = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
SHA = hashlib.sha256(PDF).hexdigest()


def _ingested(library: InMemoryLibrary, objects: FakeObjectStore, owner: str) -> str:
    uploads = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS)
    started = uploads.start_upload(UserId(owner), "paper.pdf")
    objects.objects[started.fields["key"]] = PDF
    IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS).ingest_upload(started.fields["key"])
    return started.document_id


def test_finds_the_callers_document_by_hash() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    document_id = _ingested(library, objects, "ada")
    service = DocumentService(library.unit_of_work)
    assert service.find_in_library(UserId("ada"), SHA) == document_id
    assert service.find_in_library(UserId("ada"), "0" * 64) is None


def test_another_learners_file_is_not_in_your_library() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    _ingested(library, objects, "ada")
    assert DocumentService(library.unit_of_work).find_in_library(UserId("bob"), SHA) is None


def test_an_unlinked_or_duplicate_failed_document_never_matches() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    first = _ingested(library, objects, "ada")
    _ingested(library, objects, "ada")  # fails as a duplicate; its content_id stays null
    uploads = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS)
    uploads.start_upload(UserId("carol"), "paper.pdf")  # still processing: no content yet
    service = DocumentService(library.unit_of_work)
    assert service.find_in_library(UserId("ada"), SHA) == first
    assert service.find_in_library(UserId("carol"), SHA) is None
