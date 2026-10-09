"""ConversationService: a thread answers from all the learner's ready documents (PRD §8 US-3)."""

from dataclasses import replace

import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, InMemoryThreads, ingest_ready
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.domain.ids import DocumentId, UserId
from smart_tutor.tutoring.application import (
    DELETED_DOCUMENT,
    ConversationService,
    DocumentNotAvailableError,
    DocumentUsed,
    InvalidTitleError,
    NoDocumentsError,
    ThreadArchivedError,
    ThreadNotFoundError,
)
from smart_tutor.tutoring.domain.thread import ThreadStatus


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

    assert deleted == DocumentUsed(
        gone, DELETED_DOCUMENT, (), None, archived=False, deleted=True, added_by="answer", used=True
    )


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


def test_start_thread_titles_it_with_the_first_question() -> None:
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)

    thread = svc.start_thread(LEARNER, "What is attention?")

    assert threads.threads[thread.thread_id].title == "What is attention?"


def test_rename_thread_saves_the_trimmed_title() -> None:
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)
    thread = svc.start_thread(LEARNER, "What is attention?")

    renamed = svc.rename_thread(thread.thread_id, LEARNER, " Attention basics ")

    assert renamed.title == threads.threads[thread.thread_id].title == "Attention basics"


def test_a_refused_rename_saves_nothing() -> None:
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)
    thread = svc.start_thread(LEARNER, "What is attention?")

    with pytest.raises(InvalidTitleError):
        svc.rename_thread(thread.thread_id, LEARNER, "x" * 121)
    threads.threads[thread.thread_id].status = ThreadStatus.ARCHIVED
    with pytest.raises(ThreadArchivedError):
        svc.rename_thread(thread.thread_id, LEARNER, "New")
    assert threads.threads[thread.thread_id].title == "What is attention?"


def test_another_learner_cannot_rename() -> None:
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)
    thread = svc.start_thread(LEARNER, "What is attention?")

    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        svc.rename_thread(thread.thread_id, OTHER, "Mine now")
    assert threads.threads[thread.thread_id].title == "What is attention?"


def test_another_learner_can_neither_record_nor_read() -> None:
    library = InMemoryLibrary()
    svc, threads, a, _, _ = started(library)
    thread = svc.start_thread(LEARNER)

    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        svc.documents_used(thread.thread_id, OTHER)
    with pytest.raises(ThreadNotFoundError):
        svc.record_answer(thread.thread_id, OTHER, [a])
    assert threads.documents_used_rows == {}


def test_a_deleted_document_keeps_its_title_in_the_learners_threads_only() -> None:
    library = InMemoryLibrary()
    svc, _, doc, _, _ = started(library)
    other = UserId("bob")
    ingest_ready(library, "bob", "Something else.")
    thread_a = svc.start_thread(LEARNER)
    thread_b = svc.start_thread(other)
    svc.record_answer(thread_a.thread_id, LEARNER, [doc])
    svc.record_answer(thread_b.thread_id, other, [doc])  # cannot happen in practice; the update is scoped by owner

    svc.keep_deleted_title(LEARNER, doc, "Chain-of-Thought Prompting")
    library.state.documents.pop(doc)

    used_a = svc.documents_used(thread_a.thread_id, LEARNER)
    used_b = svc.documents_used(thread_b.thread_id, other)
    assert [(d.title, d.deleted) for d in used_a] == [("Chain-of-Thought Prompting", True)]
    assert [(d.title, d.deleted) for d in used_b] == [(DELETED_DOCUMENT, True)]


def test_an_answer_saved_after_the_delete_lists_the_document_as_deleted() -> None:
    library = InMemoryLibrary()
    svc, _, doc, _, _ = started(library)
    thread = svc.start_thread(LEARNER)

    library.state.documents.pop(doc)
    svc.record_answer(thread.thread_id, LEARNER, [doc])

    used = svc.documents_used(thread.thread_id, LEARNER)
    assert [(d.title, d.deleted) for d in used] == [(DELETED_DOCUMENT, True)]


def test_the_learner_adds_ready_documents_listed_as_added_and_unused() -> None:
    library = InMemoryLibrary()
    svc, _, used, added, _ = started(library)
    thread = svc.start_thread(LEARNER)
    svc.record_answer(thread.thread_id, LEARNER, [used])

    listed = svc.add_documents(thread.thread_id, LEARNER, [added, used])

    assert [(d.document_id, d.added_by, d.used) for d in listed] == [(used, "answer", True), (added, "learner", False)]
    svc.record_answer(thread.thread_id, LEARNER, [added])
    assert [(d.document_id, d.added_by, d.used) for d in svc.documents_used(thread.thread_id, LEARNER)] == [
        (used, "answer", True),
        (added, "learner", True),
    ]


@pytest.mark.parametrize("kind", ["foreign", "archived", "processing", "unknown"])
def test_only_the_learners_ready_active_documents_can_be_added(kind: str) -> None:
    library = InMemoryLibrary()
    svc, _, good, _, _ = started(library)
    thread = svc.start_thread(LEARNER)
    bad: DocumentId
    if kind == "foreign":
        bad = ingest_ready(library, "bob", "Someone else's paper.")
    elif kind == "archived":
        bad = ingest_ready(library, "ada", "An archived paper.")
        library.state.documents[bad].archived = True
    elif kind == "processing":
        bad = (
            UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS)
            .start_upload(LEARNER, "processing.pdf")
            .document_id
        )
    else:
        bad = DocumentId("00000000-0000-0000-0000-000000000000")

    with pytest.raises(DocumentNotAvailableError, match="Document not found"):
        svc.add_documents(thread.thread_id, LEARNER, [good, bad])

    assert svc.documents_used(thread.thread_id, LEARNER) == []


def test_removing_a_document_takes_it_off_the_list_until_an_answer_uses_it_again() -> None:
    library = InMemoryLibrary()
    svc, _, a, b, _ = started(library)
    thread = svc.start_thread(LEARNER)
    svc.record_answer(thread.thread_id, LEARNER, [a, b])

    svc.remove_document(thread.thread_id, LEARNER, a)

    assert [d.document_id for d in svc.documents_used(thread.thread_id, LEARNER)] == [b]
    assert a in library.state.documents and not library.state.documents[a].archived
    svc.record_answer(thread.thread_id, LEARNER, [a])
    listed = svc.documents_used(thread.thread_id, LEARNER)
    assert [d.document_id for d in listed] == [b, a]
    assert listed[1].added_by == "answer"


def test_another_learner_can_neither_add_nor_remove() -> None:
    library = InMemoryLibrary()
    svc, _, a, b, _ = started(library)
    ingest_ready(library, "bob", "Bob's paper.")
    thread = svc.start_thread(LEARNER)
    svc.record_answer(thread.thread_id, LEARNER, [a])

    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        svc.add_documents(thread.thread_id, OTHER, [b])
    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        svc.remove_document(thread.thread_id, OTHER, a)

    assert [d.document_id for d in svc.documents_used(thread.thread_id, LEARNER)] == [a]


def test_a_thread_started_from_a_document_lists_it_as_added_then_marks_it_used() -> None:
    library = InMemoryLibrary()
    svc, _, doc, other, _ = started(library)

    thread = svc.start_thread(LEARNER, "What is attention?", doc)

    [row] = svc.documents_used(thread.thread_id, LEARNER)
    assert (row.document_id, row.added_by, row.used) == (doc, "learner", False)
    svc.record_answer(thread.thread_id, LEARNER, [doc, other])
    assert [(d.document_id, d.added_by, d.used) for d in svc.documents_used(thread.thread_id, LEARNER)] == [
        (doc, "learner", True),
        (other, "answer", True),
    ]


@pytest.mark.parametrize("kind", ["foreign", "archived", "processing", "unknown"])
def test_a_thread_starts_only_from_the_learners_ready_active_document(kind: str) -> None:
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)
    bad: DocumentId
    if kind == "foreign":
        bad = ingest_ready(library, "bob", "Someone else's paper.")
    elif kind == "archived":
        bad = ingest_ready(library, "ada", "An archived paper.")
        library.state.documents[bad].archived = True
    elif kind == "processing":
        bad = (
            UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS)
            .start_upload(LEARNER, "processing.pdf")
            .document_id
        )
    else:
        bad = DocumentId("00000000-0000-0000-0000-000000000000")

    with pytest.raises(DocumentNotAvailableError, match="Document not found"):
        svc.start_thread(LEARNER, "q", bad)

    assert threads.threads == {}
