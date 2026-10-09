"""ConversationService: a thread answers from all the learner's ready documents (PRD §8 US-3)."""

from dataclasses import replace

import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, InMemoryThreads, ingest_ready
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.domain.ids import DocumentId, UserId
from smart_tutor.tutoring.application import (
    DELETED_DOCUMENT,
    ConversationService,
    DocumentUsed,
    NoDocumentsError,
    ThreadNotFoundError,
)


def service(library: InMemoryLibrary, threads: InMemoryThreads, clock: FixedClock) -> ConversationService:
    return ConversationService(threads, DocumentService(library.unit_of_work, max_attempts=3), clock)


def test_starts_a_thread_owned_by_the_learner() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")

    thread = service(library, threads, clock).start_thread(UserId("ada"))

    assert thread.user_id == "ada" and thread.created_at == thread.last_learner_message_at == clock.now()
    assert threads.threads == {thread.thread_id: thread}


def test_a_learner_without_documents_cannot_start_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "bob", "Gradient descent.")  # someone else's document doesn't count

    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).require_documents(UserId("ada"))
    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).start_thread(UserId("ada"))
    assert threads.threads == {}


def test_a_processing_document_is_not_enough_to_start_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(
        UserId("ada"), "processing.pdf"
    )

    with pytest.raises(NoDocumentsError, match="Upload a document first"):
        service(library, threads, FixedClock()).require_documents(UserId("ada"))
    assert threads.threads == {}


def test_an_archived_only_learner_cannot_start_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    document_id = ingest_ready(library, "ada", "Attention is all you need.")
    library.state.documents[document_id].archived = True

    with pytest.raises(NoDocumentsError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"))
    assert threads.threads == {}


LEARNER, OTHER = UserId("ada"), UserId("bob")


def started(
    library: InMemoryLibrary,
) -> tuple[ConversationService, InMemoryThreads, DocumentId, DocumentId, DocumentId]:
    threads = InMemoryThreads()
    a = ingest_ready(library, "ada", "Attention is all you need.")
    b = ingest_ready(library, "ada", "Gradient descent.")
    c = ingest_ready(library, "ada", "Backpropagation.")
    return service(library, threads, FixedClock()), threads, a, b, c


def test_record_answer_keeps_first_use_order_without_duplicates() -> None:
    library = InMemoryLibrary()
    svc, _, a, b, c = started(library)
    thread = svc.start_thread(LEARNER)

    svc.record_answer(thread.thread_id, LEARNER, [a, b, a])
    svc.record_answer(thread.thread_id, LEARNER, [c, b])

    assert [d.document_id for d in svc.documents_used(thread.thread_id, LEARNER)] == [a, b, c]


def test_record_answer_with_no_documents_adds_nothing() -> None:  # a decline
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)
    thread = svc.start_thread(LEARNER)

    svc.record_answer(thread.thread_id, LEARNER, [])

    assert svc.documents_used(thread.thread_id, LEARNER) == []
    assert threads.documents_used_rows == {}


def test_documents_used_show_title_authors_year_and_archived() -> None:
    library = InMemoryLibrary()
    svc, _, a, b, _ = started(library)
    content = library.state.contents[library.state.documents[a].content_id or ""]
    content.title, content.authors, content.year = "Attention Is All You Need", ["Vaswani", "Shazeer"], 2017
    library.state.documents[b].archived = True
    thread = svc.start_thread(LEARNER)
    svc.record_answer(thread.thread_id, LEARNER, [a, b])

    first, second = svc.documents_used(thread.thread_id, LEARNER)

    assert (first.title, first.authors, first.year) == ("Attention Is All You Need", ("Vaswani", "Shazeer"), 2017)
    assert not first.archived and not first.deleted
    assert second.archived and not second.deleted


def test_a_document_that_no_longer_exists_reads_as_deleted() -> None:
    library = InMemoryLibrary()
    svc, _, a, _, _ = started(library)
    thread = svc.start_thread(LEARNER)
    gone = DocumentId("gone")
    svc.record_answer(thread.thread_id, LEARNER, [a, gone])

    _, deleted = svc.documents_used(thread.thread_id, LEARNER)

    assert deleted == DocumentUsed(gone, DELETED_DOCUMENT, (), None, archived=False, deleted=True)


def test_a_deleted_document_keeps_the_title_copied_when_it_was_deleted() -> None:
    library = InMemoryLibrary()
    svc, threads, a, _, _ = started(library)
    thread = svc.start_thread(LEARNER)
    gone = DocumentId("gone")
    svc.record_answer(thread.thread_id, LEARNER, [gone])
    row = threads.documents_used_rows[thread.thread_id][0]
    threads.documents_used_rows[thread.thread_id][0] = replace(row, deleted_title="Old paper")

    [only] = svc.documents_used(thread.thread_id, LEARNER)

    assert only.title == "Old paper" and only.deleted


def test_another_learner_can_neither_record_nor_read() -> None:
    library = InMemoryLibrary()
    svc, threads, a, _, _ = started(library)
    thread = svc.start_thread(LEARNER)

    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        svc.documents_used(thread.thread_id, OTHER)
    with pytest.raises(ThreadNotFoundError):
        svc.record_answer(thread.thread_id, OTHER, [a])
    assert threads.documents_used_rows == {}
