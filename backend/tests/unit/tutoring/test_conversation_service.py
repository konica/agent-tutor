"""ConversationService.start_thread: a learner with exactly one subject starts a thread with it (PRD §8 US-3)."""

import copy

import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, InMemoryThreads, ingest_ready
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID
from smart_tutor.tutoring.application import ConversationService, DetectionUnavailableError, NoDocumentsError


def service(library: InMemoryLibrary, threads: InMemoryThreads, clock: FixedClock) -> ConversationService:
    return ConversationService(threads, DocumentService(library.unit_of_work, max_attempts=3), clock)


def test_a_learner_with_one_subject_starts_a_thread_with_it() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")

    thread = service(library, threads, clock).start_thread(UserId("ada"))

    assert thread.user_id == "ada"
    assert thread.subject_ids == (GENERAL_SUBJECT_ID,)
    assert thread.created_at == clock.now()
    assert threads.threads == {thread.thread_id: thread}


def test_a_learner_without_documents_cannot_start_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "bob", "Gradient descent.")  # someone else's document doesn't count

    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).start_thread(UserId("ada"))
    assert threads.threads == {}


def test_a_processing_document_is_not_enough_to_start_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(
        UserId("ada"), "processing.pdf"
    )

    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).start_thread(UserId("ada"))
    assert threads.threads == {}


def test_several_subjects_need_detection_which_is_not_built_yet() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    first = ingest_ready(library, "ada", "Attention is all you need.")
    second = copy.deepcopy(library.state.documents[first])
    second.document_id = DocumentId("doc-2")
    second.subject_ids = [SubjectId("00000000-0000-4000-8000-000000000002")]
    library.state.documents[second.document_id] = second

    with pytest.raises(DetectionUnavailableError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"))
    assert threads.threads == {}
