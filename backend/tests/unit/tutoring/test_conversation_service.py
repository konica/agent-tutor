"""ConversationService: a thread answers from all the learner's ready documents (PRD §8 US-3)."""

import logging
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from fakes import (
    APP_TZ,
    TEST_LIMITS,
    TEST_UPLOAD_LIMITS,
    FakeAnswerFeedback,
    FakeObjectStore,
    FixedClock,
    InMemoryLibrary,
    InMemoryThreads,
    ingest_ready,
)
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.domain.ids import DocumentId, RunId, SubjectId, ThreadId, UserId
from smart_tutor.tutoring.application import (
    DELETED_DOCUMENT,
    AnsweredTurn,
    CitationView,
    ConversationService,
    Decline,
    DocumentNotAvailableError,
    DocumentUsed,
    InvalidTitleError,
    NoListedDocumentsError,
    Rating,
    SearchScope,
    ThreadArchivedError,
    ThreadNotFoundError,
    Turn,
    TurnCitation,
    TurnNotFoundError,
)
from smart_tutor.tutoring.domain.thread import ThreadStatus


def service(
    library: InMemoryLibrary,
    threads: InMemoryThreads,
    clock: FixedClock,
    feedback: FakeAnswerFeedback | None = None,
) -> ConversationService:
    return ConversationService(threads, DocumentService(library.unit_of_work, max_attempts=3), clock, feedback)


def test_starts_a_thread_owned_by_the_learner() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")

    thread = service(library, threads, clock).start_thread(UserId("ada"))

    assert thread.user_id == "ada" and thread.created_at == thread.last_learner_message_at == clock.now()
    assert threads.threads == {thread.thread_id: thread}


def test_a_thread_starts_without_ready_documents_so_the_upload_request_is_kept() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    document_id = ingest_ready(library, "ada", "Attention is all you need.")
    library.state.documents[document_id].archived = True  # the agent answers with the upload request (US-3)

    thread = service(library, threads, FixedClock()).start_thread(UserId("ada"), "What is attention?")

    assert threads.threads == {thread.thread_id: thread}


LEARNER, OTHER = UserId("ada"), UserId("bob")


def answered(*document_ids: DocumentId) -> AnsweredTurn:
    return AnsweredTurn("What is attention?", "It weighs tokens.", document_ids=document_ids)


def started(
    library: InMemoryLibrary,
) -> tuple[ConversationService, InMemoryThreads, DocumentId, DocumentId, DocumentId]:
    threads = InMemoryThreads()
    a = ingest_ready(library, "ada", "Attention is all you need.")
    b = ingest_ready(library, "ada", "Gradient descent.")
    c = ingest_ready(library, "ada", "Backpropagation.")
    return service(library, threads, FixedClock()), threads, a, b, c


def test_record_turn_keeps_first_use_order_without_duplicates() -> None:
    library = InMemoryLibrary()
    svc, _, a, b, c = started(library)
    thread = svc.start_thread(LEARNER)

    svc.record_turn(thread.thread_id, LEARNER, answered(a, b, a))
    svc.record_turn(thread.thread_id, LEARNER, answered(c, b))

    assert [d.document_id for d in svc.documents_used(thread.thread_id, LEARNER)] == [a, b, c]


def test_record_turn_with_no_documents_adds_nothing() -> None:  # a decline
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)
    thread = svc.start_thread(LEARNER)

    svc.record_turn(thread.thread_id, LEARNER, answered())

    assert svc.documents_used(thread.thread_id, LEARNER) == []
    assert threads.documents_used_rows == {}


def test_documents_used_show_title_authors_year_and_archived() -> None:
    library = InMemoryLibrary()
    svc, _, a, b, _ = started(library)
    content = library.state.contents[library.state.documents[a].content_id or ""]
    content.title, content.authors, content.year = "Attention Is All You Need", ["Vaswani", "Shazeer"], 2017
    library.state.documents[b].archived = True
    thread = svc.start_thread(LEARNER)
    svc.record_turn(thread.thread_id, LEARNER, answered(a, b))

    first, second = svc.documents_used(thread.thread_id, LEARNER)

    assert (first.title, first.authors, first.year) == ("Attention Is All You Need", ("Vaswani", "Shazeer"), 2017)
    assert not first.archived and not first.deleted
    assert second.archived and not second.deleted


def test_a_document_that_no_longer_exists_reads_as_deleted() -> None:
    library = InMemoryLibrary()
    svc, _, a, _, _ = started(library)
    thread = svc.start_thread(LEARNER)
    gone = DocumentId("gone")
    svc.record_turn(thread.thread_id, LEARNER, answered(a, gone))

    _, deleted = svc.documents_used(thread.thread_id, LEARNER)

    assert deleted == DocumentUsed(
        gone, DELETED_DOCUMENT, (), None, archived=False, deleted=True, added_by="answer", used=True
    )


def test_a_deleted_document_keeps_the_title_copied_when_it_was_deleted() -> None:
    library = InMemoryLibrary()
    svc, threads, a, _, _ = started(library)
    thread = svc.start_thread(LEARNER)
    gone = DocumentId("gone")
    svc.record_turn(thread.thread_id, LEARNER, answered(gone))
    row = threads.documents_used_rows[thread.thread_id][0]
    threads.documents_used_rows[thread.thread_id][0] = replace(row, deleted_title="Old paper")

    [only] = svc.documents_used(thread.thread_id, LEARNER)

    assert only.title == "Old paper" and only.deleted


def test_start_thread_titles_it_with_the_first_question() -> None:
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)

    thread = svc.start_thread(LEARNER, "What is attention?")

    assert threads.threads[thread.thread_id].title == "What is attention?"


def test_update_thread_saves_the_trimmed_title() -> None:
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)
    thread = svc.start_thread(LEARNER, "What is attention?")

    renamed = svc.update_thread(thread.thread_id, LEARNER, title=" Attention basics ")

    assert renamed.title == threads.threads[thread.thread_id].title == "Attention basics"


def test_a_refused_rename_saves_nothing() -> None:
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)
    thread = svc.start_thread(LEARNER, "What is attention?")

    with pytest.raises(InvalidTitleError):
        svc.update_thread(thread.thread_id, LEARNER, title="x" * 121)
    threads.threads[thread.thread_id].status = ThreadStatus.ARCHIVED
    with pytest.raises(ThreadArchivedError):
        svc.update_thread(thread.thread_id, LEARNER, title="New")
    assert threads.threads[thread.thread_id].title == "What is attention?"


def test_another_learner_cannot_rename() -> None:
    library = InMemoryLibrary()
    svc, threads, _, _, _ = started(library)
    thread = svc.start_thread(LEARNER, "What is attention?")

    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        svc.update_thread(thread.thread_id, OTHER, title="Mine now")
    assert threads.threads[thread.thread_id].title == "What is attention?"


def test_another_learner_can_neither_record_nor_read() -> None:
    library = InMemoryLibrary()
    svc, threads, a, _, _ = started(library)
    thread = svc.start_thread(LEARNER)

    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        svc.documents_used(thread.thread_id, OTHER)
    with pytest.raises(ThreadNotFoundError):
        svc.record_turn(thread.thread_id, OTHER, answered(a))
    assert threads.documents_used_rows == {}


def test_a_deleted_document_keeps_its_title_in_the_learners_threads_only() -> None:
    library = InMemoryLibrary()
    svc, _, doc, _, _ = started(library)
    other = UserId("bob")
    ingest_ready(library, "bob", "Something else.")
    thread_a = svc.start_thread(LEARNER)
    thread_b = svc.start_thread(other)
    svc.record_turn(thread_a.thread_id, LEARNER, answered(doc))
    svc.record_turn(
        thread_b.thread_id, other, answered(doc)
    )  # cannot happen in practice; the update is scoped by owner

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
    svc.record_turn(thread.thread_id, LEARNER, answered(doc))

    used = svc.documents_used(thread.thread_id, LEARNER)
    assert [(d.title, d.deleted) for d in used] == [(DELETED_DOCUMENT, True)]


def test_the_learner_adds_ready_documents_listed_as_added_and_unused() -> None:
    library = InMemoryLibrary()
    svc, _, used, added, _ = started(library)
    thread = svc.start_thread(LEARNER)
    svc.record_turn(thread.thread_id, LEARNER, answered(used))

    listed = svc.add_documents(thread.thread_id, LEARNER, [added, used])

    assert [(d.document_id, d.added_by, d.used) for d in listed] == [(used, "answer", True), (added, "learner", False)]
    svc.record_turn(thread.thread_id, LEARNER, answered(added))
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
            UploadService(
                library.unit_of_work,
                FakeObjectStore(),
                FixedClock(),
                TEST_LIMITS,
                rate=TEST_UPLOAD_LIMITS,
                time_zone=APP_TZ,
            )
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
    svc.record_turn(thread.thread_id, LEARNER, answered(a, b))

    svc.remove_document(thread.thread_id, LEARNER, a)

    assert [d.document_id for d in svc.documents_used(thread.thread_id, LEARNER)] == [b]
    assert a in library.state.documents and not library.state.documents[a].archived
    svc.record_turn(thread.thread_id, LEARNER, answered(a))
    listed = svc.documents_used(thread.thread_id, LEARNER)
    assert [d.document_id for d in listed] == [b, a]
    assert listed[1].added_by == "answer"


def test_another_learner_can_neither_add_nor_remove() -> None:
    library = InMemoryLibrary()
    svc, _, a, b, _ = started(library)
    ingest_ready(library, "bob", "Bob's paper.")
    thread = svc.start_thread(LEARNER)
    svc.record_turn(thread.thread_id, LEARNER, answered(a))

    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        svc.add_documents(thread.thread_id, OTHER, [b])
    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        svc.remove_document(thread.thread_id, OTHER, a)

    assert [d.document_id for d in svc.documents_used(thread.thread_id, LEARNER)] == [a]


def started_with_document() -> tuple[ConversationService, InMemoryThreads, ThreadId, DocumentId]:
    library = InMemoryLibrary()
    svc, threads, a, _, _ = started(library)
    thread = svc.start_thread(LEARNER)
    svc.add_documents(thread.thread_id, LEARNER, [a])
    return svc, threads, thread.thread_id, a


def test_limiting_needs_a_listed_document() -> None:
    svc, _, _, _, _ = started(InMemoryLibrary())
    thread = svc.start_thread(LEARNER)
    with pytest.raises(NoListedDocumentsError):
        svc.update_thread(thread.thread_id, LEARNER, search_scope=SearchScope.LISTED)


def test_a_limited_thread_searches_its_listed_documents() -> None:
    svc, _, thread_id, doc = started_with_document()
    svc.update_thread(thread_id, LEARNER, search_scope=SearchScope.LISTED)
    assert svc.get_thread(thread_id, LEARNER).search_scope is SearchScope.LISTED
    assert svc.search_documents(thread_id, LEARNER) == [doc]


def test_an_unlimited_thread_searches_the_library() -> None:
    svc, _, thread_id, _ = started_with_document()
    assert svc.search_documents(thread_id, LEARNER) is None


def test_removing_the_last_listed_document_turns_the_limit_off() -> None:
    svc, _, thread_id, doc = started_with_document()
    svc.update_thread(thread_id, LEARNER, search_scope=SearchScope.LISTED)
    svc.remove_document(thread_id, LEARNER, doc)
    assert svc.get_thread(thread_id, LEARNER).search_scope is SearchScope.LIBRARY


def test_a_bad_title_saves_neither_the_title_nor_the_scope() -> None:
    svc, _, thread_id, _ = started_with_document()
    with pytest.raises(InvalidTitleError):
        svc.update_thread(thread_id, LEARNER, title=" ", search_scope=SearchScope.LISTED)
    assert svc.get_thread(thread_id, LEARNER).search_scope is SearchScope.LIBRARY


def test_another_learners_thread_is_not_found_for_scope_and_search() -> None:
    svc, _, thread_id, _ = started_with_document()
    with pytest.raises(ThreadNotFoundError):
        svc.update_thread(thread_id, OTHER, search_scope=SearchScope.LIBRARY)
    with pytest.raises(ThreadNotFoundError):
        svc.search_documents(thread_id, OTHER)
    with pytest.raises(ThreadNotFoundError):
        svc.get_thread(thread_id, OTHER)


def test_an_archived_thread_can_neither_be_limited_nor_searched() -> None:
    svc, threads, thread_id, _ = started_with_document()
    threads.threads[thread_id].status = ThreadStatus.ARCHIVED
    with pytest.raises(ThreadArchivedError):
        svc.update_thread(thread_id, LEARNER, search_scope=SearchScope.LISTED)
    with pytest.raises(ThreadArchivedError):
        svc.search_documents(thread_id, LEARNER)


def test_a_thread_started_from_a_document_lists_it_as_added_then_marks_it_used() -> None:
    library = InMemoryLibrary()
    svc, _, doc, other, _ = started(library)

    thread = svc.start_thread(LEARNER, "What is attention?", doc)

    [row] = svc.documents_used(thread.thread_id, LEARNER)
    assert (row.document_id, row.added_by, row.used) == (doc, "learner", False)
    svc.record_turn(thread.thread_id, LEARNER, answered(doc, other))
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
            UploadService(
                library.unit_of_work,
                FakeObjectStore(),
                FixedClock(),
                TEST_LIMITS,
                rate=TEST_UPLOAD_LIMITS,
                time_zone=APP_TZ,
            )
            .start_upload(LEARNER, "processing.pdf")
            .document_id
        )
    else:
        bad = DocumentId("00000000-0000-0000-0000-000000000000")

    with pytest.raises(DocumentNotAvailableError, match="Document not found"):
        svc.start_thread(LEARNER, "q", bad)

    assert threads.threads == {}


def test_record_turn_keeps_the_turn_with_its_time_and_owner() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    doc = DocumentId(ingest_ready(library, "ada", "Attention weighs tokens."))
    svc = service(library, threads, clock)
    thread = svc.start_thread(LEARNER, "What is attention?")
    citation = TurnCitation(1, doc, "c1", 3)
    answer = AnsweredTurn("What is attention?", "It weighs [1].", (citation,), document_ids=(doc, doc))

    svc.record_turn(ThreadId(thread.thread_id), LEARNER, answer)

    [kept] = threads.turn_rows
    expected = Turn(
        ThreadId(thread.thread_id), LEARNER, "What is attention?", "It weighs [1].", (citation,), None, clock.now()
    )
    assert kept == expected
    assert [row.document_id for row in threads.documents_used(ThreadId(thread.thread_id))] == [doc]


def test_record_turn_in_another_learners_thread_is_not_found_and_keeps_nothing() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    svc = service(library, threads, clock)
    thread = svc.start_thread(LEARNER, "Q")

    with pytest.raises(ThreadNotFoundError):
        svc.record_turn(ThreadId(thread.thread_id), OTHER, AnsweredTurn("Q", "A"))
    assert threads.turn_rows == []


def test_turns_resolve_citations_now_archived_and_deleted() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    kept_doc = DocumentId(ingest_ready(library, "ada", "Attention weighs tokens."))
    gone = DocumentId("00000000-0000-4000-8000-000000000999")
    svc = service(library, threads, clock)
    t = ThreadId(svc.start_thread(LEARNER, "Q1").thread_id)
    cited = (TurnCitation(1, kept_doc, "c1", 3), TurnCitation(2, gone, "c9", None))
    svc.record_turn(t, LEARNER, AnsweredTurn("Q1", "A [1] [2].", cited))
    svc.record_turn(t, LEARNER, AnsweredTurn("Q2", decline=Decline("limited", "These documents don't cover this.")))
    library.state.documents[kept_doc].archived = True

    first, second = svc.turns(t, LEARNER)

    title = library.state.documents[kept_doc].file_name  # the display title before extraction
    assert first.question == "Q1" and first.answer == "A [1] [2]." and first.decline is None
    assert first.citations == (
        CitationView(1, kept_doc, "c1", 3, title, archived=True, deleted=False),
        CitationView(2, gone, "c9", None, DELETED_DOCUMENT, archived=False, deleted=True),
    )
    assert second.answer == "" and second.citations == ()
    assert second.decline == Decline("limited", "These documents don't cover this.")


def test_turns_of_another_learners_thread_are_not_found() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    svc = service(library, threads, clock)
    t = ThreadId(svc.start_thread(LEARNER, "Q").thread_id)

    with pytest.raises(ThreadNotFoundError):
        svc.turns(t, OTHER)


def test_a_thread_can_start_with_a_given_id() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    given = ThreadId(str(uuid.uuid4()))

    thread = service(library, threads, FixedClock()).start_thread(LEARNER, "Q?", thread_id=given)

    assert thread.thread_id == given
    assert list(threads.threads) == [given]


def test_a_kept_turn_keeps_its_run_id_and_shows_it() -> None:
    svc = service(InMemoryLibrary(), InMemoryThreads(), FixedClock())
    thread = svc.start_thread(LEARNER, "Q?")
    run = RunId(str(uuid.uuid4()))

    svc.record_turn(thread.thread_id, LEARNER, AnsweredTurn("Q?", "A.", run_id=run))

    assert [t.run_id for t in svc.turns(thread.thread_id, LEARNER)] == [run]


def test_a_turn_without_a_run_id_shows_none() -> None:
    svc = service(InMemoryLibrary(), InMemoryThreads(), FixedClock())
    thread = svc.start_thread(LEARNER, "Q?")

    svc.record_turn(thread.thread_id, LEARNER, AnsweredTurn("Q?", "A."))

    assert [t.run_id for t in svc.turns(thread.thread_id, LEARNER)] == [None]


S1, S2, S3 = (SubjectId(f"00000000-0000-4000-8000-00000000000{i}") for i in (1, 2, 3))


def test_lists_the_learners_active_threads_newest_activity_first() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")
    svc = service(library, threads, clock)
    first = svc.start_thread(UserId("ada"), "First?")
    clock.current += timedelta(minutes=1)
    second = svc.start_thread(UserId("ada"), "Second?")
    clock.current += timedelta(minutes=1)
    svc.note_question(ThreadId(first.thread_id), UserId("ada"))  # first is now the newest

    listed = svc.list_threads(UserId("ada"))

    assert [(s.thread_id, s.title) for s in listed] == [(first.thread_id, "First?"), (second.thread_id, "Second?")]
    assert listed[0].last_activity == clock.now()


def test_lists_no_archived_and_no_one_elses_threads() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")
    ingest_ready(library, "bob", "Attention is all you need.")
    svc = service(library, threads, clock)
    kept = svc.start_thread(UserId("ada"), "Mine?")
    archived = svc.start_thread(UserId("ada"), "Old?")
    threads.threads[archived.thread_id].status = ThreadStatus.ARCHIVED
    svc.start_thread(UserId("bob"), "Theirs?")

    assert [s.thread_id for s in svc.list_threads(UserId("ada"))] == [kept.thread_id]


def test_deleted_documents_subjects_dont_count_archived_ones_do() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    d1 = ingest_ready(library, "ada", "Live paper.", subject_ids=[S1])
    d2 = ingest_ready(library, "ada", "Archived paper.", subject_ids=[S2])
    d3 = ingest_ready(library, "ada", "Deleted paper.", subject_ids=[S3])
    svc = service(library, threads, clock)
    thread = svc.start_thread(UserId("ada"), "Q?")
    svc.record_turn(ThreadId(thread.thread_id), UserId("ada"), answered(d1, d2, d3))
    library.state.documents[d2].archived = True
    del library.state.documents[d3]

    [row] = svc.list_threads(UserId("ada"))

    assert row.subject_ids == (S1, S2) and row.documents == 3


def test_a_subject_shared_by_two_documents_appears_once() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    d1 = ingest_ready(library, "ada", "First paper.", subject_ids=[S1, S2])
    d2 = ingest_ready(library, "ada", "Second paper.", subject_ids=[S2, S3])
    svc = service(library, threads, clock)
    thread = svc.start_thread(UserId("ada"), "Q?")
    svc.record_turn(ThreadId(thread.thread_id), UserId("ada"), answered(d1, d2))

    [row] = svc.list_threads(UserId("ada"))

    assert row.subject_ids == (S1, S2, S3) and row.documents == 2


def test_a_thread_with_no_documents_lists_none() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")
    svc = service(library, threads, clock)
    svc.start_thread(UserId("ada"), "Hi?")
    [row] = svc.list_threads(UserId("ada"))
    assert row.subject_ids == () and row.documents == 0


def test_noting_a_question_needs_the_owners_active_thread() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")
    svc = service(library, threads, clock)
    thread = svc.start_thread(UserId("ada"), "Hi?")
    with pytest.raises(ThreadNotFoundError):
        svc.note_question(ThreadId(thread.thread_id), UserId("bob"))
    threads.threads[thread.thread_id].status = ThreadStatus.ARCHIVED
    with pytest.raises(ThreadArchivedError):
        svc.note_question(ThreadId(thread.thread_id), UserId("ada"))


def _rated_setup(
    feedback: FakeAnswerFeedback, *, decline: Decline | None = None
) -> tuple[ConversationService, InMemoryThreads, ThreadId, RunId]:
    threads = InMemoryThreads()
    svc = service(InMemoryLibrary(), threads, FixedClock(), feedback)
    thread = svc.start_thread(LEARNER, "What is attention?")
    thread_id, run = ThreadId(thread.thread_id), RunId(str(uuid.uuid4()))
    kept = (
        AnsweredTurn("What is attention?", decline=decline, run_id=run)
        if decline
        else AnsweredTurn("What is attention?", "It weighs tokens.", run_id=run)
    )
    svc.record_turn(thread_id, LEARNER, kept)
    return svc, threads, thread_id, run


def test_a_learner_rates_their_turn_and_the_rating_is_kept_and_sent() -> None:
    feedback = FakeAnswerFeedback()
    svc, _, thread_id, run = _rated_setup(feedback)

    svc.rate_turn(thread_id, LEARNER, run, Rating.UP)

    [turn] = svc.turns(thread_id, LEARNER)
    assert turn.rating is Rating.UP
    assert feedback.sent == [(run, Rating.UP)]


def test_changing_a_rating_replaces_it() -> None:
    feedback = FakeAnswerFeedback()
    svc, _, thread_id, run = _rated_setup(feedback)

    svc.rate_turn(thread_id, LEARNER, run, Rating.UP)
    svc.rate_turn(thread_id, LEARNER, run, Rating.DOWN)

    [turn] = svc.turns(thread_id, LEARNER)
    assert turn.rating is Rating.DOWN
    assert feedback.sent == [(run, Rating.UP), (run, Rating.DOWN)]


def test_a_declined_turn_can_be_rated() -> None:
    svc, _, thread_id, run = _rated_setup(FakeAnswerFeedback(), decline=Decline("limited", "Not in your documents."))

    svc.rate_turn(thread_id, LEARNER, run, Rating.DOWN)

    assert svc.turns(thread_id, LEARNER)[0].rating is Rating.DOWN


def test_rating_another_learners_thread_is_not_found_and_changes_nothing() -> None:
    feedback = FakeAnswerFeedback()
    svc, _, thread_id, run = _rated_setup(feedback)

    with pytest.raises(ThreadNotFoundError):
        svc.rate_turn(thread_id, OTHER, run, Rating.DOWN)

    assert svc.turns(thread_id, LEARNER)[0].rating is None
    assert feedback.sent == []


def test_rating_a_run_that_is_not_in_the_thread_is_not_found() -> None:
    feedback = FakeAnswerFeedback()
    svc, _, thread_id, _ = _rated_setup(feedback)

    with pytest.raises(TurnNotFoundError):
        svc.rate_turn(thread_id, LEARNER, RunId(str(uuid.uuid4())), Rating.UP)

    assert feedback.sent == []


def test_a_failing_feedback_send_still_keeps_the_rating(caplog: pytest.LogCaptureFixture) -> None:
    svc, _, thread_id, run = _rated_setup(FakeAnswerFeedback(error=RuntimeError("LangSmith down")))

    with caplog.at_level(logging.ERROR):
        svc.rate_turn(thread_id, LEARNER, run, Rating.UP)

    assert svc.turns(thread_id, LEARNER)[0].rating is Rating.UP
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "RuntimeError" in record.getMessage()
    assert LEARNER not in record.getMessage()


def test_an_unrated_turn_reads_none() -> None:
    svc, _, thread_id, _ = _rated_setup(FakeAnswerFeedback())

    assert svc.turns(thread_id, LEARNER)[0].rating is None
