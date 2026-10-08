import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, fake_tools, ingest_ready
from smart_tutor.knowledge.application import DocumentService, IngestionService, UploadService
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID


def test_lists_only_the_callers_documents_newest_first() -> None:
    library, clock = InMemoryLibrary(), FixedClock()
    uploads = UploadService(library.unit_of_work, FakeObjectStore(), clock, TEST_LIMITS)
    uploads.start_upload(UserId("ada"), "first.pdf")
    clock.current += timedelta(minutes=1)
    uploads.start_upload(UserId("ada"), "second.pdf")
    uploads.start_upload(UserId("bob"), "bobs.pdf")

    docs = DocumentService(library.unit_of_work, max_attempts=3).list_documents(UserId("ada"))

    assert [d.title for d in docs] == ["second.pdf", "first.pdf"]
    assert {d.state for d in docs} == {"processing"}
    assert all(d.failure_reason is None for d in docs)
    assert DocumentService(library.unit_of_work, max_attempts=3).list_documents(UserId("carol")) == []


ART, BIO = SubjectId("art"), SubjectId("bio")


def _ready_at(library: InMemoryLibrary, owner: str, text: str, created_at: datetime, subject: SubjectId) -> DocumentId:
    document_id = ingest_ready(library, owner, text, [subject])
    library.state.documents[document_id].created_at = created_at
    return document_id


def test_a_view_carries_the_authors_and_year_of_its_content() -> None:
    library = InMemoryLibrary()
    described = ingest_ready(library, "ada", "Attention is all you need.")
    content = library.state.contents[library.state.documents[described].content_id or ""]
    content.authors, content.year = ["Ashish Vaswani", "Noam Shazeer"], 2017
    UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(
        UserId("ada"), "uploading.pdf"
    )

    views = {v.title: v for v in DocumentService(library.unit_of_work, max_attempts=3).list_documents(UserId("ada"))}

    assert (views["uploading.pdf"].authors, views["uploading.pdf"].year) == ((), None)
    (with_authors,) = (v for v in views.values() if v.authors)
    assert (with_authors.authors, with_authors.year) == (("Ashish Vaswani", "Noam Shazeer"), 2017)


def test_the_list_narrows_by_subject_state_and_upload_dates_in_gmt_plus_7() -> None:
    library = InMemoryLibrary()
    # 2026-10-01T17:30Z is 00:30 on 2 Oct in GMT+7
    late = _ready_at(library, "ada", "late", datetime(2026, 10, 1, 17, 30, tzinfo=UTC), ART)
    early = _ready_at(library, "ada", "early", datetime(2026, 10, 1, 16, 30, tzinfo=UTC), BIO)
    UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(
        UserId("ada"), "processing.pdf"
    )
    docs = DocumentService(library.unit_of_work, max_attempts=3)

    def ids(**kwargs: Any) -> set[str]:
        return {v.document_id for v in docs.list_documents(UserId("ada"), **kwargs) if v.state == "ready"}

    assert ids(subject_ids=[ART]) == {late}
    assert ids(subject_ids=[ART, BIO]) == {late, early}
    assert {v.title for v in docs.list_documents(UserId("ada"), states=["processing"])} == {"processing.pdf"}
    assert ids(uploaded_to=date(2026, 10, 1)) == {early}
    assert ids(uploaded_from=date(2026, 10, 2)) == {late}
    assert ids(uploaded_from=date(2026, 10, 1), uploaded_to=date(2026, 10, 1)) == {early}
    assert ids(uploaded_from=date(2026, 10, 3)) == set()
    assert ids(uploaded_from=date(2026, 10, 3), uploaded_to=date(2026, 10, 1)) == set()
    assert ids(subject_ids=[BIO], states=["ready"], uploaded_to=date(2026, 10, 1)) == {early}
    assert ids(subject_ids=[ART], uploaded_to=date(2026, 10, 1)) == set()


def test_another_learners_documents_never_appear_under_any_filter() -> None:
    library = InMemoryLibrary()
    _ready_at(library, "bob", "bobs", datetime(2026, 10, 2, tzinfo=UTC), ART)
    docs = DocumentService(library.unit_of_work, max_attempts=3)
    everything: dict[str, Any] = {
        "subject_ids": [ART],
        "states": ["ready"],
        "uploaded_from": date(2026, 1, 1),
        "uploaded_to": date(2026, 12, 31),
    }
    assert docs.list_documents(UserId("ada"), **everything) == []
    assert len(docs.list_documents(UserId("bob"), **everything)) == 1


def test_learner_subjects_are_those_of_ready_unarchived_documents_only() -> None:
    library = InMemoryLibrary()
    docs = DocumentService(library.unit_of_work, max_attempts=3)
    ada_doc = ingest_ready(library, "ada", "Attention is all you need.")
    ingest_ready(library, "bob", "Gradient descent.")
    UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(
        UserId("carol"), "processing.pdf"
    )

    assert docs.learner_subjects(UserId("ada")) == frozenset({GENERAL_SUBJECT_ID})
    assert docs.learner_subjects(UserId("carol")) == frozenset()  # only a processing document
    library.state.documents[ada_doc].archived = True
    assert docs.learner_subjects(UserId("ada")) == frozenset()
    assert docs.learner_subjects(UserId("bob")) == frozenset({GENERAL_SUBJECT_ID})


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
    service = DocumentService(library.unit_of_work, max_attempts=3)
    assert service.find_in_library(UserId("ada"), SHA) == document_id
    assert service.find_in_library(UserId("ada"), "0" * 64) is None


def test_another_learners_file_is_not_in_your_library() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    _ingested(library, objects, "ada")
    assert DocumentService(library.unit_of_work, max_attempts=3).find_in_library(UserId("bob"), SHA) is None


def test_an_unlinked_or_duplicate_failed_document_never_matches() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    first = _ingested(library, objects, "ada")
    _ingested(library, objects, "ada")  # fails as a duplicate; its content_id stays null
    uploads = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS)
    uploads.start_upload(UserId("carol"), "paper.pdf")  # still processing: no content yet
    service = DocumentService(library.unit_of_work, max_attempts=3)
    assert service.find_in_library(UserId("ada"), SHA) == first
    assert service.find_in_library(UserId("carol"), SHA) is None
