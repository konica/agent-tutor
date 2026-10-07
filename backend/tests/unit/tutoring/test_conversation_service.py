"""ConversationService: a thread starts with the detected subjects, all the learner's own (PRD §8 US-3)."""

import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, InMemoryThreads, ingest_ready
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID
from smart_tutor.tutoring.application import ConversationService, NoDocumentsError, ThreadSubjectsError

S2 = SubjectId("00000000-0000-4000-8000-000000000002")


def service(library: InMemoryLibrary, threads: InMemoryThreads, clock: FixedClock) -> ConversationService:
    return ConversationService(threads, DocumentService(library.unit_of_work, max_attempts=3), clock)


def test_the_subjects_for_a_new_thread_are_the_learners_sorted() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention is all you need.", subject_ids=[S2])
    ingest_ready(library, "ada", "Gradient descent.")  # General
    ingest_ready(library, "bob", "Photosynthesis.", subject_ids=[SubjectId("00000000-0000-4000-8000-000000000009")])
    subjects = service(library, InMemoryThreads(), FixedClock()).subjects_for_new_thread(UserId("ada"))
    assert subjects == [GENERAL_SUBJECT_ID, S2]


def test_starts_a_thread_with_the_detected_subjects() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.", subject_ids=[GENERAL_SUBJECT_ID, S2])

    thread = service(library, threads, clock).start_thread(UserId("ada"), [S2, GENERAL_SUBJECT_ID])

    assert thread.user_id == "ada" and thread.subject_ids == (S2, GENERAL_SUBJECT_ID)
    assert thread.created_at == clock.now()
    assert threads.threads == {thread.thread_id: thread}


def test_a_learner_without_documents_cannot_start_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "bob", "Gradient descent.")  # someone else's document doesn't count

    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).subjects_for_new_thread(UserId("ada"))
    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), [GENERAL_SUBJECT_ID])
    assert threads.threads == {}


def test_a_processing_document_is_not_enough_to_start_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(
        UserId("ada"), "processing.pdf"
    )

    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).subjects_for_new_thread(UserId("ada"))
    assert threads.threads == {}


def test_a_subject_the_learner_does_not_have_is_refused() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "ada", "Attention is all you need.")
    with pytest.raises(ThreadSubjectsError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), [S2])
    assert threads.threads == {}


def test_no_subjects_or_more_than_three_is_refused() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    many = [SubjectId(f"00000000-0000-4000-8000-00000000000{i}") for i in range(1, 5)]
    ingest_ready(library, "ada", "a", subject_ids=many[:3])
    ingest_ready(library, "ada", "b", subject_ids=many[3:])
    with pytest.raises(ThreadSubjectsError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), [])
    with pytest.raises(ThreadSubjectsError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), many)
    assert threads.threads == {}
