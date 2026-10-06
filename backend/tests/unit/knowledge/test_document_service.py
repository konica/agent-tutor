from datetime import timedelta

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, ingest_ready
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID


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


def test_learner_subjects_are_those_of_ready_unarchived_documents_only() -> None:
    library = InMemoryLibrary()
    docs = DocumentService(library.unit_of_work)
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
