import pytest

from fakes import FakeObjectStore, FixedClock, InMemoryLibrary
from smart_tutor.knowledge.application import InvalidFileNameError, UploadService
from smart_tutor.shared.domain.ids import UserId


def make(ids: list[str] | None = None) -> tuple[UploadService, InMemoryLibrary, FakeObjectStore]:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    it = iter(ids or ["upload-1", "doc-1"])
    return UploadService(library.unit_of_work, objects, FixedClock(), lambda: next(it)), library, objects


def test_start_upload_presigns_the_callers_key_with_the_pdf_policy() -> None:
    service, _, objects = make()
    started = service.start_upload(UserId("ada"), "paper.pdf")
    assert started.upload_id == "upload-1"
    assert started.document_id == "doc-1"
    assert started.fields["key"] == "uploads/ada/upload-1.pdf"
    assert objects.presigned == [("uploads/ada/upload-1.pdf", "application/pdf", 52_428_800, 600)]


def test_start_upload_records_the_upload_and_a_processing_document() -> None:
    service, library, _ = make()
    service.start_upload(UserId("ada"), "C:\\papers\\paper.pdf")
    doc = library.state.documents["doc-1"]
    assert (doc.owner_id, doc.upload_id, doc.file_name, doc.state) == ("ada", "upload-1", "paper.pdf", "processing")
    assert library.state.uploads["upload-1"].user_id == "ada"


def test_a_blank_name_stores_nothing() -> None:
    service, library, objects = make()
    with pytest.raises(InvalidFileNameError):
        service.start_upload(UserId("ada"), "   ")
    assert library.state.documents == {} and objects.presigned == []
