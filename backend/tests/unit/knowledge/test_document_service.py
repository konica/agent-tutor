import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from fakes import (
    APP_TZ,
    TEST_LIMITS,
    TEST_UPLOAD_LIMITS,
    FakeObjectStore,
    FixedClock,
    InMemoryLibrary,
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
from smart_tutor.knowledge.domain.document import DocumentState
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID


def test_lists_only_the_callers_documents_newest_first() -> None:
    library, clock = InMemoryLibrary(), FixedClock()
    uploads = UploadService(
        library.unit_of_work, FakeObjectStore(), clock, TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    )
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
    UploadService(
        library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    ).start_upload(UserId("ada"), "uploading.pdf")

    views = {v.title: v for v in DocumentService(library.unit_of_work, max_attempts=3).list_documents(UserId("ada"))}

    assert (views["uploading.pdf"].authors, views["uploading.pdf"].year) == ((), None)
    (with_authors,) = (v for v in views.values() if v.authors)
    assert (with_authors.authors, with_authors.year) == (("Ashish Vaswani", "Noam Shazeer"), 2017)


def test_the_list_narrows_by_subject_state_and_upload_dates_in_gmt_plus_7() -> None:
    library = InMemoryLibrary()
    # 2026-10-01T17:30Z is 00:30 on 2 Oct in GMT+7
    late = _ready_at(library, "ada", "late", datetime(2026, 10, 1, 17, 30, tzinfo=UTC), ART)
    early = _ready_at(library, "ada", "early", datetime(2026, 10, 1, 16, 30, tzinfo=UTC), BIO)
    UploadService(
        library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    ).start_upload(UserId("ada"), "processing.pdf")
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
    UploadService(
        library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    ).start_upload(UserId("carol"), "processing.pdf")

    assert docs.learner_subjects(UserId("ada")) == frozenset({GENERAL_SUBJECT_ID})
    assert docs.learner_subjects(UserId("carol")) == frozenset()  # only a processing document
    library.state.documents[ada_doc].archived = True
    assert docs.learner_subjects(UserId("ada")) == frozenset()
    assert docs.learner_subjects(UserId("bob")) == frozenset({GENERAL_SUBJECT_ID})


PDF = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
SHA = hashlib.sha256(PDF).hexdigest()


def _ingested(library: InMemoryLibrary, objects: FakeObjectStore, owner: str) -> str:
    uploads = UploadService(
        library.unit_of_work, objects, FixedClock(), TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    )
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
    uploads = UploadService(
        library.unit_of_work, objects, FixedClock(), TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    )
    uploads.start_upload(UserId("carol"), "paper.pdf")  # still processing: no content yet
    service = DocumentService(library.unit_of_work, max_attempts=3)
    assert service.find_in_library(UserId("ada"), SHA) == first
    assert service.find_in_library(UserId("carol"), SHA) is None


def test_has_ready_documents_ignores_archived_and_unfinished_documents() -> None:
    library = InMemoryLibrary()
    docs = DocumentService(library.unit_of_work, max_attempts=3)
    ada = UserId("ada")
    UploadService(
        library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    ).start_upload(ada, "p.pdf")
    choosing = ingest_ready(library, "ada", "Awaiting subjects.")
    library.state.documents[choosing].state = DocumentState.AWAITING_SUBJECTS
    archived = ingest_ready(library, "ada", "Archived.")
    library.state.documents[archived].archived = True
    ingest_ready(library, "bob", "Bob's ready document.")  # another learner's never counts

    assert docs.has_ready_documents(ada) is False

    ingest_ready(library, "ada", "Ready and not archived.")
    assert docs.has_ready_documents(ada) is True
    assert docs.has_ready_documents(UserId("carol")) is False


def test_the_list_holds_active_documents_by_default_and_archived_ones_on_request() -> None:
    library = InMemoryLibrary()
    active = ingest_ready(library, "ada", "active")
    archived = ingest_ready(library, "ada", "archived")
    library.state.documents[archived].archived = True
    docs = DocumentService(library.unit_of_work, max_attempts=3)

    assert [d.document_id for d in docs.list_documents(UserId("ada"))] == [active]
    assert [d.document_id for d in docs.list_documents(UserId("ada"), archived=True)] == [archived]


def test_archived_documents_leave_my_subjects_ready_check_and_duplicate_check() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "only", [ART])
    library.state.documents[doc].archived = True
    docs = DocumentService(library.unit_of_work, max_attempts=3)
    sha = hashlib.sha256(b"only").hexdigest()

    assert docs.learner_subjects(UserId("ada")) == frozenset()
    assert docs.has_ready_documents(UserId("ada")) is False
    assert docs.find_in_library(UserId("ada"), sha) is None


def test_documents_by_id_returns_the_learners_documents_archived_included() -> None:
    library = InMemoryLibrary()
    a = ingest_ready(library, "learner-a", "Attention weighs tokens.")
    b = ingest_ready(library, "learner-a", "Gradient descent follows the slope.")
    other = ingest_ready(library, "learner-b", "Someone else's.")
    library.state.documents[b].archived = True
    service = DocumentService(library.unit_of_work, max_attempts=3)

    found = service.documents_by_id(UserId("learner-a"), [a, b, other, DocumentId("missing")])

    assert set(found) == {a, b}
    assert found[a].archived is False
    assert found[b].archived is True
    assert service.documents_by_id(UserId("learner-a"), []) == {}


ADA = UserId("ada")


def _describe(library: InMemoryLibrary, doc: DocumentId, **fields: Any) -> None:
    content_id = library.state.documents[doc].content_id
    assert content_id is not None
    with library.unit_of_work() as tx:
        content = tx.contents.get(content_id)
        assert content is not None
        for name, value in fields.items():
            setattr(content, name, value)
        tx.contents.save(content)
        tx.commit()


def test_details_carry_facts_summary_and_subjects() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    _describe(library, doc, title="Extracted", summary="A summary", doi="10.1/x", authors=["Yao"], year=2022)
    details = DocumentService(library.unit_of_work, max_attempts=3).details(ADA, doc)
    assert details.document.title == "Extracted"
    assert details.document.authors == ("Yao",) and details.document.year == 2022
    assert details.document.subject_ids == (ART,)
    assert (details.extracted_title, details.title_overridden) == ("Extracted", False)
    assert (details.doi, details.pages, details.summary) == ("10.1/x", 1, "A summary")
    assert details.file_name.endswith(".pdf")


def test_details_of_an_archived_document() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3).archive(ADA, doc)
    assert DocumentService(library.unit_of_work, max_attempts=3).details(ADA, doc).document.archived is True


def test_details_of_a_document_still_uploading_have_no_content_facts() -> None:
    library = InMemoryLibrary()
    started = UploadService(
        library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    ).start_upload(ADA, "p.pdf")
    details = DocumentService(library.unit_of_work, max_attempts=3).details(ADA, DocumentId(started.document_id))
    assert (details.document.title, details.extracted_title, details.pages, details.summary) == (
        "p.pdf",
        None,
        None,
        None,
    )


def test_details_of_another_learners_document_is_not_found() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    with pytest.raises(DocumentNotFoundError):
        DocumentService(library.unit_of_work, max_attempts=3).details(UserId("bob"), doc)


def test_set_title_and_reset() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    _describe(library, doc, title="Extracted")
    docs = DocumentService(library.unit_of_work, max_attempts=3)
    renamed = docs.set_title(ADA, doc, "  Mine ")
    assert (renamed.document.title, renamed.title_overridden) == ("Mine", True)
    assert [v.title for v in docs.list_documents(ADA)] == ["Mine"]
    reset = docs.set_title(ADA, doc, None)
    assert (reset.document.title, reset.title_overridden) == ("Extracted", False)
    assert library.state.contents[library.state.documents[doc].content_id or ""].title == "Extracted"


def test_set_title_of_another_learners_document_is_not_found() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    with pytest.raises(DocumentNotFoundError):
        DocumentService(library.unit_of_work, max_attempts=3).set_title(UserId("bob"), doc, "Mine")
    assert library.state.documents[doc].title_override is None


def test_a_renamed_document_is_cited_by_its_new_title() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention mechanisms", [ART])
    DocumentService(library.unit_of_work, max_attempts=3).set_title(ADA, doc, "Mine")
    hits = SearchService(library.unit_of_work, fake_embeddings()).search(ADA, "attention mechanisms")
    assert [h.document_title for h in hits] == ["Mine"]
