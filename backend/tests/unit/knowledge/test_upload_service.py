import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary
from smart_tutor.knowledge.application import FileLimits, InvalidFileNameError, UploadService
from smart_tutor.shared.domain.ids import UserId

UPLOAD = "b5f3c1a2-0d4e-4f6a-9b7c-1e2d3c4b5a69"
DOC = "0a1b2c3d-0000-4000-8000-000000000002"


def make(ids: list[str] | None = None) -> tuple[UploadService, InMemoryLibrary, FakeObjectStore]:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    it = iter(ids or [UPLOAD, DOC])
    return UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS, lambda: next(it)), library, objects


def test_start_upload_presigns_the_callers_key_with_the_pdf_policy() -> None:
    service, _, objects = make()
    started = service.start_upload(UserId("ada"), "paper.pdf")
    assert started.upload_id == UPLOAD
    assert started.document_id == DOC
    assert started.fields["key"] == f"uploads/ada/{UPLOAD}.pdf"
    assert objects.presigned == [(f"uploads/ada/{UPLOAD}.pdf", "application/pdf", 52_428_800, 600)]


def test_start_upload_records_the_upload_and_a_processing_document() -> None:
    service, library, _ = make()
    service.start_upload(UserId("ada"), "C:\\papers\\paper.pdf")
    doc = library.state.documents[DOC]
    assert (doc.owner_id, doc.upload_id, doc.file_name, doc.state) == ("ada", UPLOAD, "paper.pdf", "processing")
    assert library.state.uploads[UPLOAD].user_id == "ada"


def test_a_blank_name_stores_nothing() -> None:
    service, library, objects = make()
    with pytest.raises(InvalidFileNameError):
        service.start_upload(UserId("ada"), "   ")
    assert library.state.documents == {} and objects.presigned == []


def test_presigns_with_the_configured_size_limit() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    service = UploadService(library.unit_of_work, objects, FixedClock(), FileLimits(max_bytes=1234, max_pages=9))

    service.start_upload(UserId("ada"), "a.pdf")

    assert objects.presigned[-1][2] == 1234
