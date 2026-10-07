"""ConversationService: a thread starts with the detected subjects, all the learner's own (PRD §8 US-3)."""

import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, InMemoryThreads, ingest_ready
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID
from smart_tutor.tutoring.application import (
    ConversationService,
    NoDocumentsError,
    ThreadNotFoundError,
    ThreadNotPendingError,
    ThreadSubjectsError,
)

TID = ThreadId("t1")
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

    thread = service(library, threads, clock).start_thread(UserId("ada"), [S2, GENERAL_SUBJECT_ID], TID, "Q?")

    assert thread.user_id == "ada" and thread.subject_ids == (S2, GENERAL_SUBJECT_ID)
    assert thread.created_at == clock.now() and thread.thread_id == TID and thread.title == "Q?"
    assert threads.threads == {thread.thread_id: thread}


def test_a_learner_without_documents_cannot_start_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "bob", "Gradient descent.")  # someone else's document doesn't count

    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).subjects_for_new_thread(UserId("ada"))
    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), [GENERAL_SUBJECT_ID], TID, "Q?")
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
        service(library, threads, FixedClock()).start_thread(UserId("ada"), [S2], TID, "Q?")
    assert threads.threads == {}


def test_no_subjects_or_more_than_three_is_refused() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    many = [SubjectId(f"00000000-0000-4000-8000-00000000000{i}") for i in range(1, 5)]
    ingest_ready(library, "ada", "a", subject_ids=many[:3])
    ingest_ready(library, "ada", "b", subject_ids=many[3:])
    with pytest.raises(ThreadSubjectsError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), [], TID, "Q?")
    with pytest.raises(ThreadSubjectsError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), many, TID, "Q?")
    assert threads.threads == {}


def ready_library() -> InMemoryLibrary:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention is all you need.", subject_ids=[GENERAL_SUBJECT_ID, S2])
    return library


def test_a_pending_thread_is_stored_without_subjects() -> None:
    threads = InMemoryThreads()
    thread = service(ready_library(), threads, FixedClock()).start_pending_thread(UserId("ada"), TID, "Which one?")
    assert thread.subject_ids == () and thread.title == "Which one?" and thread.awaiting_subjects
    assert threads.threads == {TID: thread}


def test_a_learner_without_documents_cannot_start_a_pending_thread() -> None:
    threads = InMemoryThreads()
    with pytest.raises(NoDocumentsError):
        service(InMemoryLibrary(), threads, FixedClock()).start_pending_thread(UserId("ada"), TID, "Q?")
    assert threads.threads == {}


def test_pending_thread_is_only_the_owners_and_only_while_pending() -> None:
    library, threads = ready_library(), InMemoryThreads()
    svc = service(library, threads, FixedClock())
    svc.start_pending_thread(UserId("ada"), TID, "Q?")
    assert svc.pending_thread(UserId("ada"), TID).thread_id == TID
    with pytest.raises(ThreadNotFoundError):
        svc.pending_thread(UserId("bob"), TID)
    with pytest.raises(ThreadNotFoundError):
        svc.get_thread(UserId("ada"), ThreadId("missing"))
    assert svc.bind_subjects(UserId("ada"), TID, [S2]) is True
    with pytest.raises(ThreadNotPendingError):
        svc.pending_thread(UserId("ada"), TID)


@pytest.mark.parametrize("choice", [[], ["1", "2", "3", "4"], ["1", "1"], ["9"]])
def test_a_choice_must_be_one_to_three_distinct_subjects_of_the_learner(choice: list[str]) -> None:
    library = InMemoryLibrary()
    ids = [SubjectId(f"00000000-0000-4000-8000-00000000000{i}") for i in range(1, 5)]
    ingest_ready(library, "ada", "a", subject_ids=ids[:3])
    ingest_ready(library, "ada", "b", subject_ids=ids[3:])
    wanted = [SubjectId(f"00000000-0000-4000-8000-00000000000{c}") for c in choice]
    with pytest.raises(ThreadSubjectsError):
        service(library, InMemoryThreads(), FixedClock()).check_choice(UserId("ada"), wanted)


def test_one_to_three_of_the_learners_subjects_are_a_valid_choice() -> None:
    svc = service(ready_library(), InMemoryThreads(), FixedClock())
    assert svc.check_choice(UserId("ada"), [S2, GENERAL_SUBJECT_ID]) is None


def test_bind_subjects_binds_once_and_only_for_the_owner() -> None:
    library, threads = ready_library(), InMemoryThreads()
    svc = service(library, threads, FixedClock())
    svc.start_pending_thread(UserId("ada"), TID, "Q?")
    assert svc.bind_subjects(UserId("ada"), TID, [S2]) is True
    assert svc.bind_subjects(UserId("ada"), TID, [GENERAL_SUBJECT_ID]) is False
    assert threads.threads[TID].subject_ids == (S2,)
    ingest_ready(library, "bob", "x", subject_ids=[S2])
    svc.start_pending_thread(UserId("ada"), ThreadId("t2"), "Q2?")
    assert svc.bind_subjects(UserId("bob"), ThreadId("t2"), [S2]) is False
    assert threads.threads[ThreadId("t2")].awaiting_subjects


def test_an_invalid_choice_leaves_the_thread_pending() -> None:
    threads = InMemoryThreads()
    svc = service(ready_library(), threads, FixedClock())
    svc.start_pending_thread(UserId("ada"), TID, "Q?")
    with pytest.raises(ThreadSubjectsError):
        svc.bind_subjects(UserId("ada"), TID, [])
    assert threads.threads[TID].awaiting_subjects
